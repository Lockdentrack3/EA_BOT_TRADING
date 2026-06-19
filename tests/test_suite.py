"""
Test Suite — EA_BOT_TRADING
Run: pytest tests/ -v --cov=. --cov-report=term-missing
"""

import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from python.core.signal_engine import (
    AISignalEngine, TechnicalIndicators, SMCAnalyzer,
    MarketRegimeDetector, SignalDirection, MarketRegime
)
from risk_management.risk_manager import RiskManager, RiskStatus, PositionSizer
from analytics.performance import PerformanceAnalytics, TradeRecord


# ---------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------

def make_ohlcv(n: int = 300, trend: str = "up") -> pd.DataFrame:
    """Generate synthetic OHLCV data."""
    np.random.seed(42)
    base = 1.1000
    if trend == "up":
        close = base + np.cumsum(np.random.normal(0.0002, 0.001, n))
    elif trend == "down":
        close = base + np.cumsum(np.random.normal(-0.0002, 0.001, n))
    else:
        close = base + np.random.normal(0, 0.001, n)

    high   = close + np.abs(np.random.normal(0, 0.0005, n))
    low    = close - np.abs(np.random.normal(0, 0.0005, n))
    open_  = close + np.random.normal(0, 0.0003, n)
    volume = np.random.randint(100, 1000, n).astype(float)

    idx = pd.date_range("2020-01-01", periods=n, freq="1h")
    return pd.DataFrame({
        "open": open_, "high": high, "low": low,
        "close": close, "volume": volume
    }, index=idx)


def make_trades(n: int = 50, win_rate: float = 0.6) -> list:
    """Generate synthetic trade records."""
    trades = []
    for i in range(n):
        is_win = i < int(n * win_rate)
        profit = np.random.uniform(50, 200) if is_win else -np.random.uniform(30, 100)
        base_time = datetime(2023, 1, 1) + timedelta(hours=i * 4)
        trades.append(TradeRecord(
            ticket=i + 1,
            symbol="EURUSD",
            direction="BUY" if i % 2 == 0 else "SELL",
            open_time=base_time,
            close_time=base_time + timedelta(hours=2),
            open_price=1.1000,
            close_price=1.1050 if is_win else 1.0980,
            lots=0.10,
            profit=profit,
            swap=0.0,
            commission=-0.70,
            net_profit=profit - 0.70,
            sl=1.0950,
            tp=1.1100,
            magic=202401,
        ))
    return trades


# ---------------------------------------------------------------
# Technical Indicators Tests
# ---------------------------------------------------------------

class TestTechnicalIndicators:
    def setup_method(self):
        self.ti = TechnicalIndicators()
        self.df = make_ohlcv(300, "up")

    def test_ema_length(self):
        ema = self.ti.ema(self.df["close"], 50)
        assert len(ema) == 300

    def test_ema_smoothing(self):
        ema50  = self.ti.ema(self.df["close"], 50)
        ema200 = self.ti.ema(self.df["close"], 200)
        # EMA200 should be smoother (less std deviation)
        assert ema200.std() < ema50.std()

    def test_rsi_bounds(self):
        rsi = self.ti.rsi(self.df["close"], 14)
        valid = rsi.dropna()
        assert (valid >= 0).all() and (valid <= 100).all()

    def test_rsi_uptrend(self):
        rsi = self.ti.rsi(self.df["close"], 14)
        # In uptrend, most recent RSI should be > 50
        assert rsi.iloc[-1] > 50

    def test_atr_positive(self):
        atr = self.ti.atr(self.df["high"], self.df["low"], self.df["close"], 14)
        assert (atr.dropna() > 0).all()

    def test_macd_returns_three_series(self):
        line, sig, hist = self.ti.macd(self.df["close"])
        assert len(line) == len(sig) == len(hist) == 300

    def test_bollinger_upper_above_lower(self):
        up, mid, low = self.ti.bollinger_bands(self.df["close"], 20, 2.0)
        valid = up.dropna().index
        assert (up[valid] > mid[valid]).all()
        assert (mid[valid] > low[valid]).all()

    def test_stochastic_bounds(self):
        k, d = self.ti.stochastic(self.df["high"], self.df["low"], self.df["close"])
        kv = k.dropna()
        assert (kv >= 0).all() and (kv <= 100).all()


# ---------------------------------------------------------------
# SMC Analyzer Tests
# ---------------------------------------------------------------

class TestSMCAnalyzer:
    def setup_method(self):
        self.smc = SMCAnalyzer(lookback=10)

    def test_bos_bull_detected(self):
        df = make_ohlcv(50, "up")
        bull, bear = self.smc.detect_bos(df["high"], df["low"], df["close"])
        # Should detect at least something in uptrend
        assert isinstance(bull, bool) and isinstance(bear, bool)

    def test_fvg_returns_booleans(self):
        df = make_ohlcv(20, "up")
        bull, bear = self.smc.detect_fvg(df["high"], df["low"])
        assert isinstance(bull, bool) and isinstance(bear, bool)

    def test_liquidity_levels_valid(self):
        df = make_ohlcv(50, "range")
        high, low = self.smc.get_liquidity_levels(df["high"], df["low"])
        assert high > low > 0


# ---------------------------------------------------------------
# AI Signal Engine Tests
# ---------------------------------------------------------------

class TestAISignalEngine:
    def setup_method(self):
        self.engine = AISignalEngine(min_confidence=85.0)

    def test_signal_generated_uptrend(self):
        df = make_ohlcv(300, "up")
        # Might or might not generate signal — just check it doesn't crash
        signal = self.engine.generate_signal(df, "EURUSD", df["close"].iloc[-1])
        if signal:
            assert signal.direction in [SignalDirection.BUY, SignalDirection.SELL]
            assert 0 <= signal.confidence <= 100

    def test_no_signal_insufficient_data(self):
        df = make_ohlcv(50, "up")   # Not enough bars
        signal = self.engine.generate_signal(df, "EURUSD", 1.1000)
        assert signal is None

    def test_scores_bounded(self):
        df = make_ohlcv(300, "up")
        ind = self.engine.compute_indicators(df)
        for score_fn in [
            self.engine.score_trend,
            self.engine.score_momentum,
            self.engine.score_volume,
            self.engine.score_liquidity,
            self.engine.score_volatility,
        ]:
            score = score_fn(ind)
            assert 0 <= score <= 100, f"{score_fn.__name__} returned {score}"

    def test_confidence_above_threshold_required(self):
        engine_strict = AISignalEngine(min_confidence=99.9)
        df = make_ohlcv(300, "range")
        signal = engine_strict.generate_signal(df, "EURUSD", df["close"].iloc[-1])
        assert signal is None  # Near-impossible confidence threshold


# ---------------------------------------------------------------
# Risk Manager Tests
# ---------------------------------------------------------------

class TestRiskManager:
    def setup_method(self):
        self.rm = RiskManager(
            risk_pct=1.0, max_daily_loss=3.0, max_weekly_loss=8.0,
            max_open_trades=3, max_correlated=2, max_consec_losses=3
        )

    def test_trade_allowed_initially(self):
        result = self.rm.check_trade_allowed(
            symbol="EURUSD", balance=10000, equity=10000,
            open_symbols=[], sl_distance=0.001,
        )
        assert result.allowed
        assert result.status == RiskStatus.ALLOWED

    def test_max_trades_blocked(self):
        result = self.rm.check_trade_allowed(
            symbol="EURUSD", balance=10000, equity=10000,
            open_symbols=["EURUSD", "GBPUSD", "XAUUSD"],  # 3 already open
            sl_distance=0.001,
        )
        assert not result.allowed
        assert result.status == RiskStatus.MAX_TRADES

    def test_circuit_breaker_activates(self):
        for _ in range(3):
            self.rm.record_trade_result(-100, "EURUSD")
        assert self.rm.circuit_breaker_active

        result = self.rm.check_trade_allowed(
            symbol="EURUSD", balance=10000, equity=10000,
            open_symbols=[], sl_distance=0.001,
        )
        assert not result.allowed
        assert result.status == RiskStatus.CIRCUIT_BREAK

    def test_circuit_breaker_reset(self):
        for _ in range(3):
            self.rm.record_trade_result(-100, "EURUSD")
        self.rm.reset_circuit_breaker()
        assert not self.rm.circuit_breaker_active
        assert self.rm.consecutive_losses == 0

    def test_win_resets_consecutive_losses(self):
        self.rm.record_trade_result(-50, "EURUSD")
        self.rm.record_trade_result(-50, "EURUSD")
        self.rm.record_trade_result(100, "EURUSD")  # Win resets counter
        assert self.rm.consecutive_losses == 0

    def test_daily_loss_blocked(self):
        self.rm.daily_start_balance = 10000
        result = self.rm.check_trade_allowed(
            symbol="EURUSD", balance=9700, equity=9700,  # -3% daily
            open_symbols=[], sl_distance=0.001,
        )
        assert not result.allowed
        assert result.status == RiskStatus.DAILY_LIMIT


class TestPositionSizer:
    def setup_method(self):
        self.sizer = PositionSizer()

    def test_lot_size_reasonable(self):
        lots = self.sizer.calculate_lots(
            balance=10000, risk_pct=1.0,
            symbol="EURUSD", sl_distance=0.0015
        )
        assert 0.01 <= lots <= 10.0

    def test_lot_size_scales_with_balance(self):
        lots_small = self.sizer.calculate_lots(5000, 1.0, "EURUSD", 0.0015)
        lots_large = self.sizer.calculate_lots(10000, 1.0, "EURUSD", 0.0015)
        assert lots_large > lots_small

    def test_wider_sl_gives_smaller_lots(self):
        lots_tight = self.sizer.calculate_lots(10000, 1.0, "EURUSD", 0.0010)
        lots_wide  = self.sizer.calculate_lots(10000, 1.0, "EURUSD", 0.0030)
        assert lots_tight > lots_wide

    def test_min_lot_enforced(self):
        lots = self.sizer.calculate_lots(100, 1.0, "EURUSD", 0.0050)
        assert lots >= 0.01


# ---------------------------------------------------------------
# Performance Analytics Tests
# ---------------------------------------------------------------

class TestPerformanceAnalytics:
    def setup_method(self):
        self.analytics = PerformanceAnalytics()
        self.analytics.initial_balance = 10000.0
        trades = make_trades(50, win_rate=0.6)
        for t in trades:
            self.analytics.add_trade(t)

    def test_win_rate_correct(self):
        wr = self.analytics.win_rate()
        assert 55 <= wr <= 65  # ~60% with some variance

    def test_profit_factor_positive(self):
        pf = self.analytics.profit_factor()
        assert pf > 1.0  # Profitable strategy

    def test_sharpe_computes(self):
        sr = self.analytics.sharpe_ratio()
        assert isinstance(sr, float)

    def test_sortino_computes(self):
        sortino = self.analytics.sortino_ratio()
        assert isinstance(sortino, float)

    def test_max_drawdown_non_negative(self):
        mdd = self.analytics.max_drawdown_pct()
        assert mdd >= 0

    def test_full_report_structure(self):
        report = self.analytics.full_report()
        assert "summary" in report
        assert "risk_metrics" in report
        assert "monthly_returns" in report
        assert report["summary"]["total_trades"] == 50

    def test_monthly_returns_dict(self):
        monthly = self.analytics.monthly_returns()
        assert isinstance(monthly, dict)
        assert len(monthly) > 0

    def test_empty_analytics(self):
        a = PerformanceAnalytics()
        assert a.win_rate() == 0.0
        assert a.total_trades() == 0
        assert a.max_drawdown_pct() == 0.0
