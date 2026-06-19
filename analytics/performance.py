"""
Performance Analytics Engine
Tracks: Win Rate, Profit Factor, Sharpe, Sortino, Max Drawdown,
Monthly Returns, and auto-generates reports.
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import List, Dict, Optional
from datetime import datetime, date
import logging
import json
import os

logger = logging.getLogger("analytics")


@dataclass
class TradeRecord:
    ticket: int
    symbol: str
    direction: str          # BUY / SELL
    open_time: datetime
    close_time: datetime
    open_price: float
    close_price: float
    lots: float
    profit: float
    swap: float
    commission: float
    net_profit: float
    sl: float
    tp: float
    magic: int
    comment: str = ""


class PerformanceAnalytics:
    """
    Institutional-grade performance analytics.
    All metrics computed from a list of TradeRecord objects.
    """

    RISK_FREE_RATE = 0.05   # Annual risk-free rate (5%)
    TRADING_DAYS   = 252

    def __init__(self):
        self.trades: List[TradeRecord] = []
        self.initial_balance: float    = 0.0

    def add_trade(self, trade: TradeRecord):
        self.trades.append(trade)

    def load_from_df(self, df: pd.DataFrame):
        """Load trades from a pandas DataFrame."""
        for _, row in df.iterrows():
            t = TradeRecord(
                ticket=int(row.get("ticket", 0)),
                symbol=str(row.get("symbol", "")),
                direction=str(row.get("direction", "")),
                open_time=pd.to_datetime(row.get("open_time")),
                close_time=pd.to_datetime(row.get("close_time")),
                open_price=float(row.get("open_price", 0)),
                close_price=float(row.get("close_price", 0)),
                lots=float(row.get("lots", 0)),
                profit=float(row.get("profit", 0)),
                swap=float(row.get("swap", 0)),
                commission=float(row.get("commission", 0)),
                net_profit=float(row.get("net_profit", row.get("profit", 0))),
                sl=float(row.get("sl", 0)),
                tp=float(row.get("tp", 0)),
                magic=int(row.get("magic", 0)),
                comment=str(row.get("comment", "")),
            )
            self.trades.append(t)

    # ------------------------------------------------------------------
    # Core Metrics
    # ------------------------------------------------------------------

    def total_trades(self) -> int:
        return len(self.trades)

    def winning_trades(self) -> List[TradeRecord]:
        return [t for t in self.trades if t.net_profit > 0]

    def losing_trades(self) -> List[TradeRecord]:
        return [t for t in self.trades if t.net_profit < 0]

    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        return len(self.winning_trades()) / len(self.trades) * 100

    def profit_factor(self) -> float:
        gross_profit = sum(t.net_profit for t in self.winning_trades())
        gross_loss   = abs(sum(t.net_profit for t in self.losing_trades()))
        if gross_loss == 0:
            return float("inf")
        return round(gross_profit / gross_loss, 3)

    def total_net_profit(self) -> float:
        return sum(t.net_profit for t in self.trades)

    def average_win(self) -> float:
        wins = [t.net_profit for t in self.winning_trades()]
        return np.mean(wins) if wins else 0.0

    def average_loss(self) -> float:
        losses = [t.net_profit for t in self.losing_trades()]
        return np.mean(losses) if losses else 0.0

    def risk_reward_ratio(self) -> float:
        avg_win  = self.average_win()
        avg_loss = abs(self.average_loss())
        if avg_loss == 0:
            return 0.0
        return round(avg_win / avg_loss, 2)

    def expectancy(self) -> float:
        """Expected profit per trade."""
        wr = self.win_rate() / 100
        return round(wr * self.average_win() + (1 - wr) * self.average_loss(), 2)

    # ------------------------------------------------------------------
    # Risk-Adjusted Metrics
    # ------------------------------------------------------------------

    def _daily_returns(self) -> np.ndarray:
        """Build daily return series from trades."""
        if not self.trades:
            return np.array([])

        df = pd.DataFrame([
            {"date": t.close_time.date(), "pnl": t.net_profit}
            for t in self.trades
        ])
        daily = df.groupby("date")["pnl"].sum().reset_index()
        daily = daily.sort_values("date")
        return daily["pnl"].values

    def sharpe_ratio(self) -> float:
        returns = self._daily_returns()
        if len(returns) < 2:
            return 0.0
        daily_rf   = self.RISK_FREE_RATE / self.TRADING_DAYS
        excess     = returns - daily_rf
        std        = np.std(excess, ddof=1)
        if std == 0:
            return 0.0
        return round(np.mean(excess) / std * np.sqrt(self.TRADING_DAYS), 3)

    def sortino_ratio(self) -> float:
        """Sortino uses downside deviation only."""
        returns = self._daily_returns()
        if len(returns) < 2:
            return 0.0
        daily_rf    = self.RISK_FREE_RATE / self.TRADING_DAYS
        excess      = returns - daily_rf
        downside    = excess[excess < 0]
        if len(downside) == 0:
            return float("inf")
        downside_std = np.sqrt(np.mean(downside ** 2))
        if downside_std == 0:
            return 0.0
        return round(np.mean(excess) / downside_std * np.sqrt(self.TRADING_DAYS), 3)

    def calmar_ratio(self) -> float:
        """Calmar = Annualized Return / Max Drawdown."""
        returns  = self._daily_returns()
        max_dd   = self.max_drawdown_pct()
        if max_dd == 0 or self.initial_balance == 0:
            return 0.0
        annual_return = np.mean(returns) * self.TRADING_DAYS / self.initial_balance * 100
        return round(annual_return / max_dd, 3)

    # ------------------------------------------------------------------
    # Drawdown Analysis
    # ------------------------------------------------------------------

    def max_drawdown_pct(self) -> float:
        returns = self._daily_returns()
        if len(returns) == 0:
            return 0.0
        cumulative = np.cumsum(returns)
        peak       = np.maximum.accumulate(cumulative)
        drawdown   = peak - cumulative
        if self.initial_balance > 0:
            return round(float(np.max(drawdown) / self.initial_balance * 100), 2)
        return round(float(np.max(drawdown)), 2)

    def max_drawdown_duration(self) -> int:
        """Max drawdown duration in days."""
        returns = self._daily_returns()
        if len(returns) < 2:
            return 0
        cumulative = np.cumsum(returns)
        peak       = np.maximum.accumulate(cumulative)
        in_drawdown = cumulative < peak
        if not in_drawdown.any():
            return 0

        max_dur = 0
        current = 0
        for dd in in_drawdown:
            if dd:
                current += 1
                max_dur = max(max_dur, current)
            else:
                current = 0
        return max_dur

    # ------------------------------------------------------------------
    # Time-Based Analysis
    # ------------------------------------------------------------------

    def monthly_returns(self) -> Dict[str, float]:
        if not self.trades:
            return {}
        data = [{"month": t.close_time.strftime("%Y-%m"), "pnl": t.net_profit}
                for t in self.trades]
        df      = pd.DataFrame(data)
        monthly = df.groupby("month")["pnl"].sum().to_dict()
        return {k: round(v, 2) for k, v in sorted(monthly.items())}

    def performance_by_symbol(self) -> Dict[str, dict]:
        symbols = set(t.symbol for t in self.trades)
        result  = {}
        for sym in symbols:
            sym_trades = [t for t in self.trades if t.symbol == sym]
            wins  = [t for t in sym_trades if t.net_profit > 0]
            pnl   = sum(t.net_profit for t in sym_trades)
            result[sym] = {
                "trades":     len(sym_trades),
                "win_rate":   round(len(wins) / len(sym_trades) * 100, 1),
                "total_pnl":  round(pnl, 2),
                "avg_profit": round(pnl / len(sym_trades), 2),
            }
        return result

    def performance_by_hour(self) -> Dict[int, dict]:
        """Identify best/worst trading hours."""
        result = {}
        for t in self.trades:
            hour = t.open_time.hour
            if hour not in result:
                result[hour] = {"trades": 0, "pnl": 0.0, "wins": 0}
            result[hour]["trades"] += 1
            result[hour]["pnl"]    += t.net_profit
            if t.net_profit > 0:
                result[hour]["wins"] += 1

        for hour, data in result.items():
            data["win_rate"] = round(data["wins"] / data["trades"] * 100, 1)
            data["pnl"]      = round(data["pnl"], 2)
        return result

    def consecutive_stats(self) -> dict:
        """Max consecutive wins and losses."""
        max_wins = max_losses = 0
        cur_wins = cur_losses = 0
        for t in self.trades:
            if t.net_profit > 0:
                cur_wins  += 1
                cur_losses = 0
            else:
                cur_losses += 1
                cur_wins   = 0
            max_wins   = max(max_wins,   cur_wins)
            max_losses = max(max_losses, cur_losses)
        return {"max_consecutive_wins": max_wins, "max_consecutive_losses": max_losses}

    # ------------------------------------------------------------------
    # Full Report
    # ------------------------------------------------------------------

    def full_report(self) -> dict:
        monthly = self.monthly_returns()
        best_month  = max(monthly.values()) if monthly else 0
        worst_month = min(monthly.values()) if monthly else 0

        return {
            "summary": {
                "total_trades":     self.total_trades(),
                "winning_trades":   len(self.winning_trades()),
                "losing_trades":    len(self.losing_trades()),
                "win_rate":         round(self.win_rate(), 2),
                "profit_factor":    self.profit_factor(),
                "total_net_profit": round(self.total_net_profit(), 2),
                "average_win":      round(self.average_win(), 2),
                "average_loss":     round(self.average_loss(), 2),
                "risk_reward":      self.risk_reward_ratio(),
                "expectancy":       self.expectancy(),
            },
            "risk_metrics": {
                "sharpe_ratio":          self.sharpe_ratio(),
                "sortino_ratio":         self.sortino_ratio(),
                "calmar_ratio":          self.calmar_ratio(),
                "max_drawdown_pct":      self.max_drawdown_pct(),
                "max_drawdown_duration": self.max_drawdown_duration(),
            },
            "monthly_returns":    monthly,
            "best_month":         round(best_month, 2),
            "worst_month":        round(worst_month, 2),
            "by_symbol":          self.performance_by_symbol(),
            "by_hour":            self.performance_by_hour(),
            "consecutive":        self.consecutive_stats(),
            "generated_at":       datetime.utcnow().isoformat(),
        }

    def save_report(self, path: str):
        """Save full report to JSON file."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.full_report(), f, indent=2, default=str)
        logger.info(f"Report saved to {path}")
