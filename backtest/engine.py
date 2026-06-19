"""
Backtesting Framework
Walk-Forward Analysis, Monte Carlo Simulation, Parameter Optimization.
Anti-overfitting controls built-in.
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import List, Dict, Callable, Tuple, Optional
from itertools import product
from copy import deepcopy
import logging
import json
import os
from datetime import datetime

from python.core.signal_engine import AISignalEngine, SignalDirection
from analytics.performance import PerformanceAnalytics, TradeRecord

logger = logging.getLogger("backtest")


@dataclass
class BacktestConfig:
    symbol: str
    timeframe: str
    start_date: str
    end_date: str
    initial_balance: float  = 10_000.0
    risk_pct: float         = 1.0
    sl_atr_mult: float      = 1.5
    tp_atr_mult: float      = 3.0
    min_confidence: float   = 85.0
    commission_per_lot: float = 7.0   # USD per lot per side
    spread_pips: float      = 1.5
    slippage_pips: float    = 0.5


@dataclass
class BacktestResult:
    config: BacktestConfig
    trades: List[TradeRecord]
    metrics: dict
    equity_curve: List[float]
    generated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


class BacktestEngine:
    """
    Event-driven backtester with realistic cost modeling.
    """

    def __init__(self, config: BacktestConfig):
        self.config  = config
        self.engine  = AISignalEngine(min_confidence=config.min_confidence)
        self.balance = config.initial_balance
        self.equity  = config.initial_balance

    def run(self, df: pd.DataFrame) -> BacktestResult:
        """
        Run backtest on OHLCV DataFrame.
        Expects columns: open, high, low, close, volume, datetime index.
        """
        logger.info(f"Starting backtest | {self.config.symbol} | "
                    f"{self.config.start_date} → {self.config.end_date} | "
                    f"Bars: {len(df)}")

        trades: List[TradeRecord] = []
        balance = self.config.initial_balance
        equity_curve = [balance]

        open_trade: Optional[dict] = None

        # Minimum bars needed for indicators
        min_bars = 210

        for i in range(min_bars, len(df)):
            window = df.iloc[:i].copy()
            current_bar = df.iloc[i]

            current_price = current_bar["close"]
            current_high  = current_bar["high"]
            current_low   = current_bar["low"]
            bar_time      = df.index[i] if hasattr(df.index[i], 'strftime') else i

            # ---- Manage open trade ----
            if open_trade is not None:
                result = self._check_exit(open_trade, current_high, current_low,
                                           current_price, bar_time)
                if result:
                    net_profit = self._apply_costs(result["raw_profit"], open_trade["lots"])
                    balance   += net_profit

                    trades.append(TradeRecord(
                        ticket=open_trade["ticket"],
                        symbol=self.config.symbol,
                        direction=open_trade["direction"],
                        open_time=open_trade["open_time"],
                        close_time=bar_time,
                        open_price=open_trade["entry"],
                        close_price=result["exit_price"],
                        lots=open_trade["lots"],
                        profit=result["raw_profit"],
                        swap=0.0,
                        commission=-self.config.commission_per_lot * open_trade["lots"] * 2,
                        net_profit=net_profit,
                        sl=open_trade["sl"],
                        tp=open_trade["tp"],
                        magic=202401,
                        comment=result["reason"],
                    ))
                    open_trade = None

            # ---- Generate new signal (only if no open trade) ----
            if open_trade is None:
                signal = self.engine.generate_signal(
                    window, self.config.symbol, current_price,
                    self.config.sl_atr_mult, self.config.tp_atr_mult
                )

                if signal and signal.direction != SignalDirection.NONE:
                    lots = self._calc_lots(balance, signal.stop_loss, current_price)
                    if lots > 0:
                        # Apply spread to entry
                        spread = self.config.spread_pips * 0.0001
                        entry  = current_price + spread if signal.direction == SignalDirection.BUY \
                                 else current_price - spread

                        open_trade = {
                            "ticket":    len(trades) + 1,
                            "direction": signal.direction.value,
                            "entry":     entry,
                            "sl":        signal.stop_loss,
                            "tp":        signal.take_profit,
                            "lots":      lots,
                            "open_time": bar_time,
                        }

            equity_curve.append(balance)

        # Close any remaining trade at last bar
        if open_trade is not None:
            last_price = df.iloc[-1]["close"]
            raw_profit = self._raw_profit(open_trade, last_price)
            net_profit = self._apply_costs(raw_profit, open_trade["lots"])
            balance   += net_profit
            trades.append(TradeRecord(
                ticket=open_trade["ticket"],
                symbol=self.config.symbol,
                direction=open_trade["direction"],
                open_time=open_trade["open_time"],
                close_time=df.index[-1],
                open_price=open_trade["entry"],
                close_price=last_price,
                lots=open_trade["lots"],
                profit=raw_profit,
                swap=0.0,
                commission=-self.config.commission_per_lot * open_trade["lots"] * 2,
                net_profit=net_profit,
                sl=open_trade["sl"],
                tp=open_trade["tp"],
                magic=202401,
                comment="End of backtest",
            ))

        # Compute metrics
        analytics = PerformanceAnalytics()
        analytics.initial_balance = self.config.initial_balance
        for t in trades:
            analytics.add_trade(t)

        metrics = analytics.full_report()
        metrics["final_balance"] = round(balance, 2)
        metrics["return_pct"]    = round((balance - self.config.initial_balance) /
                                          self.config.initial_balance * 100, 2)

        logger.info(f"Backtest complete | Trades: {len(trades)} | "
                    f"Net PnL: {metrics['summary']['total_net_profit']:.2f} | "
                    f"WR: {metrics['summary']['win_rate']:.1f}% | "
                    f"Sharpe: {metrics['risk_metrics']['sharpe_ratio']:.3f}")

        return BacktestResult(
            config=self.config,
            trades=trades,
            metrics=metrics,
            equity_curve=equity_curve,
        )

    def _check_exit(self, trade: dict, high: float, low: float,
                    close: float, bar_time) -> Optional[dict]:
        is_buy = trade["direction"] == "BUY"

        if is_buy:
            if low <= trade["sl"]:
                return {"exit_price": trade["sl"], "reason": "SL",
                        "raw_profit": self._raw_profit(trade, trade["sl"])}
            if high >= trade["tp"]:
                return {"exit_price": trade["tp"], "reason": "TP",
                        "raw_profit": self._raw_profit(trade, trade["tp"])}
        else:
            if high >= trade["sl"]:
                return {"exit_price": trade["sl"], "reason": "SL",
                        "raw_profit": self._raw_profit(trade, trade["sl"])}
            if low <= trade["tp"]:
                return {"exit_price": trade["tp"], "reason": "TP",
                        "raw_profit": self._raw_profit(trade, trade["tp"])}
        return None

    def _raw_profit(self, trade: dict, exit_price: float) -> float:
        diff = (exit_price - trade["entry"]) * (1 if trade["direction"] == "BUY" else -1)
        # Approximate: 1 lot = $10 per pip on EURUSD
        pip_value = 10.0
        pip_size  = 0.0001
        return diff / pip_size * pip_value * trade["lots"]

    def _apply_costs(self, raw_profit: float, lots: float) -> float:
        commission = self.config.commission_per_lot * lots * 2
        slippage   = self.config.slippage_pips * 0.0001 / 0.0001 * 10.0 * lots
        return raw_profit - commission - slippage

    def _calc_lots(self, balance: float, sl_price: float, entry: float) -> float:
        sl_dist = abs(entry - sl_price)
        if sl_dist <= 0:
            return 0.0
        risk_amount = balance * (self.config.risk_pct / 100.0)
        pip_value   = 10.0
        pip_size    = 0.0001
        sl_pips     = sl_dist / pip_size
        lots        = risk_amount / (sl_pips * pip_value)
        lots        = round(int(lots / 0.01) * 0.01, 2)
        return max(0.01, min(100.0, lots))


# ------------------------------------------------------------------
# Walk-Forward Analysis
# ------------------------------------------------------------------

class WalkForwardAnalyzer:
    """
    Walk-Forward Analysis: train on IS, test on OOS repeatedly.
    Avoids overfitting by validating on unseen data.
    """

    def __init__(self, n_windows: int = 5, oos_ratio: float = 0.3):
        self.n_windows = n_windows
        self.oos_ratio = oos_ratio

    def run(self, df: pd.DataFrame, base_config: BacktestConfig,
            param_grid: dict) -> dict:
        """
        Run walk-forward analysis over n_windows folds.
        Returns per-window IS/OOS results.
        """
        window_size = len(df) // self.n_windows
        oos_size    = int(window_size * self.oos_ratio)
        is_size     = window_size - oos_size

        results = []
        logger.info(f"Walk-Forward | {self.n_windows} windows | "
                    f"IS: {is_size} | OOS: {oos_size}")

        optimizer = ParameterOptimizer()

        for w in range(self.n_windows):
            start = w * window_size
            is_df  = df.iloc[start : start + is_size]
            oos_df = df.iloc[start + is_size : start + window_size]

            if len(is_df) < 210 or len(oos_df) < 50:
                continue

            # Optimize on IS data
            best_params, is_metrics = optimizer.optimize(is_df, base_config, param_grid)
            logger.info(f"Window {w+1} | Best IS params: {best_params}")

            # Test on OOS data
            oos_config = deepcopy(base_config)
            for k, v in best_params.items():
                setattr(oos_config, k, v)

            oos_engine = BacktestEngine(oos_config)
            oos_result = oos_engine.run(oos_df)

            results.append({
                "window":      w + 1,
                "is_metrics":  is_metrics,
                "oos_metrics": oos_result.metrics,
                "best_params": best_params,
                "is_sharpe":   is_metrics.get("risk_metrics", {}).get("sharpe_ratio", 0),
                "oos_sharpe":  oos_result.metrics.get("risk_metrics", {}).get("sharpe_ratio", 0),
                "oos_wr":      oos_result.metrics.get("summary", {}).get("win_rate", 0),
            })

        overall_oos_sharpe = np.mean([r["oos_sharpe"] for r in results]) if results else 0
        overall_oos_wr     = np.mean([r["oos_wr"] for r in results]) if results else 0
        efficiency         = (overall_oos_sharpe /
                               np.mean([r["is_sharpe"] for r in results if r["is_sharpe"] > 0])
                               if results else 0)

        return {
            "windows":           results,
            "overall_oos_sharpe": round(overall_oos_sharpe, 3),
            "overall_oos_wr":    round(overall_oos_wr, 2),
            "wf_efficiency":     round(efficiency, 3),  # >0.7 = robust strategy
            "n_windows":         len(results),
        }


# ------------------------------------------------------------------
# Monte Carlo Simulation
# ------------------------------------------------------------------

class MonteCarloSimulator:
    """
    Monte Carlo simulation by randomizing trade sequence.
    Tests strategy robustness across thousands of paths.
    """

    def simulate(self, trades: List[TradeRecord], initial_balance: float,
                 n_simulations: int = 1000) -> dict:
        """
        Run n_simulations by shuffling trade order.
        """
        profits = np.array([t.net_profit for t in trades])
        if len(profits) == 0:
            return {}

        logger.info(f"Monte Carlo | {n_simulations} simulations | {len(profits)} trades")

        final_balances = []
        max_drawdowns  = []
        ruin_count     = 0

        for _ in range(n_simulations):
            shuffled   = np.random.permutation(profits)
            equity     = np.cumsum(shuffled) + initial_balance

            final_balances.append(equity[-1])

            # Max drawdown for this path
            peak = np.maximum.accumulate(equity)
            dd   = (peak - equity) / peak * 100
            max_drawdowns.append(float(np.max(dd)))

            # Ruin: account drops below 50% of initial
            if equity.min() < initial_balance * 0.50:
                ruin_count += 1

        final_balances = np.array(final_balances)
        max_drawdowns  = np.array(max_drawdowns)

        return {
            "n_simulations":      n_simulations,
            "n_trades":           len(profits),
            "initial_balance":    initial_balance,
            "final_balance": {
                "mean":   round(float(np.mean(final_balances)), 2),
                "median": round(float(np.median(final_balances)), 2),
                "p5":     round(float(np.percentile(final_balances, 5)), 2),
                "p95":    round(float(np.percentile(final_balances, 95)), 2),
                "min":    round(float(np.min(final_balances)), 2),
                "max":    round(float(np.max(final_balances)), 2),
            },
            "max_drawdown": {
                "mean":   round(float(np.mean(max_drawdowns)), 2),
                "median": round(float(np.median(max_drawdowns)), 2),
                "p95":    round(float(np.percentile(max_drawdowns, 95)), 2),
                "worst":  round(float(np.max(max_drawdowns)), 2),
            },
            "probability_of_profit": round(
                float(np.sum(final_balances > initial_balance) / n_simulations * 100), 1),
            "ruin_probability":      round(ruin_count / n_simulations * 100, 2),
        }


# ------------------------------------------------------------------
# Parameter Optimizer
# ------------------------------------------------------------------

class ParameterOptimizer:
    """
    Grid search optimizer with overfitting controls.
    Ranks by Sharpe ratio, filters by minimum trade count.
    """

    MIN_TRADES = 30   # Minimum trades for a valid result

    def optimize(self, df: pd.DataFrame, base_config: BacktestConfig,
                 param_grid: dict) -> Tuple[dict, dict]:
        """
        Grid search over param_grid. Returns (best_params, best_metrics).
        """
        keys   = list(param_grid.keys())
        values = list(param_grid.values())
        combos = list(product(*values))

        logger.info(f"Optimizer | {len(combos)} combinations to test")

        best_sharpe = -999
        best_params = {}
        best_metrics = {}

        for combo in combos:
            params = dict(zip(keys, combo))
            config = deepcopy(base_config)
            for k, v in params.items():
                setattr(config, k, v)

            try:
                engine = BacktestEngine(config)
                result = engine.run(df)
                n_trades = result.metrics.get("summary", {}).get("total_trades", 0)

                if n_trades < self.MIN_TRADES:
                    continue

                sharpe = result.metrics.get("risk_metrics", {}).get("sharpe_ratio", 0)
                if sharpe > best_sharpe:
                    best_sharpe  = sharpe
                    best_params  = params
                    best_metrics = result.metrics
            except Exception as e:
                logger.debug(f"Combo {params} failed: {e}")
                continue

        logger.info(f"Best params: {best_params} | Sharpe: {best_sharpe:.3f}")
        return best_params, best_metrics
