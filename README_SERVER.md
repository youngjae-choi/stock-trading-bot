# Server Execution Guide

This guide provides instructions on how to run the FastAPI backend and static console for the Stock Trading Bot.

## Components and Ports

| Component | Port | Description |
|-----------|------|-------------|
| **Backend API + Static Console** | `8000` | FastAPI server for KIS API services, health checks, `/`, and `/console`. |

## VM, DDNS, and Double NAT Access

When the service runs inside a VM behind DDNS and double NAT, browser access must use the DDNS hostname and the forwarded external port, not the VM's internal port directly.

- Browser access example: `http://your-ddns-host:18000/console`
- Recommended mapping: external `18000` -> VM `8000`
- Operators should treat `127.0.0.1:8000` as a VM-local address, not a PM browser URL.

### Operator Checklist

1. Configure router NAT first: external port `18000` -> notebook/host port `18000`.
2. Configure the second hop on the notebook or VM host: host `18000` -> VM `192.168.89.128:8000`.
4. Verify the DDNS hostname resolves to the router's public address before asking PM to test.
5. Share the console URL as `http://<your-ddns-host>:18000/console` with PM. Do not send `localhost`, `127.0.0.1`, or `192.168.89.128` unless the user is already inside that notebook/VM network.

## Quick Start

### 1. Environment Setup
Run the following script to create a virtual environment and install dependencies.
```bash
./setup_env.sh
```
*Note: This script will prefer `uv` if installed, otherwise it uses `venv`.*

### 2. Configuration
Copy `.env.example` to `.env` and fill in your KIS API credentials.
```bash
cp .env.example .env
# Edit .env with your KIS_APP_KEY, KIS_APP_SECRET, etc.
```

### 3. Run Server
Execute the following script to start the FastAPI server:
```bash
./run.sh
```
The script starts the backend with `python3 -m uvicorn backend.main:app`, which avoids the package import failure that occurs when launching `backend/main.py` directly.

Useful modes:

```bash
./run.sh --check
./run.sh --systemd
```

### 4. KIS Rate-Limit Policy

The backend includes an operator-controlled KIS rate-limit profile.

- `KIS_SERVICE_APPLY_DATE=YYYY-MM-DD`: enables automatic switching from the new-account profile to the standard profile.
- `KIS_RATE_LIMIT_PROFILE=auto|new_account|standard`: forces or auto-selects the profile.
- `KIS_RATE_LIMIT_NEW_ACCOUNT_RPS=2`: conservative real-account startup profile for the first 3 calendar days including apply date.
- `KIS_RATE_LIMIT_STANDARD_RPS=20`: standard real-account profile after day 3.
- `KIS_RATE_LIMIT_RPS`: optional fixed override when operations require a manual cap.

Check the active profile at:

```bash
curl -fsS http://127.0.0.1:8000/health
```

### 5. Systemd Installation

Template and helper files are included for boot-time startup and automatic restart.

```bash
./scripts/install_systemd_service.sh --check
sudo ./scripts/install_systemd_service.sh --install --enable --start
./scripts/service_healthcheck.sh
```

Installed service name: `stock-trading-bot.service`

### 6. External Access Example

For a common double NAT setup:

1. Forward router external port `18000` to the VM's `8000` port.
3. Ensure the notebook or hypervisor network mode forwards those ports into the VM.
4. Open the console in a browser with `http://<your-ddns-host>:18000/console`.

## API Endpoints (v1)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Check backend health and KIS config status. |
| GET | `/api/v1/kis/token/status` | Check KIS OAuth token status and expiration. |
| GET | `/api/v1/kis/price/{symbol}` | Fetch current price for a domestic stock. |
| GET | `/api/v1/kis/orderbook/{symbol}` | Fetch current order book via `/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn` (`tr_id=FHKST01010200`). |
| GET | `/api/v1/kis/balance` | Fetch account balance and holdings via `/uapi/domestic-stock/v1/trading/inquire-balance` (`TTTC8434R` real, `VTTC8434R` virtual). |

## Error Handling

When KIS environment variables are missing, KIS endpoints stay online and return a JSON error payload instead of crashing startup:

```json
{
  "ok": false,
  "error": {
    "code": "KIS_CONFIG_MISSING",
    "message": "KIS API credentials are not configured.",
    "missing_fields": ["KIS_APP_KEY", "KIS_APP_SECRET"]
  }
}
```

`/health` remains available regardless of KIS configuration and reports `kis_configured` plus `missing_kis_config`.

For KIS domestic stock balance, the backend sends the required query fields `CANO`, `ACNT_PRDT_CD`, `AFHR_FLPR_YN`, `OFL_YN`, `INQR_DVSN`, `UNPR_DVSN`, `FUND_STTL_ICLD_YN`, `FNCG_AMT_AUTO_RDPT_YN`, `PRCS_DVSN`, `CTX_AREA_FK100`, and `CTX_AREA_NK100`.

## File Structure
- `backend/main.py`: FastAPI server implementation.
- `requirements.txt`: Python dependency list.
- `setup_env.sh`: Virtual environment setup script.
- `run.sh`: Server execution script.
- `systemd/stock-trading-bot.service`: systemd unit template.
- `scripts/install_systemd_service.sh`: systemd install helper.
- `scripts/service_healthcheck.sh`: local/systemd health helper.
