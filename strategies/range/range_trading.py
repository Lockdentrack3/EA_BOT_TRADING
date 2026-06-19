"""
Range Trading Strategy
Used when market regime = RANGING.
Buys support, sells resistance. Uses Bollinger Bands for boundaries.
"""

import pandas as pd
import numpy as np
from python.core.signal_engine import AISignalEngine, SignalDirection, TradeSignal
from typing import Optional
import logging

logger = logging.getLogger("strategy.range")


class RangeTradingStrategy:
    """
    Entry: Price near lower BB (buy) or upper BB (sell) in range regime.
    Confirmation: RSI reversal + Stochastic oversold/overbought.
    Target: 1:2 R:R (range midpoint as TP).
    """

    name = "RangeTrading"

    def __init__(self, engine: AISignalEngine,
                 bb_threshold: float = 0.1,
                 rsi_oversold: float = 35.0,
                 rsi_overbought: float = 65.0):
        self.engine         = engine
        self.bb_threshold   = bb_threshold
        self.rsi_oversold   = rsi_oversold
        self.rsi_overbought = rsi_overbought

    def evaluate(self, df: pd.DataFrame, symbol: str,
                  current_price: float) -> Optional[TradeSignal]:
        if len(df) < 50:
            return None

        ind = self.engine.compute_indicators(df)

        bb_up  = ind["bb_up"].iloc[-1]
        bb_mid = ind["bb_mid"].iloc[-1]
        bb_low = ind["bb_low"].iloc[-1]
        rsi    = ind["rsi"].iloc[-1]
        stk    = ind["stoch_k"].iloc[-1]
        std_   = ind["stoch_d"].iloc[-1]
        atr    = ind["atr"].iloc[-1]
        bb_range = bb_up - bb_low

        # Near lower band — potential buy
        near_lower = current_price <= bb_low + bb_range * self.bb_threshold
        near_upper = current_price >= bb_up  - bb_range * self.bb_threshold

        bull_reversal = (near_lower and rsi < self.rsi_oversold and stk < 25 and stk > std_)
        bear_reversal = (near_upper and rsi > self.rsi_overbought and stk > 75 and stk < std_)

        if not (bull_reversal or bear_reversal):
            return None

        direction = SignalDirection.BUY if bull_reversal else SignalDirection.SELL

        if direction == SignalDirection.BUY:
            sl = current_price - atr * 1.0
            tp = bb_mid  # Range midpoint as TP
        else:
            sl = current_price + atr * 1.0
            tp = bb_mid

        rr = abs(tp - current_price) / abs(sl - current_price) if abs(sl - current_price) > 0 else 0
        if rr < 1.5:
            return None

        logger.info(f"RangeTrading signal | {symbol} | {direction.value} | RR: {rr:.2f}")

        from python.core.signal_engine import MarketRegime
        from datetime import datetime
        return TradeSignal(
            symbol=symbol,
            direction=direction,
            confidence=75.0,  # Lower confidence for range trades
            trend_score=40.0,
            momentum_score=ind["rsi"].iloc[-1],
            volume_score=60.0,
            liquidity_score=50.0,
            volatility_score=70.0,
            regime=MarketRegime.RANGING,
            atr=atr,
            entry_price=current_price,
            stop_loss=sl,
            take_profit=tp,
            risk_reward=round(rr, 2),
            description=f"Range {'buy at support' if bull_reversal else 'sell at resistance'}",
        )


# ------------------------------------------------------------------

class VolatilityBreakoutStrategy:
    """
    Volatility Breakout Strategy
    Used after a Bollinger Band squeeze (low volatility compression).
    Trades the breakout in the direction of the move.
    """

    name = "VolatilityBreakout"

    def __init__(self, engine: AISignalEngine,
                 squeeze_ratio: float = 0.5,
                 breakout_atr_mult: float = 1.2):
        self.engine             = engine
        self.squeeze_ratio      = squeeze_ratio
        self.breakout_atr_mult  = breakout_atr_mult

    def evaluate(self, df: pd.DataFrame, symbol: str,
                  current_price: float) -> Optional[TradeSignal]:
        if len(df) < 50:
            return None

        ind = self.engine.compute_indicators(df)

        bb_up    = ind["bb_up"]
        bb_low   = ind["bb_low"]
        bb_mid   = ind["bb_mid"]
        atr      = ind["atr"].iloc[-1]
        close    = ind["close"]

        # Measure BB width ratio (current vs recent average)
        current_width = bb_up.iloc[-1] - bb_low.iloc[-1]
        avg_width     = (bb_up - bb_low).iloc[-20:].mean()
        squeeze       = current_width / avg_width if avg_width > 0 else 1.0

        # Only act after a squeeze
        if squeeze > self.squeeze_ratio:
            return None

        # Determine breakout direction
        prev_close    = close.iloc[-2]
        current_close = close.iloc[-1]

        bull_break = current_close > bb_up.iloc[-1] and current_close > prev_close + atr * 0.5
        bear_break = current_close < bb_low.iloc[-1] and current_close < prev_close - atr * 0.5

        if not (bull_break or bear_break):
            return None

        direction = SignalDirection.BUY if bull_break else SignalDirection.SELL

        if direction == SignalDirection.BUY:
            sl = current_price - atr * self.breakout_atr_mult
            tp = current_price + atr * 3.0
        else:
            sl = current_price + atr * self.breakout_atr_mult
            tp = current_price - atr * 3.0

        rr = abs(tp - current_price) / abs(sl - current_price) if abs(sl - current_price) > 0 else 0
        if rr < 2.0:
            return None

        logger.info(f"VolatilityBreakout signal | {symbol} | {direction.value} | "
                     f"Squeeze: {squeeze:.2f} | RR: {rr:.2f}")

        from python.core.signal_engine import MarketRegime
        return TradeSignal(
            symbol=symbol,
            direction=direction,
            confidence=80.0,
            trend_score=55.0,
            momentum_score=70.0,
            volume_score=80.0,
            liquidity_score=60.0,
            volatility_score=85.0,
            regime=MarketRegime.LOW_VOLATILITY,
            atr=atr,
            entry_price=current_price,
            stop_loss=sl,
            take_profit=tp,
            risk_reward=round(rr, 2),
            description=f"BB Squeeze breakout {'up' if bull_break else 'down'}",
        )
