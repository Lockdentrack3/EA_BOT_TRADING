"""
FastAPI Route Handlers
All REST endpoints for the trading system.
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from datetime import datetime
import logging

from python.core.database import get_db, Trade, Signal, AccountSnapshot, DailyStats
from python.core.signal_engine import AISignalEngine
from risk_management.risk_manager import RiskManager
from analytics.performance import PerformanceAnalytics, TradeRecord
from backtest.engine import BacktestEngine, BacktestConfig, WalkForwardAnalyzer, MonteCarloSimulator

logger = logging.getLogger("routes")

# ---------------------------------------------------------------
# Shared instances
# ---------------------------------------------------------------
signal_engine = AISignalEngine(min_confidence=85.0)
risk_manager  = RiskManager()

# ---------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------

class SignalRequest(BaseModel):
    symbol: str
    ohlcv: List[Dict]           # list of {open,high,low,close,volume}
    current_price: float
    sl_atr_mult: float = 1.5
    tp_atr_mult: float = 3.0

class TradeCreateRequest(BaseModel):
    ticket: int
    symbol: str
    direction: str
    open_time: datetime
    open_price: float
    lots: float
    sl: float
    tp: float
    magic: int
    confidence: float = 0.0
    regime: str = ""
    comment: str = ""

class TradeCloseRequest(BaseModel):
    ticket: int
    close_time: datetime
    close_price: float
    profit: float
    swap: float = 0.0
    commission: float = 0.0

class RiskCheckRequest(BaseModel):
    symbol: str
    balance: float
    equity: float
    open_symbols: List[str] = []
    sl_distance: float

class AccountUpdateRequest(BaseModel):
    balance: float
    equity: float
    margin_used: float = 0.0
    margin_free: float = 0.0
    open_pnl: float = 0.0
    daily_pnl: float = 0.0
    open_trades: int = 0

class BacktestRequest(BaseModel):
    symbol: str
    timeframe: str = "H1"
    start_date: str
    end_date: str
    initial_balance: float = 10000.0
    risk_pct: float = 1.0
    sl_atr_mult: float = 1.5
    tp_atr_mult: float = 3.0
    min_confidence: float = 85.0
    ohlcv: List[Dict]

class WalkForwardRequest(BacktestRequest):
    n_windows: int = 5
    oos_ratio: float = 0.3
    param_grid: Dict = Field(default_factory=dict)

class MonteCarloRequest(BaseModel):
    ticket_ids: Optional[List[int]] = None   # None = use all closed trades
    initial_balance: float = 10000.0
    n_simulations: int = 1000

# ---------------------------------------------------------------
# Signals Router
# ---------------------------------------------------------------

signals_router = APIRouter()

@signals_router.post("/generate")
async def generate_signal(req: SignalRequest, db: AsyncSession = Depends(get_db)):
    """Generate AI trade signal from OHLCV data."""
    try:
        import pandas as pd
        df = pd.DataFrame(req.ohlcv)
        required = {"open", "high", "low", "close", "volume"}
        if not required.issubset(df.columns):
            raise HTTPException(400, f"Missing columns. Required: {required}")

        signal = signal_engine.generate_signal(
            df, req.symbol, req.current_price,
            req.sl_atr_mult, req.tp_atr_mult
        )

        if signal is None:
            return {"signal": None, "message": "No signal — confidence below threshold"}

        # Persist to DB
        db_sig = Signal(
            symbol=signal.symbol,
            direction=signal.direction.value,
            confidence=signal.confidence,
            trend_score=signal.trend_score,
            momentum_score=signal.momentum_score,
            volume_score=signal.volume_score,
            liquidity_score=signal.liquidity_score,
            volatility_score=signal.volatility_score,
            regime=signal.regime.value,
            atr=signal.atr,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            risk_reward=signal.risk_reward,
        )
        db.add(db_sig)
        await db.commit()
        await db.refresh(db_sig)

        return {
            "signal": {
                "id":               db_sig.id,
                "symbol":           signal.symbol,
                "direction":        signal.direction.value,
                "confidence":       signal.confidence,
                "trend_score":      signal.trend_score,
                "momentum_score":   signal.momentum_score,
                "volume_score":     signal.volume_score,
                "liquidity_score":  signal.liquidity_score,
                "volatility_score": signal.volatility_score,
                "regime":           signal.regime.value,
                "entry_price":      signal.entry_price,
                "stop_loss":        signal.stop_loss,
                "take_profit":      signal.take_profit,
                "risk_reward":      signal.risk_reward,
                "description":      signal.description,
                "timestamp":        signal.timestamp.isoformat(),
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Signal generation error")
        raise HTTPException(500, f"Signal error: {str(e)}")


@signals_router.get("/history")
async def signal_history(limit: int = 50, symbol: Optional[str] = None,
                          db: AsyncSession = Depends(get_db)):
    q = select(Signal).order_by(desc(Signal.timestamp)).limit(limit)
    if symbol:
        q = q.where(Signal.symbol == symbol)
    result = await db.execute(q)
    signals = result.scalars().all()
    return {"signals": [s.to_dict() for s in signals]}


# ---------------------------------------------------------------
# Risk Router
# ---------------------------------------------------------------

risk_router = APIRouter()

@risk_router.post("/check")
async def check_risk(req: RiskCheckRequest):
    """Check if a new trade is allowed under current risk rules."""
    result = risk_manager.check_trade_allowed(
        symbol=req.symbol,
        balance=req.balance,
        equity=req.equity,
        open_symbols=req.open_symbols,
        sl_distance=req.sl_distance,
    )
    return {
        "allowed":     result.allowed,
        "status":      result.status.value,
        "reason":      result.reason,
        "max_lots":    result.max_lots,
        "risk_amount": result.risk_amount,
    }

@risk_router.post("/record_trade")
async def record_trade_result(profit: float, symbol: str):
    risk_manager.record_trade_result(profit, symbol)
    return {"recorded": True, "circuit_breaker": risk_manager.circuit_breaker_active}

@risk_router.post("/reset_circuit_breaker")
async def reset_circuit_breaker():
    risk_manager.reset_circuit_breaker()
    return {"message": "Circuit breaker reset"}

@risk_router.get("/portfolio_stats")
async def get_portfolio_stats():
    return risk_manager.get_portfolio_stats()


# ---------------------------------------------------------------
# Analytics Router
# ---------------------------------------------------------------

analytics_router = APIRouter()

@analytics_router.get("/performance")
async def get_performance(db: AsyncSession = Depends(get_db)):
    """Compute full performance metrics from all closed trades."""
    q = select(Trade).where(Trade.status == "CLOSED")
    result = await db.execute(q)
    trades = result.scalars().all()

    analytics = PerformanceAnalytics()
    for t in trades:
        analytics.add_trade(TradeRecord(
            ticket=t.ticket, symbol=t.symbol, direction=t.direction,
            open_time=t.open_time, close_time=t.close_time or datetime.utcnow(),
            open_price=t.open_price, close_price=t.close_price or t.open_price,
            lots=t.lots, profit=t.profit, swap=t.swap, commission=t.commission,
            net_profit=t.net_profit, sl=t.sl or 0.0, tp=t.tp or 0.0,
            magic=t.magic, comment=t.comment,
        ))

    return analytics.full_report()

@analytics_router.post("/account_snapshot")
async def save_account_snapshot(req: AccountUpdateRequest,
                                  db: AsyncSession = Depends(get_db)):
    snap = AccountSnapshot(
        balance=req.balance,
        equity=req.equity,
        margin_used=req.margin_used,
        margin_free=req.margin_free,
        open_pnl=req.open_pnl,
        daily_pnl=req.daily_pnl,
        open_trades=req.open_trades,
    )
    db.add(snap)
    await db.commit()
    return {"saved": True}

@analytics_router.post("/trades")
async def create_trade(req: TradeCreateRequest, db: AsyncSession = Depends(get_db)):
    """Record a new opened trade."""
    trade = Trade(
        ticket=req.ticket, symbol=req.symbol, direction=req.direction,
        open_time=req.open_time, open_price=req.open_price, lots=req.lots,
        sl=req.sl, tp=req.tp, magic=req.magic, confidence=req.confidence,
        regime=req.regime, comment=req.comment, status="OPEN",
    )
    db.add(trade)
    await db.commit()
    await db.refresh(trade)
    return {"trade_id": trade.id}

@analytics_router.put("/trades/{ticket}/close")
async def close_trade(ticket: int, req: TradeCloseRequest,
                       db: AsyncSession = Depends(get_db)):
    q = select(Trade).where(Trade.ticket == ticket)
    result = await db.execute(q)
    trade = result.scalar_one_or_none()
    if not trade:
        raise HTTPException(404, f"Trade {ticket} not found")

    trade.close_time  = req.close_time
    trade.close_price = req.close_price
    trade.profit      = req.profit
    trade.swap        = req.swap
    trade.commission  = req.commission
    trade.net_profit  = req.profit + req.swap + req.commission
    trade.status      = "CLOSED"
    trade.updated_at  = datetime.utcnow()

    await db.commit()
    risk_manager.record_trade_result(trade.net_profit, trade.symbol)
    return {"closed": True, "net_profit": trade.net_profit}


# ---------------------------------------------------------------
# Backtest Router
# ---------------------------------------------------------------

backtest_router = APIRouter()

@backtest_router.post("/run")
async def run_backtest(req: BacktestRequest):
    """Run a full backtest on supplied OHLCV data."""
    try:
        import pandas as pd
        df = pd.DataFrame(req.ohlcv)

        config = BacktestConfig(
            symbol=req.symbol,
            timeframe=req.timeframe,
            start_date=req.start_date,
            end_date=req.end_date,
            initial_balance=req.initial_balance,
            risk_pct=req.risk_pct,
            sl_atr_mult=req.sl_atr_mult,
            tp_atr_mult=req.tp_atr_mult,
            min_confidence=req.min_confidence,
        )

        engine = BacktestEngine(config)
        result = engine.run(df)

        return {
            "symbol":        req.symbol,
            "total_trades":  len(result.trades),
            "metrics":       result.metrics,
            "equity_curve":  result.equity_curve[-100:],  # Last 100 points
        }
    except Exception as e:
        logger.exception("Backtest error")
        raise HTTPException(500, str(e))


@backtest_router.post("/walkforward")
async def run_walkforward(req: WalkForwardRequest):
    """Run walk-forward analysis."""
    try:
        import pandas as pd
        df     = pd.DataFrame(req.ohlcv)
        config = BacktestConfig(
            symbol=req.symbol, timeframe=req.timeframe,
            start_date=req.start_date, end_date=req.end_date,
            initial_balance=req.initial_balance, risk_pct=req.risk_pct,
        )
        wf = WalkForwardAnalyzer(n_windows=req.n_windows, oos_ratio=req.oos_ratio)
        return wf.run(df, config, req.param_grid or {})
    except Exception as e:
        logger.exception("Walk-forward error")
        raise HTTPException(500, str(e))


@backtest_router.post("/montecarlo")
async def run_montecarlo(req: MonteCarloRequest, db: AsyncSession = Depends(get_db)):
    """Run Monte Carlo simulation on historical trades."""
    q = select(Trade).where(Trade.status == "CLOSED")
    result = await db.execute(q)
    db_trades = result.scalars().all()

    analytics = PerformanceAnalytics()
    analytics.initial_balance = req.initial_balance
    for t in db_trades:
        analytics.add_trade(TradeRecord(
            ticket=t.ticket, symbol=t.symbol, direction=t.direction,
            open_time=t.open_time, close_time=t.close_time or datetime.utcnow(),
            open_price=t.open_price, close_price=t.close_price or t.open_price,
            lots=t.lots, profit=t.profit, swap=t.swap, commission=t.commission,
            net_profit=t.net_profit, sl=t.sl or 0, tp=t.tp or 0,
            magic=t.magic, comment=t.comment,
        ))

    mc = MonteCarloSimulator()
    return mc.simulate(analytics.trades, req.initial_balance, req.n_simulations)


# ---------------------------------------------------------------
# Telegram Router
# ---------------------------------------------------------------

telegram_router = APIRouter()

@telegram_router.get("/status")
async def telegram_status():
    return {"bot": "configured", "timestamp": datetime.utcnow().isoformat()}
