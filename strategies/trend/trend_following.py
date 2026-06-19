"""
Trend Following Strategy
Used when market regime = TRENDING_UP or TRENDING_DOWN.
Trades in the direction of the primary trend with pullback entries.
"""

import pandas as pd
import numpy as np
from python.core.signal_engine import AISignalEngine, SignalDirection, TradeSignal
from typing import Optional
import logging

logger = logging.getLogger("strategy.trend")


class TrendFollowingStrategy:
    """
    Entry: Price pulls back to EMA50 in a trending market.
    Confirmation: RSI > 50 (bull) or RSI < 50 (bear) + MACD aligned.
    Target: 1:3 R:R minimum.
    """

    name = "TrendFollowing"

    def __init__(self, engine: AISignalEngine,
                 pullback_ema_period: int = 50,
                 min_rr: float = 2.5):
        self.engine = engine
        self.pullback_ema = pullback_ema_period
        self.min_rr = min_rr

    def evaluate(self, df: pd.DataFrame, symbol: str,
                  current_price: float) -> Optional[TradeSignal]:
        """Evaluate entry on pullback to EMA50 in trending market."""
        if len(df) < 210:
            return None

        ind = self.engine.compute_indicators(df)

        ema50   = ind["ema50"].iloc[-1]
        ema200  = ind["ema200"].iloc[-1]
        rsi     = ind["rsi"].iloc[-1]
        atr     = ind["atr"].iloc[-1]

        # Is this a trending market?
        is_uptrend   = ema50 > ema200 and current_price > ema200
        is_downtrend = ema50 < ema200 and current_price < ema200

        if not (is_uptrend or is_downtrend):
            return None

        # Pullback entry condition
        near_ema50  = abs(current_price - ema50) < atr * 0.5
        bull_entry  = is_uptrend and near_ema50 and rsi > 45 and rsi < 65
        bear_entry  = is_downtrend and near_ema50 and rsi < 55 and rsi > 35

        if not (bull_entry or bear_entry):
            return None

        signal = self.engine.generate_signal(
            df, symbol, current_price,
            sl_atr_mult=1.2,   # Tighter SL on pullbacks
            tp_atr_mult=3.0,
        )

        if signal and signal.risk_reward >= self.min_rr:
            logger.info(f"TrendFollowing signal | {symbol} | {signal.direction.value} | "
                         f"RR: {signal.risk_reward:.2f}")
            return signal

        return None
