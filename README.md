## 🚀 Quick Start

### 1. Clone & Setup Environment

```bash
git clone <your-repo> EA_BOT_TRADING
cd EA_BOT_TRADING

# Create virtual environment
python -m venv venv
source venv/bin/activate          # Linux/Mac
venv\Scripts\activate             # Windows

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp config/.env.example .env
# Edit .env with your credentials:
#   MT5_ACCOUNT, MT5_PASSWORD, MT5_SERVER
#   TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
#   SECRET_KEY (generate with: python -c "import secrets; print(secrets.token_hex(32))")
```

### 3. Start the API Server

```bash
python main.py
# API available at: http://localhost:8000
# Swagger docs:     http://localhost:8000/docs
```

### 4. Install MT5 EA

1. Copy `mql5/Experts/EA_BotTrading.mq5` to your MT5 `Experts` folder
2. Copy all `.mqh` files from `mql5/Include/` to MT5 `Include` folder
3. Open MetaEditor → Compile `EA_BotTrading.mq5`
4. Attach EA to chart (any symbol, H1 or H4 recommended)
5. Enable "Allow algorithmic trading" and "Allow DLL imports"

### 5. Start MT5 Bridge (Windows only)

```bash
# On the Windows machine running MetaTrader 5:
python python/core/mt5_bridge.py
```

### 6. Start Telegram Bot

```python
# Add to main.py startup or run standalone:
from telegram.bot import build_bot
app = build_bot(token=settings.TELEGRAM_BOT_TOKEN, admin_ids=settings.TELEGRAM_ADMIN_IDS)
app.run_polling()
```

---

## 🐳 Docker Deployment

```bash
cd docker

# Development (SQLite):
docker compose up -d api

# Production (PostgreSQL + Nginx):
docker compose --profile postgres --profile prod up -d

# View logs:
docker compose logs -f api
```

---

## 📊 Backtesting

```python
import pandas as pd
from backtest.engine import BacktestEngine, BacktestConfig, WalkForwardAnalyzer, MonteCarloSimulator

# Load your OHLCV data
df = pd.read_csv("backtest/data/EURUSD_H1.csv", parse_dates=["datetime"], index_col="datetime")

config = BacktestConfig(
    symbol="EURUSD",
    timeframe="H1",
    start_date="2020-01-01",
    end_date="2024-01-01",
    initial_balance=10_000,
    risk_pct=1.0,
    sl_atr_mult=1.5,
    tp_atr_mult=3.0,
    min_confidence=85.0,
)

# Run backtest
engine = BacktestEngine(config)
result = engine.run(df)
print(result.metrics["summary"])

# Walk-Forward Analysis
wf = WalkForwardAnalyzer(n_windows=5, oos_ratio=0.3)
wf_result = wf.run(df, config, param_grid={
    "sl_atr_mult": [1.2, 1.5, 1.8],
    "tp_atr_mult": [2.5, 3.0, 3.5],
    "min_confidence": [80.0, 85.0, 90.0],
})
print(f"WF Efficiency: {wf_result['wf_efficiency']}")

# Monte Carlo Simulation
mc = MonteCarloSimulator()
mc_result = mc.simulate(result.trades, 10_000, n_simulations=1000)
print(f"Ruin Probability: {mc_result['ruin_probability']}%")
```

---

## 📈 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET  | `/health` | Health check |
| POST | `/api/v1/signals/generate` | Generate AI signal |
| GET  | `/api/v1/signals/history` | Signal history |
| POST | `/api/v1/risk/check` | Risk pre-trade check |
| GET  | `/api/v1/analytics/performance` | Full performance report |
| POST | `/api/v1/analytics/trades` | Record new trade |
| PUT  | `/api/v1/analytics/trades/{ticket}/close` | Close trade |
| POST | `/api/v1/backtest/run` | Run backtest |
| POST | `/api/v1/backtest/walkforward` | Walk-forward analysis |
| POST | `/api/v1/backtest/montecarlo` | Monte Carlo simulation |

Full interactive docs: `http://localhost:8000/docs`

---

## 🤖 Telegram Commands

| Command | Description |
|---------|-------------|
| `/status` | Full system status + account |
| `/start` | Enable trading |
| `/stop` | Pause trading (keeps open positions) |
| `/profit` | Profit summary (daily/weekly/monthly/all-time) |
| `/loss` | Loss & drawdown summary |
| `/opentrades` | List all open positions |
| `/performance` | Full analytics report |
| `/help` | Show all commands |

---

## ⚙️ Risk Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `MAX_RISK_PER_TRADE` | 1.0% | Maximum account risk per trade |
| `MAX_DAILY_LOSS_PCT` | 3.0% | Daily loss circuit breaker |
| `MAX_WEEKLY_LOSS_PCT` | 8.0% | Weekly loss circuit breaker |
| `MAX_OPEN_TRADES` | 3 | Max simultaneous positions |
| `MAX_CONSECUTIVE_LOSSES` | 3 | Losses before circuit breaker |
| `MIN_CONFIDENCE` | 85% | Minimum AI signal confidence |

---

## 🔒 Security Checklist

- [ ] Change `SECRET_KEY` in `.env` (64 random chars minimum)
- [ ] Never commit `.env` to git (it's in `.gitignore`)
- [ ] Use strong `MT5_PASSWORD`
- [ ] Set `TELEGRAM_ADMIN_IDS` to your Telegram user ID only
- [ ] Use PostgreSQL in production (not SQLite)
- [ ] Enable Nginx with SSL in production
- [ ] Run containers as non-root user (already configured in Dockerfile)
- [ ] Rotate API keys periodically
- [ ] Enable firewall: only expose port 80/443 externally

---

## 🔬 AI Upgrade Roadmap

### Phase 1 — Current (v2.0)
- Multi-factor scoring (Trend + Momentum + Volume + Liquidity + Volatility)
- Smart Money Concepts (BOS, CHoCH, OB, FVG)
- Deterministic rule-based confidence scoring

### Phase 2 — ML Integration (v2.5)
- [ ] Train LSTM/GRU on historical signals + outcomes
- [ ] Feature engineering pipeline (100+ features)
- [ ] Ensemble: XGBoost + Neural Net + Rule-based
- [ ] Online learning (model updates every week)

### Phase 3 — Reinforcement Learning (v3.0)
- [ ] PPO/SAC agent for trade management (BE, trail, partial)
- [ ] Multi-agent system (one agent per symbol)
- [ ] Reward function: risk-adjusted returns (Sortino)

### Phase 4 — Advanced (v3.5)
- [ ] NLP news sentiment analysis (real-time)
- [ ] Orderbook microstructure features (L2 data)
- [ ] Cross-asset correlation ML model
- [ ] Regime-adaptive strategy selection

---

## 📝 License

Proprietary — For personal trading use only.
Not financial advice. Trade at your own risk.
