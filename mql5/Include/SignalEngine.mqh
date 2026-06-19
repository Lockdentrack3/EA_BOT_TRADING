//+------------------------------------------------------------------+
//|  SignalEngine.mqh                                                |
//|  Multi-Factor Signal Engine: Trend + Momentum + SMC + Volume    |
//+------------------------------------------------------------------+
#pragma once

//--- Signal direction enum
enum ENUM_SIGNAL_DIRECTION { SIGNAL_NONE = 0, SIGNAL_BUY = 1, SIGNAL_SELL = -1 };

//--- Trade signal structure
struct STradeSignal
{
   ENUM_SIGNAL_DIRECTION direction;
   double trendScore;      // 0-100
   double momentumScore;   // 0-100
   double volumeScore;     // 0-100
   double liquidityScore;  // 0-100
   double volatilityScore; // 0-100
   double atr;
   datetime timestamp;
   string description;
};

//--- Smart Money Concepts structure
struct SSMC
{
   bool   hasBOS_Bull;      // Break of Structure bullish
   bool   hasBOS_Bear;      // Break of Structure bearish
   bool   hasCHoCH_Bull;    // Change of Character bullish
   bool   hasCHoCH_Bear;    // Change of Character bearish
   bool   hasOrderBlock_Bull;
   bool   hasOrderBlock_Bear;
   bool   hasFVG_Bull;      // Fair Value Gap bullish
   bool   hasFVG_Bear;      // Fair Value Gap bearish
   double liquZoneHigh;     // Liquidity zone high
   double liquZoneLow;      // Liquidity zone low
};

//+------------------------------------------------------------------+
//| Signal Engine Class                                              |
//+------------------------------------------------------------------+
class CSignalEngine
{
private:
   // Indicator handles
   int    m_hEMA_Fast;
   int    m_hEMA_Slow;
   int    m_hRSI;
   int    m_hATR;
   int    m_hBB;
   int    m_hMACD;
   int    m_hStoch;

   // Parameters
   int    m_emaFast, m_emaSlow;
   int    m_rsiPeriod, m_atrPeriod;
   int    m_bbPeriod; double m_bbDev;
   int    m_macdFast, m_macdSlow, m_macdSig;
   int    m_stochK, m_stochD;

   string m_symbol;
   ENUM_TIMEFRAMES m_tf;

   // Cached values
   double m_emaFastVal[3], m_emaSlowVal[3];
   double m_rsiVal[3];
   double m_atrVal[3];
   double m_bbUpper[3], m_bbMiddle[3], m_bbLower[3];
   double m_macdMain[3], m_macdSignal[3];
   double m_stochMain[3], m_stochSignal[3];
   double m_volume[10];
   double m_close[10], m_high[10], m_low[10];

   // SMC cache
   SSMC   m_smc;

public:
   CSignalEngine(int emaFast, int emaSlow, int rsiPeriod, int atrPeriod,
                  int bbPeriod, double bbDev,
                  int macdFast, int macdSlow, int macdSig,
                  int stochK, int stochD)
   {
      m_emaFast = emaFast; m_emaSlow = emaSlow;
      m_rsiPeriod = rsiPeriod; m_atrPeriod = atrPeriod;
      m_bbPeriod = bbPeriod; m_bbDev = bbDev;
      m_macdFast = macdFast; m_macdSlow = macdSlow; m_macdSig = macdSig;
      m_stochK = stochK; m_stochD = stochD;
      m_hEMA_Fast = m_hEMA_Slow = m_hRSI = m_hATR = INVALID_HANDLE;
      m_hBB = m_hMACD = m_hStoch = INVALID_HANDLE;
   }

   ~CSignalEngine()
   {
      ReleaseHandles();
   }

   bool Initialize(string symbol, ENUM_TIMEFRAMES tf)
   {
      m_symbol = symbol;
      m_tf     = tf;

      m_hEMA_Fast = iMA(m_symbol, m_tf, m_emaFast,  0, MODE_EMA, PRICE_CLOSE);
      m_hEMA_Slow = iMA(m_symbol, m_tf, m_emaSlow,  0, MODE_EMA, PRICE_CLOSE);
      m_hRSI      = iRSI(m_symbol, m_tf, m_rsiPeriod, PRICE_CLOSE);
      m_hATR      = iATR(m_symbol, m_tf, m_atrPeriod);
      m_hBB       = iBands(m_symbol, m_tf, m_bbPeriod, 0, m_bbDev, PRICE_CLOSE);
      m_hMACD     = iMACD(m_symbol, m_tf, m_macdFast, m_macdSlow, m_macdSig, PRICE_CLOSE);
      m_hStoch    = iStochastic(m_symbol, m_tf, m_stochK, m_stochD, 3,
                                 MODE_SMA, STO_LOWHIGH);

      bool valid = (m_hEMA_Fast != INVALID_HANDLE && m_hEMA_Slow != INVALID_HANDLE &&
                    m_hRSI      != INVALID_HANDLE && m_hATR      != INVALID_HANDLE &&
                    m_hBB       != INVALID_HANDLE && m_hMACD     != INVALID_HANDLE &&
                    m_hStoch    != INVALID_HANDLE);

      if(!valid) Print("SignalEngine: One or more indicator handles invalid");
      return valid;
   }

   void Update()
   {
      CopyBuffer(m_hEMA_Fast, 0, 0, 3, m_emaFastVal);
      CopyBuffer(m_hEMA_Slow, 0, 0, 3, m_emaSlowVal);
      CopyBuffer(m_hRSI,      0, 0, 3, m_rsiVal);
      CopyBuffer(m_hATR,      0, 0, 3, m_atrVal);
      CopyBuffer(m_hBB,  UPPER_BAND, 0, 3, m_bbUpper);
      CopyBuffer(m_hBB,  BASE_LINE,  0, 3, m_bbMiddle);
      CopyBuffer(m_hBB,  LOWER_BAND, 0, 3, m_bbLower);
      CopyBuffer(m_hMACD, MAIN_LINE,   0, 3, m_macdMain);
      CopyBuffer(m_hMACD, SIGNAL_LINE, 0, 3, m_macdSignal);
      CopyBuffer(m_hStoch, MAIN_LINE,   0, 3, m_stochMain);
      CopyBuffer(m_hStoch, SIGNAL_LINE, 0, 3, m_stochSignal);

      // Price data
      CopyClose(m_symbol, m_tf, 0, 10, m_close);
      CopyHigh(m_symbol,  m_tf, 0, 10, m_high);
      CopyLow(m_symbol,   m_tf, 0, 10, m_low);
      CopyTickVolume(m_symbol, m_tf, 0, 10, m_volume);

      // Update SMC analysis
      AnalyzeSMC();
   }

   double GetATR() { return m_atrVal[1]; }

   bool GenerateSignal(STradeSignal &signal)
   {
      signal.trendScore      = CalcTrendScore();
      signal.momentumScore   = CalcMomentumScore();
      signal.volumeScore     = CalcVolumeScore();
      signal.liquidityScore  = CalcLiquidityScore();
      signal.volatilityScore = CalcVolatilityScore();
      signal.atr             = m_atrVal[1];
      signal.timestamp       = TimeCurrent();

      // Determine direction
      bool bullish = (signal.trendScore > 60 && signal.momentumScore > 55);
      bool bearish = (signal.trendScore < 40 && signal.momentumScore < 45);

      if(bullish && !bearish)
      {
         signal.direction = SIGNAL_BUY;
         signal.description = "Bullish: Trend+Momentum+SMC aligned";
      }
      else if(bearish && !bullish)
      {
         signal.direction = SIGNAL_SELL;
         signal.description = "Bearish: Trend+Momentum+SMC aligned";
      }
      else
      {
         signal.direction = SIGNAL_NONE;
         return false;
      }

      return true;
   }

private:
   //--- Trend Score (EMA alignment + BOS + CHOCH)
   double CalcTrendScore()
   {
      double score = 50.0; // Neutral

      // EMA 50 vs EMA 200 alignment
      bool emasBull = (m_emaFastVal[1] > m_emaSlowVal[1]);
      bool emasBear = (m_emaFastVal[1] < m_emaSlowVal[1]);

      if(emasBull) score += 15;
      else if(emasBear) score -= 15;

      // Price vs EMA 50
      double ask = SymbolInfoDouble(m_symbol, SYMBOL_ASK);
      if(ask > m_emaFastVal[1]) score += 10;
      else score -= 10;

      // EMA slope
      double emaFastSlope = m_emaFastVal[1] - m_emaFastVal[2];
      if(emaFastSlope > 0) score += 8;
      else score -= 8;

      // BOS/CHOCH from SMC
      if(m_smc.hasBOS_Bull)   score += 12;
      if(m_smc.hasBOS_Bear)   score -= 12;
      if(m_smc.hasCHoCH_Bull) score += 10;
      if(m_smc.hasCHoCH_Bear) score -= 10;

      // Order blocks
      if(m_smc.hasOrderBlock_Bull) score += 5;
      if(m_smc.hasOrderBlock_Bear) score -= 5;

      return MathMax(0, MathMin(100, score));
   }

   //--- Momentum Score (RSI + MACD + Stochastic)
   double CalcMomentumScore()
   {
      double score = 50.0;

      // RSI analysis
      double rsi = m_rsiVal[1];
      if(rsi > 50 && rsi < 70)       score += 15;  // Bullish momentum
      else if(rsi < 50 && rsi > 30)  score -= 15;  // Bearish momentum
      else if(rsi >= 70)             score -= 5;   // Overbought - caution
      else if(rsi <= 30)             score += 5;   // Oversold - caution

      // MACD crossover
      bool macdBull = (m_macdMain[1] > m_macdSignal[1] && m_macdMain[2] <= m_macdSignal[2]);
      bool macdBear = (m_macdMain[1] < m_macdSignal[1] && m_macdMain[2] >= m_macdSignal[2]);

      if(macdBull) score += 20;
      else if(macdBear) score -= 20;
      else if(m_macdMain[1] > m_macdSignal[1]) score += 10;
      else score -= 10;

      // MACD above zero line
      if(m_macdMain[1] > 0) score += 5;
      else score -= 5;

      // Stochastic
      double stochK = m_stochMain[1];
      double stochD = m_stochSignal[1];
      if(stochK > stochD && stochK < 80)  score += 10;
      else if(stochK < stochD && stochK > 20) score -= 10;

      return MathMax(0, MathMin(100, score));
   }

   //--- Volume Score (tick volume analysis)
   double CalcVolumeScore()
   {
      // Calculate average volume (bars 2-10)
      double avgVol = 0;
      for(int i = 2; i < 10; i++) avgVol += m_volume[i];
      avgVol /= 8.0;

      if(avgVol == 0) return 50.0;

      double currentVol = m_volume[1];
      double volRatio   = currentVol / avgVol;

      double score = 50.0;

      // Volume spike detection
      if(volRatio > 2.0)      score += 30; // Strong volume spike
      else if(volRatio > 1.5) score += 15; // Moderate volume
      else if(volRatio < 0.5) score -= 20; // Low volume - weak signal

      // Volume trend (increasing or decreasing)
      if(m_volume[1] > m_volume[2] && m_volume[2] > m_volume[3]) score += 10;
      else if(m_volume[1] < m_volume[2]) score -= 5;

      // FVG presence adds to volume/liquidity context
      if(m_smc.hasFVG_Bull || m_smc.hasFVG_Bear) score += 10;

      return MathMax(0, MathMin(100, score));
   }

   //--- Liquidity / SMC Score
   double CalcLiquidityScore()
   {
      double score = 50.0;
      double price = m_close[1];

      // Near order block
      if(m_smc.hasOrderBlock_Bull) score += 20;
      if(m_smc.hasOrderBlock_Bear) score += 20; // Both sides provide context

      // Near liquidity zone
      double zoneRange = m_smc.liquZoneHigh - m_smc.liquZoneLow;
      if(zoneRange > 0)
      {
         bool nearZone = (price >= m_smc.liquZoneLow - zoneRange * 0.1 &&
                          price <= m_smc.liquZoneHigh + zoneRange * 0.1);
         if(nearZone) score += 15;
      }

      // FVG
      if(m_smc.hasFVG_Bull) score += 15;
      if(m_smc.hasFVG_Bear) score += 15;

      return MathMax(0, MathMin(100, score));
   }

   //--- Volatility Score (ATR + Bollinger Bands)
   double CalcVolatilityScore()
   {
      double score = 50.0;
      double atr    = m_atrVal[1];
      double price  = m_close[1];
      double bbWidth = m_bbUpper[1] - m_bbLower[1];

      // ATR-based volatility regime
      double atrMA = 0;
      for(int i = 1; i <= 3; i++) atrMA += m_atrVal[i];
      atrMA /= 3.0;

      if(atr > atrMA * 1.3)       score -= 20; // Too volatile
      else if(atr > atrMA * 1.1)  score += 10; // Good momentum volatility
      else if(atr < atrMA * 0.7)  score -= 15; // Too quiet - low opportunity

      // Bollinger Band squeeze (contraction before breakout)
      if(price <= m_bbMiddle[1])  score -= 5;
      else                         score += 5;

      // BB width vs BB middle
      double bbRatio = (bbWidth / m_bbMiddle[1]) * 100;
      if(bbRatio < 1.0)  score -= 10; // Squeeze - uncertain
      if(bbRatio > 3.0)  score -= 10; // Too wide - avoid

      return MathMax(0, MathMin(100, score));
   }

   //--- Smart Money Concepts Analysis
   void AnalyzeSMC()
   {
      // Reset
      ZeroMemory(m_smc);

      // Break of Structure (BOS) - simplified detection
      // Look for swing high/low breaks
      double swingHigh = 0, swingLow = DBL_MAX;
      for(int i = 2; i <= 6; i++)
      {
         if(m_high[i] > swingHigh) swingHigh = m_high[i];
         if(m_low[i]  < swingLow)  swingLow  = m_low[i];
      }

      // Current bar closes above recent swing high = BOS bullish
      if(m_close[1] > swingHigh) m_smc.hasBOS_Bull = true;
      if(m_close[1] < swingLow)  m_smc.hasBOS_Bear = true;

      // Change of Character (CHoCH) - shift in market structure
      // Previous BOS bear followed by bull candle = CHoCH bull
      if(m_close[2] < m_low[3] && m_close[1] > m_high[2])
         m_smc.hasCHoCH_Bull = true;
      if(m_close[2] > m_high[3] && m_close[1] < m_low[2])
         m_smc.hasCHoCH_Bear = true;

      // Order Block detection
      // Bullish OB: last bearish candle before significant bullish move
      if(m_close[3] < m_open[3] && m_close[2] < m_open[2] &&
         m_close[1] > m_open[1] && (m_close[1] - m_open[1]) > m_atrVal[1])
         m_smc.hasOrderBlock_Bull = true;

      // Bearish OB: last bullish candle before significant bearish move
      if(m_close[3] > m_open[3] && m_close[2] > m_open[2] &&
         m_close[1] < m_open[1] && (m_open[1] - m_close[1]) > m_atrVal[1])
         m_smc.hasOrderBlock_Bear = true;

      // Fair Value Gap (FVG) - 3-candle imbalance
      // Bullish FVG: high[3] < low[1] (gap between 3-bar high and current low)
      if(m_high[3] < m_low[1]) m_smc.hasFVG_Bull = true;
      if(m_low[3] > m_high[1]) m_smc.hasFVG_Bear = true;

      // Liquidity zones (equal highs/lows within recent bars)
      double highTolerance = m_atrVal[1] * 0.3;
      double nearHigh = 0, nearLow = DBL_MAX;
      for(int i = 1; i <= 8; i++)
      {
         if(m_high[i] > nearHigh) nearHigh = m_high[i];
         if(m_low[i]  < nearLow)  nearLow  = m_low[i];
      }
      m_smc.liquZoneHigh = nearHigh;
      m_smc.liquZoneLow  = nearLow;
   }

   // Helper arrays for open prices
   double m_open[10];

   void ReleaseHandles()
   {
      if(m_hEMA_Fast != INVALID_HANDLE) IndicatorRelease(m_hEMA_Fast);
      if(m_hEMA_Slow != INVALID_HANDLE) IndicatorRelease(m_hEMA_Slow);
      if(m_hRSI      != INVALID_HANDLE) IndicatorRelease(m_hRSI);
      if(m_hATR      != INVALID_HANDLE) IndicatorRelease(m_hATR);
      if(m_hBB       != INVALID_HANDLE) IndicatorRelease(m_hBB);
      if(m_hMACD     != INVALID_HANDLE) IndicatorRelease(m_hMACD);
      if(m_hStoch    != INVALID_HANDLE) IndicatorRelease(m_hStoch);
   }
};
//+------------------------------------------------------------------+
