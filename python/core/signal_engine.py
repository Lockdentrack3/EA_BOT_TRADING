"""
AI Signal Engine
Multi-factor scoring with ML integration.
Generates trade signals with confidence scores.
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional, Dict, Tuple
from enum import Enum
import logging
from datetime import datetime

logger = logging.getLogger("signal_engine")


class SignalDirection(str, Enum):
    BUY  = "BUY"
    SELL = "SELL"
    NONE = "NONE"


class MarketRegime(str, Enum):
    TRENDING_UP    = "TRENDING_UP"
    TRENDING_DOWN  = "TRENDING_DOWN"
    RANGING        = "RANGING"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY  = "LOW_VOLATILITY"
    UNDEFINED      = "UNDEFINED"


@dataclass
class TradeSignal:
    symbol: str
    direction: SignalDirection
    confidence: float             # 0-100
    trend_score: float            # 0-100
    momentum_score: float         # 0-100
    volume_score: float           # 0-100
    liquidity_score: float        # 0-100
    volatility_score: float       # 0-100
    regime: MarketRegime
    atr: float
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_reward: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    description: str = ""
    metadata: Dict = field(default_factory=dict)


class TechnicalIndicators:
    """Compute all technical indicators from OHLCV data."""

    @staticmethod
    def ema(series: pd.Series, period: int) -> pd.Series:
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def rsi(series: pd.Series, period: int = 14) -> pd.Series:
        delta = series.diff()
        gain  = delta.clip(lower=0)
        loss  = -delta.clip(upper=0)
        avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
        avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
        rs  = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        return rsi.fillna(50)

    @staticmethod
    def macd(series: pd.Series, fast: int = 12, slow: int = 26,
             signal: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
        ema_fast   = series.ewm(span=fast,   adjust=False).mean()
        ema_slow   = series.ewm(span=slow,   adjust=False).mean()
        macd_line  = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram  = macd_line - signal_line
        return macd_line, signal_line, histogram

    @staticmethod
    def atr(high: pd.Series, low: pd.Series, close: pd.Series,
            period: int = 14) -> pd.Series:
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low  - close.shift()).abs(),
        ], axis=1).max(axis=1)
        return tr.ewm(com=period - 1, adjust=False).mean()

    @staticmethod
    def bollinger_bands(series: pd.Series, period: int = 20,
                        std_dev: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
        mid  = series.rolling(period).mean()
        std  = series.rolling(period).std()
        upper = mid + std_dev * std
        lower = mid - std_dev * std
        return upper, mid, lower

    @staticmethod
    def stochastic(high: pd.Series, low: pd.Series, close: pd.Series,
                   k: int = 5, d: int = 3) -> Tuple[pd.Series, pd.Series]:
        lowest  = low.rolling(k).min()
        highest = high.rolling(k).max()
        stoch_k = 100 * (close - lowest) / (highest - lowest).replace(0, np.nan)
        stoch_d = stoch_k.rolling(d).mean()
        return stoch_k.fillna(50), stoch_d.fillna(50)

    @staticmethod
    def volume_profile(volume: pd.Series, window: int = 20) -> pd.Series:
        avg_vol = volume.rolling(window).mean()
        return (volume / avg_vol.replace(0, np.nan)).fillna(1.0)


class SMCAnalyzer:
    """Smart Money Concepts analyzer."""

    def __init__(self, lookback: int = 10):
        self.lookback = lookback

    def detect_bos(self, high: pd.Series, low: pd.Series,
                   close: pd.Series) -> Tuple[bool, bool]:
        """Detect Break of Structure: (bullish_bos, bearish_bos)."""
        if len(close) < self.lookback + 2:
            return False, False

        swing_high = high.iloc[-self.lookback:-1].max()
        swing_low  = low.iloc[-self.lookback:-1].min()
        current_close = close.iloc[-1]

        bull_bos = current_close > swing_high
        bear_bos = current_close < swing_low
        return bull_bos, bear_bos

    def detect_choch(self, high: pd.Series, low: pd.Series,
                     close: pd.Series) -> Tuple[bool, bool]:
        """Detect Change of Character: (bullish_choch, bearish_choch)."""
        if len(close) < 4:
            return False, False

        # Previous two candles broke low, now bullish reversal
        prev_broke_low = close.iloc[-3] < low.iloc[-4]
        now_bull       = close.iloc[-1] > high.iloc[-2]

        prev_broke_high = close.iloc[-3] > high.iloc[-4]
        now_bear        = close.iloc[-1] < low.iloc[-2]

        return (prev_broke_low and now_bull), (prev_broke_high and now_bear)

    def detect_order_blocks(self, open_: pd.Series, high: pd.Series,
                             low: pd.Series, close: pd.Series,
                             atr: float) -> Tuple[bool, bool]:
        """Detect bullish and bearish order blocks."""
        if len(close) < 4:
            return False, False

        # Bullish OB: series of bearish candles before large bull move
        bearish_prev = close.iloc[-3] < open_.iloc[-3]
        big_bull     = (close.iloc[-1] - open_.iloc[-1]) > atr
        bull_ob      = bearish_prev and big_bull

        # Bearish OB: series of bullish candles before large bear move
        bullish_prev = close.iloc[-3] > open_.iloc[-3]
        big_bear     = (open_.iloc[-1] - close.iloc[-1]) > atr
        bear_ob      = bullish_prev and big_bear

        return bull_ob, bear_ob

    def detect_fvg(self, high: pd.Series, low: pd.Series) -> Tuple[bool, bool]:
        """Detect Fair Value Gaps."""
        if len(high) < 3:
            return False, False

        bull_fvg = high.iloc[-3] < low.iloc[-1]   # Gap up (bullish imbalance)
        bear_fvg = low.iloc[-3] > high.iloc[-1]   # Gap down (bearish imbalance)
        return bull_fvg, bear_fvg

    def get_liquidity_levels(self, high: pd.Series,
                              low: pd.Series) -> Tuple[float, float]:
        """Get key liquidity levels (equal highs/lows)."""
        return high.rolling(20).max().iloc[-1], low.rolling(20).min().iloc[-1]


class MarketRegimeDetector:
    """Detect current market regime using multiple methods."""

    def detect(self, close: pd.Series, high: pd.Series, low: pd.Series,
               atr: pd.Series, ema_fast: pd.Series,
               ema_slow: pd.Series) -> MarketRegime:
        if len(close) < 50:
            return MarketRegime.UNDEFINED

        current_atr = atr.iloc[-1]
        avg_atr     = atr.iloc[-20:].mean()
        atr_ratio   = current_atr / avg_atr if avg_atr > 0 else 1.0

        if atr_ratio > 1.8:
            return MarketRegime.HIGH_VOLATILITY
        if atr_ratio < 0.5:
            return MarketRegime.LOW_VOLATILITY

        ema_spread = abs(ema_fast.iloc[-1] - ema_slow.iloc[-1])
        spread_pct = ema_spread / ema_slow.iloc[-1] * 100 if ema_slow.iloc[-1] > 0 else 0

        if spread_pct > 0.15:
            if ema_fast.iloc[-1] > ema_slow.iloc[-1]:
                return MarketRegime.TRENDING_UP
            else:
                return MarketRegime.TRENDING_DOWN

        return MarketRegime.RANGING


class AISignalEngine:
    """
    Core AI Signal Engine combining technical + SMC + ML scoring.
    Produces a 0-100 confidence score for each potential trade.
    """

    WEIGHTS = {
        "trend":      0.30,
        "momentum":   0.25,
        "volume":     0.20,
        "liquidity":  0.15,
        "volatility": 0.10,
    }

    def __init__(self, min_confidence: float = 85.0):
        self.min_confidence = min_confidence
        self.ti     = TechnicalIndicators()
        self.smc    = SMCAnalyzer()
        self.regime = MarketRegimeDetector()

    def compute_indicators(self, df: pd.DataFrame) -> dict:
        """Compute all indicators from OHLCV DataFrame."""
        c = df["close"]
        h = df["high"]
        l = df["low"]
        v = df["volume"]
        o = df["open"] if "open" in df.columns else c

        ema50  = self.ti.ema(c, 50)
        ema200 = self.ti.ema(c, 200)
        rsi    = self.ti.rsi(c, 14)
        macd_line, macd_sig, macd_hist = self.ti.macd(c)
        atr_s  = self.ti.atr(h, l, c, 14)
        bb_up, bb_mid, bb_low = self.ti.bollinger_bands(c, 20, 2.0)
        stk, std = self.ti.stochastic(h, l, c)
        vol_ratio = self.ti.volume_profile(v)

        return {
            "ema50": ema50, "ema200": ema200,
            "rsi": rsi, "macd_line": macd_line,
            "macd_sig": macd_sig, "macd_hist": macd_hist,
            "atr": atr_s, "bb_up": bb_up,
            "bb_mid": bb_mid, "bb_low": bb_low,
            "stoch_k": stk, "stoch_d": std,
            "vol_ratio": vol_ratio,
            "open": o, "high": h, "low": l,
            "close": c, "volume": v,
        }

    def score_trend(self, ind: dict) -> float:
        score = 50.0
        c       = ind["close"].iloc[-1]
        ema50   = ind["ema50"].iloc[-1]
        ema200  = ind["ema200"].iloc[-1]
        ema50_prev  = ind["ema50"].iloc[-2]

        # EMA alignment
        if ema50 > ema200:  score += 15
        else:               score -= 15

        # Price vs EMA50
        if c > ema50: score += 10
        else:         score -= 10

        # EMA50 slope
        if ema50 > ema50_prev: score += 8
        else:                  score -= 8

        # BOS/CHOCH
        bull_bos, bear_bos = self.smc.detect_bos(ind["high"], ind["low"], ind["close"])
        bull_choch, bear_choch = self.smc.detect_choch(ind["high"], ind["low"], ind["close"])

        if bull_bos:   score += 12
        if bear_bos:   score -= 12
        if bull_choch: score += 10
        if bear_choch: score -= 10

        # Order blocks
        bull_ob, bear_ob = self.smc.detect_order_blocks(
            ind["open"], ind["high"], ind["low"], ind["close"], ind["atr"].iloc[-1]
        )
        if bull_ob: score += 5
        if bear_ob: score -= 5

        return max(0.0, min(100.0, score))

    def score_momentum(self, ind: dict) -> float:
        score = 50.0
        rsi     = ind["rsi"].iloc[-1]
        ml      = ind["macd_line"]
        ms      = ind["macd_sig"]
        stk     = ind["stoch_k"].iloc[-1]
        std_    = ind["stoch_d"].iloc[-1]

        # RSI
        if 50 < rsi < 70:  score += 15
        elif 30 < rsi < 50: score -= 15
        elif rsi >= 70:    score -= 5
        elif rsi <= 30:    score += 5

        # MACD crossover
        macd_cross_up   = ml.iloc[-1] > ms.iloc[-1] and ml.iloc[-2] <= ms.iloc[-2]
        macd_cross_down = ml.iloc[-1] < ms.iloc[-1] and ml.iloc[-2] >= ms.iloc[-2]

        if macd_cross_up:    score += 20
        elif macd_cross_down: score -= 20
        elif ml.iloc[-1] > ms.iloc[-1]: score += 10
        else:                           score -= 10

        if ml.iloc[-1] > 0: score += 5
        else:               score -= 5

        # Stochastic
        if stk > std_ and stk < 80:  score += 10
        elif stk < std_ and stk > 20: score -= 10

        return max(0.0, min(100.0, score))

    def score_volume(self, ind: dict) -> float:
        score    = 50.0
        vr       = ind["vol_ratio"].iloc[-1]
        v        = ind["volume"]

        if vr > 2.0:   score += 30
        elif vr > 1.5: score += 15
        elif vr < 0.5: score -= 20

        if v.iloc[-1] > v.iloc[-2] > v.iloc[-3]: score += 10
        elif v.iloc[-1] < v.iloc[-2]:             score -= 5

        bull_fvg, bear_fvg = self.smc.detect_fvg(ind["high"], ind["low"])
        if bull_fvg or bear_fvg: score += 10

        return max(0.0, min(100.0, score))

    def score_liquidity(self, ind: dict) -> float:
        score = 50.0
        c     = ind["close"].iloc[-1]
        bull_ob, bear_ob = self.smc.detect_order_blocks(
            ind["open"], ind["high"], ind["low"], ind["close"], ind["atr"].iloc[-1]
        )
        if bull_ob: score += 20
        if bear_ob: score += 20

        liq_high, liq_low = self.smc.get_liquidity_levels(ind["high"], ind["low"])
        zone_range = liq_high - liq_low
        if zone_range > 0:
            near = (liq_low * 0.9 <= c <= liq_high * 1.1)
            if near: score += 15

        bull_fvg, bear_fvg = self.smc.detect_fvg(ind["high"], ind["low"])
        if bull_fvg: score += 15
        if bear_fvg: score += 15

        return max(0.0, min(100.0, score))

    def score_volatility(self, ind: dict) -> float:
        score    = 50.0
        atr_now  = ind["atr"].iloc[-1]
        atr_avg  = ind["atr"].iloc[-5:].mean()
        atr_ratio = atr_now / atr_avg if atr_avg > 0 else 1.0

        if atr_ratio > 1.8:   score -= 30   # Too volatile
        elif atr_ratio > 1.1: score += 10
        elif atr_ratio < 0.6: score -= 15

        bb_width = ind["bb_up"].iloc[-1] - ind["bb_low"].iloc[-1]
        bb_mid   = ind["bb_mid"].iloc[-1]
        bb_ratio = (bb_width / bb_mid * 100) if bb_mid > 0 else 0

        if bb_ratio < 1.0: score -= 10
        if bb_ratio > 3.0: score -= 10

        if ind["close"].iloc[-1] > bb_mid: score += 5
        else:                               score -= 5

        return max(0.0, min(100.0, score))

    def calculate_confidence(self, scores: dict) -> float:
        return sum(
            scores[k] * self.WEIGHTS[k] for k in self.WEIGHTS
        )

    def generate_signal(self, df: pd.DataFrame, symbol: str,
                         current_price: float,
                         sl_atr_mult: float = 1.5,
                         tp_atr_mult: float = 3.0) -> Optional[TradeSignal]:
        """
        Main entry: generate a trade signal from OHLCV data.
        Returns None if confidence < min_confidence.
        """
        if len(df) < 210:
            logger.warning(f"Insufficient data for {symbol}: {len(df)} bars")
            return None

        ind = self.compute_indicators(df)
        atr = ind["atr"].iloc[-1]

        # Compute sub-scores
        scores = {
            "trend":      self.score_trend(ind),
            "momentum":   self.score_momentum(ind),
            "volume":     self.score_volume(ind),
            "liquidity":  self.score_liquidity(ind),
            "volatility": self.score_volatility(ind),
        }

        confidence = self.calculate_confidence(scores)

        # Determine direction
        bullish = scores["trend"] > 60 and scores["momentum"] > 55
        bearish = scores["trend"] < 40 and scores["momentum"] < 45

        if bullish and not bearish:
            direction = SignalDirection.BUY
        elif bearish and not bullish:
            direction = SignalDirection.SELL
        else:
            logger.debug(f"{symbol}: No clear direction | Scores: {scores}")
            return None

        if confidence < self.min_confidence:
            logger.debug(f"{symbol}: Confidence {confidence:.1f}% below threshold")
            return None

        # Calculate levels
        sl_dist = atr * sl_atr_mult
        tp_dist = atr * tp_atr_mult

        if direction == SignalDirection.BUY:
            sl = current_price - sl_dist
            tp = current_price + tp_dist
        else:
            sl = current_price + sl_dist
            tp = current_price - tp_dist

        rr = tp_dist / sl_dist if sl_dist > 0 else 0

        # Detect regime
        regime = self.regime.detect(
            ind["close"], ind["high"], ind["low"],
            ind["atr"], ind["ema50"], ind["ema200"]
        )

        signal = TradeSignal(
            symbol=symbol,
            direction=direction,
            confidence=round(confidence, 2),
            trend_score=round(scores["trend"], 2),
            momentum_score=round(scores["momentum"], 2),
            volume_score=round(scores["volume"], 2),
            liquidity_score=round(scores["liquidity"], 2),
            volatility_score=round(scores["volatility"], 2),
            regime=regime,
            atr=atr,
            entry_price=current_price,
            stop_loss=sl,
            take_profit=tp,
            risk_reward=round(rr, 2),
            description=f"{direction.value} signal | Regime: {regime.value}",
            metadata={"scores": scores, "atr": atr},
        )

        logger.info(
            f"SIGNAL GENERATED | {symbol} {direction.value} | "
            f"Conf: {confidence:.1f}% | RR: {rr:.2f} | Regime: {regime.value}"
        )
        return signal
