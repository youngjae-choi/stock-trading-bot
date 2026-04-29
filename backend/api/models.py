"""Pydantic request models for API routes."""

from __future__ import annotations

from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field


class KISCashOrderRequest(BaseModel):
    side: Literal["buy", "sell"] = Field(..., description="buy or sell")
    symbol: str = Field(..., min_length=1, max_length=12, description="Stock symbol")
    qty: int = Field(..., ge=1, le=1_000_000, description="Order quantity")
    price: str = Field(..., min_length=1, max_length=32, description="Order price")
    ord_dvsn: str = Field(default="00", description="Order type code")
    excg_id_dvsn_cd: str = Field(default="KRX", description="Exchange code")
    sll_type: str = Field(default="", description="Sell type")
    cndt_pric: str = Field(default="", description="Conditional price")


class KISRvseCnclRequest(BaseModel):
    mode: Literal["modify", "cancel"] = Field(..., description="modify or cancel")
    orgn_odno: str = Field(..., min_length=1, max_length=64, description="Original order number")
    qty: int = Field(default=0, ge=0, le=1_000_000, description="Quantity")
    order_qty: int = Field(default=0, ge=0, le=1_000_000, description="New quantity for modify")
    order_price: str = Field(default="0", max_length=32, description="New price")
    ord_dvsn: str = Field(default="00", max_length=8, description="Order type code")
    qty_all_ord_yn: Literal["Y", "N"] = Field(default="N", description="All quantity cancel flag")


class KISReserveOrderRequest(BaseModel):
    side: Literal["buy", "sell"] = Field(..., description="buy or sell")
    symbol: str = Field(..., min_length=1, max_length=12, description="Stock symbol")
    qty: int = Field(..., ge=1, le=1_000_000, description="Order quantity")
    price: str = Field(..., min_length=1, max_length=32, description="Order price")
    ord_dvsn_cd: str = Field(default="00", description="Order type code")
    ord_objt_cblc_dvsn_cd: str = Field(default="10", description="Cash/loan balance code")
    loan_dt: str = Field(default="", description="Loan date")
    rsvn_ord_end_dt: str = Field(default="", description="Reservation end date")
    ldng_dt: str = Field(default="", description="Lending date")


class KISOverseasCashOrderRequest(BaseModel):
    side: Literal["buy", "sell"] = Field(..., description="buy or sell")
    exchange: str = Field(..., min_length=3, max_length=8, description="Overseas exchange code")
    symbol: str = Field(..., min_length=1, max_length=12, description="Ticker")
    qty: int = Field(..., ge=1, le=1_000_000, description="Order quantity")
    price: str = Field(..., min_length=1, max_length=32, description="Order price")
    ord_dvsn: str = Field(default="00", description="Order division code")


class KISOverseasRvseCnclRequest(BaseModel):
    mode: Literal["modify", "cancel"] = Field(..., description="modify or cancel")
    exchange: str = Field(..., min_length=3, max_length=8, description="Overseas exchange code")
    symbol: str = Field(..., min_length=1, max_length=12, description="Ticker")
    orgn_odno: str = Field(..., min_length=1, max_length=64, description="Original order number")
    qty: int = Field(default=0, ge=0, le=1_000_000, description="Quantity")
    order_price: str = Field(default="0", max_length=32, description="Order price")


class TelegramTestRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1024)


class SimOrderRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=12, description="Stock symbol")
    side: Literal["BUY", "SELL"] = Field(..., description="Order side")
    qty: int = Field(..., ge=1, le=1_000_000, description="Order quantity")
    price: float = Field(..., gt=0, description="Order price")


class SmokeRunRequest(BaseModel):
    base_url: str = Field(default="http://127.0.0.1:8000", min_length=1, max_length=200)
    include_schema_only: bool = Field(default=True)
    timeout_seconds: float = Field(default=25.0, ge=3.0, le=120.0)


class DomesticFilterConditionRequest(BaseModel):
    key: str = Field(..., min_length=1, max_length=64)
    enabled: bool = Field(default=True)
    op: str = Field(default="eq", min_length=1, max_length=32)
    value: Any = Field(default=None)
    value_to: Any = Field(default=None)


class DomesticFilterConsoleRequest(BaseModel):
    keyword: str = Field(default="", max_length=120)
    symbols: List[str] = Field(default_factory=list, max_length=200)
    manual_symbols: List[str] = Field(default_factory=list, max_length=200)
    universe_mode: str | None = Field(default=None, max_length=32)
    market: Literal["KOSPI", "KOSDAQ", "ALL"] | None = Field(default=None)
    top_n: int | None = Field(default=None, ge=1, le=200)
    limit: int = Field(default=30, ge=1, le=200)
    max_candidates: int = Field(default=80, ge=1, le=200)
    selected_tests: List[str] = Field(default_factory=list, max_length=100)
    conditions: List[DomesticFilterConditionRequest] = Field(default_factory=list, max_length=200)
    universe_filters: List[DomesticFilterConditionRequest] = Field(default_factory=list, max_length=200)
    timing_filters: List[DomesticFilterConditionRequest] = Field(default_factory=list, max_length=200)
    change_filters: List[DomesticFilterConditionRequest] = Field(default_factory=list, max_length=200)
    include_raw: bool = Field(default=True)
    include_failed_rows: bool = Field(default=False)


class StrategyParamSchema(BaseModel):
    market: Literal["domestic", "overseas", "all"] = Field(default="domestic")
    limit: int = Field(default=20, ge=1, le=100)
    min_turnover: float = Field(default=0, ge=0)
    volatility_min: float = Field(default=0, ge=0)
    volatility_max: float = Field(default=0, ge=0)
    price_min: float = Field(default=0, ge=0)
    price_max: float = Field(default=0, ge=0)
    volume_min: float = Field(default=0, ge=0)
    volume_max: float = Field(default=0, ge=0)


class StrategySearchFilterRequest(BaseModel):
    keyword: str = Field(default="", max_length=120)
    market: Literal["domestic", "overseas", "all"] = Field(default="domestic")
    strategy: StrategyParamSchema = Field(default_factory=StrategyParamSchema)
    max_candidates: int = Field(default=30, ge=1, le=100)


class AutoTradeExecuteRequest(BaseModel):
    mode: Literal["dry_run", "live"] = Field(default="dry_run")
    market: Literal["domestic", "overseas"] = Field(default="domestic")
    exchange: str = Field(default="NASD", min_length=3, max_length=8)
    symbol: str = Field(..., min_length=1, max_length=16)
    side: Literal["buy", "sell"] = Field(..., description="buy or sell")
    qty: int = Field(..., ge=1, le=1_000_000)
    price: str = Field(..., min_length=1, max_length=32)
    confirm_text: str = Field(default="", max_length=64)
