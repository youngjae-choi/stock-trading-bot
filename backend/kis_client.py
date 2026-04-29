import asyncio
import httpx
import logging
import time
from datetime import datetime
from typing import Dict, Any, Optional, Literal
from .config import settings, mask_secret
from .utils import kis_rate_limiter, retry_on_kis_error

logger = logging.getLogger("KISClient")

class KISClient:
    def __init__(self):
        self.base_url = settings.KIS_URL
        self.app_key = settings.KIS_APP_KEY
        self.app_secret = settings.KIS_APP_SECRET
        self.token: Optional[str] = None
        self.token_expires_at: float = 0
        self._token_lock = asyncio.Lock()

    def _is_virtual_trading(self) -> bool:
        """Return whether the configured KIS endpoint is the mock trading host."""
        return "openapivts" in self.base_url.lower()

    def _order_env(self) -> Literal["demo", "real"]:
        """Return environment label used by KIS TR-id branching."""
        return "demo" if self._is_virtual_trading() else "real"

    def _build_kis_error_message(self, response: httpx.Response, context: str) -> str:
        """Keep KIS error details intact and avoid returning an empty error string."""
        raw_text = response.text.strip()
        msg_cd = ""
        msg1 = ""

        try:
            payload = response.json()
        except ValueError:
            payload = None

        if isinstance(payload, dict):
            msg_cd = str(payload.get("msg_cd") or "").strip()
            msg1 = str(payload.get("msg1") or "").strip()

        details = raw_text or " ".join(part for part in [msg_cd, msg1] if part).strip()
        if not details:
            details = f"HTTP {response.status_code} from KIS API"

        return f"{context}: {details}"

    async def _get_token(self) -> str:
        """Issue or return valid OAuth token."""
        if self.token and self.token_expires_at > time.time() + 60:
            return self.token

        async with self._token_lock:
            if self.token and self.token_expires_at > time.time() + 60:
                return self.token

            logger.info("START: KIS OAuth Token Issuance")
            url = f"{self.base_url}/oauth2/tokenP"
            data = {
                "grant_type": "client_credentials",
                "appkey": self.app_key,
                "appsecret": self.app_secret
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=data)
                if response.status_code != 200:
                    logger.error(f"FAIL: Token issuance failed. Status: {response.status_code}, Body: {response.text}")
                    raise Exception(self._build_kis_error_message(response, "KIS Token Error"))

                res_data = response.json()
                self.token = res_data["access_token"]
                # Typically valid for 24 hours, but we use 'expires_in' if provided
                expires_in = int(res_data.get("expires_in", 86400))
                self.token_expires_at = time.time() + expires_in

                logger.info(f"SUCCESS: KIS OAuth Token Issued (Masked: {mask_secret(self.token)})")
                return self.token

    @retry_on_kis_error()
    async def get_current_price(self, symbol: str) -> Dict[str, Any]:
        """Fetch current price for a given stock symbol."""
        await kis_rate_limiter.wait()
        token = await self._get_token()
        
        logger.info(f"START: Fetching Current Price for {symbol}")
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-price"
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": "FHKST01010100"
        }
        params = {
            "fid_cond_mrkt_div_code": "J",
            "fid_input_iscd": symbol
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, params=params)
            if response.status_code != 200:
                logger.error(f"FAIL: Price inquiry failed for {symbol}. Status: {response.status_code}")
                raise Exception(self._build_kis_error_message(response, f"KIS API Error ({symbol} price)"))
            
            logger.info(f"SUCCESS: Current Price for {symbol} retrieved.")
            return response.json()

    @retry_on_kis_error()
    async def get_order_book(self, symbol: str) -> Dict[str, Any]:
        """Fetch order book (quotes) for a given stock symbol."""
        await kis_rate_limiter.wait()
        token = await self._get_token()
        
        logger.info(f"START: Fetching Order Book for {symbol}")
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn"
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": "FHKST01010200"
        }
        params = {
            "fid_cond_mrkt_div_code": "J",
            "fid_input_iscd": symbol
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, params=params)
            if response.status_code != 200:
                logger.error(f"FAIL: Order book inquiry failed for {symbol}.")
                raise Exception(self._build_kis_error_message(response, f"KIS API Error ({symbol} orderbook)"))
            
            logger.info(f"SUCCESS: Order Book for {symbol} retrieved.")
            return response.json()

    @retry_on_kis_error()
    async def get_balance(self) -> Dict[str, Any]:
        """Fetch account balance and holdings."""
        await kis_rate_limiter.wait()
        token = await self._get_token()
        
        logger.info(f"START: Fetching Account Balance")
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": "VTTC8434R" if self._is_virtual_trading() else "TTTC8434R"
        }

        params = {
            "CANO": settings.KIS_CANO,
            "ACNT_PRDT_CD": settings.KIS_ACNT_PRDT_CD,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "01",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "00",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": ""
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, params=params)
            if response.status_code != 200:
                logger.error("FAIL: Balance inquiry failed.")
                raise Exception(self._build_kis_error_message(response, "KIS API Error (balance)"))
            
            logger.info("SUCCESS: Account Balance retrieved.")
            return response.json()

    @retry_on_kis_error()
    async def order_cash(
        self,
        *,
        side: Literal["buy", "sell"],
        symbol: str,
        qty: int,
        price: str,
        ord_dvsn: str = "00",
        excg_id_dvsn_cd: str = "KRX",
        sll_type: str = "",
        cndt_pric: str = "",
    ) -> Dict[str, Any]:
        """Place a cash order (buy/sell)."""
        await kis_rate_limiter.wait()
        token = await self._get_token()
        env = self._order_env()
        side_value = side.lower()
        if side_value not in {"buy", "sell"}:
            raise ValueError("side must be 'buy' or 'sell'")

        tr_id_map = {
            ("real", "sell"): "TTTC0011U",
            ("real", "buy"): "TTTC0012U",
            ("demo", "sell"): "VTTC0011U",
            ("demo", "buy"): "VTTC0012U",
        }
        tr_id = tr_id_map[(env, side_value)]
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-cash"
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
        }
        body = {
            "CANO": settings.KIS_CANO,
            "ACNT_PRDT_CD": settings.KIS_ACNT_PRDT_CD,
            "PDNO": symbol,
            "ORD_DVSN": ord_dvsn,
            "ORD_QTY": str(qty),
            "ORD_UNPR": str(price),
            "EXCG_ID_DVSN_CD": excg_id_dvsn_cd,
            "SLL_TYPE": sll_type,
            "CNDT_PRIC": cndt_pric,
        }
        logger.info("START: KIS order-cash side=%s symbol=%s qty=%s", side_value, symbol, qty)
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=body)
            if response.status_code != 200:
                logger.error("FAIL: order-cash failed side=%s symbol=%s", side_value, symbol)
                raise Exception(self._build_kis_error_message(response, "KIS API Error (order-cash)"))
            logger.info("SUCCESS: KIS order-cash side=%s symbol=%s", side_value, symbol)
            return response.json()

    @retry_on_kis_error()
    async def order_rvsecncl(
        self,
        *,
        orgn_odno: str,
        qty: int,
        mode: Literal["modify", "cancel"],
        order_qty: int = 0,
        order_price: str = "0",
        ord_dvsn: str = "00",
        q_ord_yn: str = "N",
    ) -> Dict[str, Any]:
        """Modify or cancel an existing stock order."""
        await kis_rate_limiter.wait()
        token = await self._get_token()
        env = self._order_env()
        mode_value = mode.lower()
        if mode_value not in {"modify", "cancel"}:
            raise ValueError("mode must be 'modify' or 'cancel'")

        tr_id_map = {
            ("real", "modify"): "TTTC0013U",
            ("real", "cancel"): "TTTC0014U",
            ("demo", "modify"): "VTTC0013U",
            ("demo", "cancel"): "VTTC0014U",
        }
        tr_id = tr_id_map[(env, mode_value)]
        rvse_cncl_dvsn_cd = "01" if mode_value == "modify" else "02"
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-rvsecncl"
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
        }
        body = {
            "CANO": settings.KIS_CANO,
            "ACNT_PRDT_CD": settings.KIS_ACNT_PRDT_CD,
            "KRX_FWDG_ORD_ORGNO": "",
            "ORGN_ODNO": orgn_odno,
            "ORD_DVSN": ord_dvsn,
            "RVSE_CNCL_DVSN_CD": rvse_cncl_dvsn_cd,
            "ORD_QTY": str(qty),
            "ORD_UNPR": str(order_price),
            "QTY_ALL_ORD_YN": q_ord_yn,
        }
        if mode_value == "modify":
            body["MGCO_APTM_ODNO"] = ""
            body["ORD_OBJT_CBLC_DVSN_CD"] = "10"
            body["ORD_QTY"] = str(order_qty)
        logger.info("START: KIS order-rvsecncl mode=%s orgn_odno=%s", mode_value, orgn_odno)
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=body)
            if response.status_code != 200:
                logger.error("FAIL: order-rvsecncl failed mode=%s orgn_odno=%s", mode_value, orgn_odno)
                raise Exception(self._build_kis_error_message(response, "KIS API Error (order-rvsecncl)"))
            logger.info("SUCCESS: KIS order-rvsecncl mode=%s orgn_odno=%s", mode_value, orgn_odno)
            return response.json()

    @retry_on_kis_error()
    async def order_resv(
        self,
        *,
        symbol: str,
        qty: int,
        price: str,
        side_code: Literal["01", "02"],
        ord_dvsn_cd: str = "00",
        ord_objt_cblc_dvsn_cd: str = "10",
        loan_dt: str = "",
        rsvn_ord_end_dt: str = "",
        ldng_dt: str = "",
    ) -> Dict[str, Any]:
        """Place a reservation order."""
        await kis_rate_limiter.wait()
        token = await self._get_token()
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-resv"
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": "CTSC0008U",
        }
        body = {
            "CANO": settings.KIS_CANO,
            "ACNT_PRDT_CD": settings.KIS_ACNT_PRDT_CD,
            "PDNO": symbol,
            "ORD_QTY": str(qty),
            "ORD_UNPR": str(price),
            "SLL_BUY_DVSN_CD": side_code,
            "ORD_DVSN_CD": ord_dvsn_cd,
            "ORD_OBJT_CBLC_DVSN_CD": ord_objt_cblc_dvsn_cd,
            "LOAN_DT": loan_dt,
            "RSVN_ORD_END_DT": rsvn_ord_end_dt,
            "LDNG_DT": ldng_dt,
        }
        logger.info("START: KIS order-resv symbol=%s qty=%s side=%s", symbol, qty, side_code)
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=body)
            if response.status_code != 200:
                logger.error("FAIL: order-resv failed symbol=%s side=%s", symbol, side_code)
                raise Exception(self._build_kis_error_message(response, "KIS API Error (order-resv)"))
            logger.info("SUCCESS: KIS order-resv symbol=%s side=%s", symbol, side_code)
            return response.json()

    @retry_on_kis_error()
    async def get_news_title(
        self,
        *,
        symbol: str,
        date_yyyymmdd: str | None = None,
        time_hhmmss: str = "000000",
    ) -> Dict[str, Any]:
        """Fetch comprehensive market/disclosure title feed for a symbol."""
        await kis_rate_limiter.wait()
        token = await self._get_token()
        date_value = date_yyyymmdd or datetime.now().strftime("%Y%m%d")
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/news-title"
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": "FHKST01011800",
        }
        params = {
            "FID_NEWS_OFER_ENTP_CODE": "2",
            "FID_COND_MRKT_CLS_CODE": "00",
            "FID_INPUT_ISCD": symbol,
            "FID_TITL_CNTT": "",
            "FID_INPUT_DATE_1": date_value,
            "FID_INPUT_HOUR_1": time_hhmmss,
            "FID_RANK_SORT_CLS_CODE": "01",
            "FID_INPUT_SRNO": "1",
        }
        logger.info("START: KIS news-title symbol=%s date=%s", symbol, date_value)
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, params=params)
            if response.status_code != 200:
                logger.error("FAIL: news-title failed symbol=%s", symbol)
                raise Exception(self._build_kis_error_message(response, "KIS API Error (news-title)"))
            logger.info("SUCCESS: KIS news-title symbol=%s", symbol)
            return response.json()

    @retry_on_kis_error()
    async def get_daily_chart(
        self,
        *,
        symbol: str,
        period_code: Literal["D", "W", "M"] = "D",
        adjusted_price: Literal["0", "1"] = "1",
    ) -> Dict[str, Any]:
        """Fetch daily/weekly/monthly historical price chart data."""
        await kis_rate_limiter.wait()
        token = await self._get_token()
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-daily-price"
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": "FHKST01010400",
        }
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": symbol,
            "FID_PERIOD_DIV_CODE": period_code,
            "FID_ORG_ADJ_PRC": adjusted_price,
        }
        logger.info("START: KIS daily-chart symbol=%s period=%s", symbol, period_code)
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, params=params)
            if response.status_code != 200:
                logger.error("FAIL: daily-chart failed symbol=%s", symbol)
                raise Exception(self._build_kis_error_message(response, "KIS API Error (daily-chart)"))
            logger.info("SUCCESS: KIS daily-chart symbol=%s", symbol)
            return response.json()

    @retry_on_kis_error()
    async def get_intraday_chart(
        self,
        *,
        symbol: str,
        input_hour: str = "153000",
        include_past: Literal["Y", "N"] = "Y",
        market_code: Literal["J", "NX", "UN"] = "J",
        etc_code: str = "",
    ) -> Dict[str, Any]:
        """Fetch intraday minute-bar chart data (same-day)."""
        await kis_rate_limiter.wait()
        token = await self._get_token()
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": "FHKST03010200",
        }
        params = {
            "FID_COND_MRKT_DIV_CODE": market_code,
            "FID_INPUT_ISCD": symbol,
            "FID_INPUT_HOUR_1": input_hour,
            "FID_PW_DATA_INCU_YN": include_past,
            "FID_ETC_CLS_CODE": etc_code,
        }
        logger.info("START: KIS intraday-chart symbol=%s hour=%s", symbol, input_hour)
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, params=params)
            if response.status_code != 200:
                logger.error("FAIL: intraday-chart failed symbol=%s", symbol)
                raise Exception(self._build_kis_error_message(response, "KIS API Error (intraday-chart)"))
            logger.info("SUCCESS: KIS intraday-chart symbol=%s", symbol)
            return response.json()

kis_client = KISClient()
