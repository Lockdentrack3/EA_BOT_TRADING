"""
Risk Management Engine
Institutional-grade risk controls: position sizing, drawdown limits,
circuit breakers, correlation checks, and portfolio-level risk.
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional
from datetime import datetime, date
from enum import Enum

logger = logging.getLogger("risk_manager")


class RiskStatus(str, Enum):
    ALLOWED      = "ALLOWED"
    DAILY_LIMIT  = "DAILY_LIMIT_HIT"
    WEEKLY_LIMIT = "WEEKLY_LIMIT_HIT"
    MAX_TRADES   = "MAX_TRADES_REACHED"
    CORRELATION  = "CORRELATED_LIMIT"
    CIRCUIT_BREAK = "CIRCUIT_BREAKER"
    NEWS_BLOCK   = "NEWS_FILTER"
    INSUFFICIENT = "INSUFFICIENT_MARGIN"


@dataclass
class RiskCheckResult:
    allowed: bool
    status: RiskStatus
    reason: str
    max_lots: float = 0.0
    risk_amount: float = 0.0


@dataclass
class AccountSnapshot:
    balance: float
    equity: float
    margin_free: float
    open_pnl: float
    daily_pnl: float
    weekly_pnl: float
    timestamp: datetime


class PositionSizer:
    """
    Dynamic position sizing using fixed fractional risk model.
    Risk Amount = Balance × Risk%
    Lots = Risk Amount / (SL pips × Pip Value)
    """

    SYMBOL_SPECS = {
        "EURUSD": {"pip_value_per_lot": 10.0,  "pip_size": 0.0001},
        "GBPUSD": {"pip_value_per_lot": 10.0,  "pip_size": 0.0001},
        "USDJPY": {"pip_value_per_lot": 6.80,  "pip_size": 0.01},
        "XAUUSD": {"pip_value_per_lot": 100.0, "pip_size": 0.1},
        "BTCUSD": {"pip_value_per_lot": 1.0,   "pip_size": 1.0},
        "US30":   {"pip_value_per_lot": 1.0,   "pip_size": 1.0},
        "NAS100": {"pip_value_per_lot": 1.0,   "pip_size": 0.25},
    }

    DEFAULT_SPEC = {"pip_value_per_lot": 10.0, "pip_size": 0.0001}
    MIN_LOT      = 0.01
    MAX_LOT      = 100.0
    LOT_STEP     = 0.01

    def calculate_lots(
        self,
        balance: float,
        risk_pct: float,
        symbol: str,
        sl_distance: float,       # in price units (e.g. 0.00150 for EURUSD)
    ) -> float:
        if balance <= 0 or sl_distance <= 0:
            return 0.0

        spec     = self.SYMBOL_SPECS.get(symbol, self.DEFAULT_SPEC)
        pip_val  = spec["pip_value_per_lot"]
        pip_size = spec["pip_size"]

        risk_amount = balance * (risk_pct / 100.0)
        sl_pips     = sl_distance / pip_size
        if sl_pips <= 0:
            return 0.0

        lots = risk_amount / (sl_pips * pip_val)

        # Normalize to lot step
        lots = round(int(lots / self.LOT_STEP) * self.LOT_STEP, 2)
        lots = max(self.MIN_LOT, min(self.MAX_LOT, lots))

        return lots


class CorrelationMatrix:
    """Track correlation between open positions to avoid over-exposure."""

    CORRELATED_GROUPS = [
        {"EURUSD", "GBPUSD", "AUDUSD", "NZDUSD"},   # USD-correlated majors
        {"USDJPY", "USDCHF", "USDCAD"},               # Inverse USD pairs
        {"XAUUSD", "XAGUSD"},                          # Precious metals
        {"BTCUSD", "ETHUSD"},                          # Crypto
        {"US30", "NAS100", "SPX500"},                  # US Indices
    ]

    def get_correlation_group(self, symbol: str) -> Optional[int]:
        for i, group in enumerate(self.CORRELATED_GROUPS):
            if symbol in group:
                return i
        return None

    def count_correlated(self, symbol: str, open_symbols: List[str]) -> int:
        group_id = self.get_correlation_group(symbol)
        if group_id is None:
            return 0
        group = self.CORRELATED_GROUPS[group_id]
        return sum(1 for s in open_symbols if s in group)


class RiskManager:
    """
    Central risk management hub. All trade decisions pass through here.
    """

    def __init__(
        self,
        risk_pct: float         = 1.0,
        max_daily_loss: float   = 3.0,
        max_weekly_loss: float  = 8.0,
        max_open_trades: int    = 3,
        max_correlated: int     = 2,
        max_consec_losses: int  = 3,
    ):
        self.risk_pct          = risk_pct
        self.max_daily_loss    = max_daily_loss
        self.max_weekly_loss   = max_weekly_loss
        self.max_open_trades   = max_open_trades
        self.max_correlated    = max_correlated
        self.max_consec_losses = max_consec_losses

        self.sizer         = PositionSizer()
        self.correlation   = CorrelationMatrix()

        # State
        self.circuit_breaker_active = False
        self.consecutive_losses     = 0
        self.daily_start_balance    = 0.0
        self.weekly_start_balance   = 0.0
        self.daily_reset_date       = date.today()
        self.weekly_reset_date      = date.today()
        self.trade_log: List[dict]  = []

    # ----------------------------------------------------------------
    # Primary check: can we open a new trade?
    # ----------------------------------------------------------------
    def check_trade_allowed(
        self,
        symbol: str,
        balance: float,
        equity: float,
        open_symbols: List[str],
        sl_distance: float,
    ) -> RiskCheckResult:

        self._reset_periodic_counters(balance)

        # Circuit breaker
        if self.circuit_breaker_active:
            return RiskCheckResult(
                allowed=False,
                status=RiskStatus.CIRCUIT_BREAK,
                reason=f"Circuit breaker after {self.consecutive_losses} consecutive losses",
            )

        # Daily loss
        if self.daily_start_balance > 0:
            daily_loss_pct = (self.daily_start_balance - equity) / self.daily_start_balance * 100
            if daily_loss_pct >= self.max_daily_loss:
                return RiskCheckResult(
                    allowed=False,
                    status=RiskStatus.DAILY_LIMIT,
                    reason=f"Daily loss {daily_loss_pct:.2f}% >= {self.max_daily_loss}%",
                )

        # Weekly loss
        if self.weekly_start_balance > 0:
            weekly_loss_pct = (self.weekly_start_balance - equity) / self.weekly_start_balance * 100
            if weekly_loss_pct >= self.max_weekly_loss:
                return RiskCheckResult(
                    allowed=False,
                    status=RiskStatus.WEEKLY_LIMIT,
                    reason=f"Weekly loss {weekly_loss_pct:.2f}% >= {self.max_weekly_loss}%",
                )

        # Max open trades
        if len(open_symbols) >= self.max_open_trades:
            return RiskCheckResult(
                allowed=False,
                status=RiskStatus.MAX_TRADES,
                reason=f"Max open trades {self.max_open_trades} reached",
            )

        # Correlation check
        correl_count = self.correlation.count_correlated(symbol, open_symbols)
        if correl_count >= self.max_correlated:
            return RiskCheckResult(
                allowed=False,
                status=RiskStatus.CORRELATION,
                reason=f"Correlated positions limit {self.max_correlated} reached for {symbol}",
            )

        # Calculate lot size
        lots = self.sizer.calculate_lots(balance, self.risk_pct, symbol, sl_distance)
        risk_amount = balance * (self.risk_pct / 100.0)

        return RiskCheckResult(
            allowed=True,
            status=RiskStatus.ALLOWED,
            reason="All risk checks passed",
            max_lots=lots,
            risk_amount=risk_amount,
        )

    # ----------------------------------------------------------------
    # Record trade outcome
    # ----------------------------------------------------------------
    def record_trade_result(self, profit: float, symbol: str):
        self.trade_log.append({
            "profit": profit,
            "symbol": symbol,
            "timestamp": datetime.utcnow(),
        })

        if profit < 0:
            self.consecutive_losses += 1
            logger.warning(f"Consecutive losses: {self.consecutive_losses}")
            if self.consecutive_losses >= self.max_consec_losses:
                self.circuit_breaker_active = True
                logger.error(
                    f"CIRCUIT BREAKER ACTIVATED after {self.consecutive_losses} "
                    "consecutive losses"
                )
        else:
            self.consecutive_losses = 0

    def reset_circuit_breaker(self):
        self.circuit_breaker_active = False
        self.consecutive_losses     = 0
        logger.info("Circuit breaker reset manually")

    # ----------------------------------------------------------------
    # Portfolio metrics
    # ----------------------------------------------------------------
    def get_portfolio_stats(self) -> dict:
        if not self.trade_log:
            return {}

        profits = [t["profit"] for t in self.trade_log]
        wins    = [p for p in profits if p > 0]
        losses  = [p for p in profits if p < 0]

        total_profit = sum(profits)
        win_rate     = len(wins) / len(profits) * 100 if profits else 0
        profit_factor = (sum(wins) / abs(sum(losses))) if losses else float("inf")

        # Sharpe ratio approximation
        if len(profits) > 1:
            import numpy as np
            arr = np.array(profits)
            sharpe = (arr.mean() / arr.std() * (252 ** 0.5)) if arr.std() > 0 else 0
        else:
            sharpe = 0

        # Max drawdown
        max_dd = self._calc_max_drawdown(profits)

        return {
            "total_trades":   len(profits),
            "win_rate":       round(win_rate, 2),
            "profit_factor":  round(profit_factor, 2),
            "total_pnl":      round(total_profit, 2),
            "sharpe_ratio":   round(sharpe, 3),
            "max_drawdown":   round(max_dd, 2),
            "consec_losses":  self.consecutive_losses,
            "circuit_breaker": self.circuit_breaker_active,
        }

    def _calc_max_drawdown(self, profits: list) -> float:
        """Calculate maximum drawdown as percentage."""
        if not profits:
            return 0.0
        cumulative = [sum(profits[:i+1]) for i in range(len(profits))]
        peak = cumulative[0]
        max_dd = 0.0
        for val in cumulative:
            if val > peak:
                peak = val
            dd = (peak - val) / abs(peak) * 100 if peak != 0 else 0
            max_dd = max(max_dd, dd)
        return max_dd

    def _reset_periodic_counters(self, current_balance: float):
        today = date.today()

        # Daily reset
        if today != self.daily_reset_date:
            self.daily_start_balance = current_balance
            self.daily_reset_date    = today
            logger.info(f"Daily balance snapshot: {current_balance:.2f}")

        # Weekly reset (Monday = 0)
        if today.weekday() == 0 and today != self.weekly_reset_date:
            self.weekly_start_balance = current_balance
            self.weekly_reset_date    = today
            logger.info(f"Weekly balance snapshot: {current_balance:.2f}")

        # Initialize on first call
        if self.daily_start_balance == 0:
            self.daily_start_balance = current_balance
        if self.weekly_start_balance == 0:
            self.weekly_start_balance = current_balance
