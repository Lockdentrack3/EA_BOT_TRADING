//+------------------------------------------------------------------+
//|  MarketRegime.mqh                                                |
//|  Market Regime Detection: Trending / Ranging / Volatile          |
//+------------------------------------------------------------------+
#pragma once

enum ENUM_MARKET_REGIME
{
   REGIME_UNDEFINED      = 0,
   REGIME_TRENDING_UP    = 1,
   REGIME_TRENDING_DOWN  = 2,
   REGIME_RANGING        = 3,
   REGIME_HIGH_VOLATILITY = 4,
   REGIME_LOW_VOLATILITY  = 5
};

class CMarketRegime
{
private:
   int    m_atrPeriod;
   int    m_emaFast;
   int    m_emaSlow;
   int    m_hATR, m_hEMAFast, m_hEMASlow;
   string m_symbol;
   ENUM_TIMEFRAMES m_tf;
   ENUM_MARKET_REGIME m_current;

public:
   CMarketRegime(int atrPeriod, int emaFast, int emaSlow)
   {
      m_atrPeriod = atrPeriod;
      m_emaFast   = emaFast;
      m_emaSlow   = emaSlow;
      m_current   = REGIME_UNDEFINED;
      m_hATR = m_hEMAFast = m_hEMASlow = INVALID_HANDLE;
   }

   ~CMarketRegime()
   {
      if(m_hATR     != INVALID_HANDLE) IndicatorRelease(m_hATR);
      if(m_hEMAFast != INVALID_HANDLE) IndicatorRelease(m_hEMAFast);
      if(m_hEMASlow != INVALID_HANDLE) IndicatorRelease(m_hEMASlow);
   }

   bool Initialize(string symbol, ENUM_TIMEFRAMES tf)
   {
      m_symbol = symbol;
      m_tf     = tf;
      m_hATR     = iATR(symbol, tf, m_atrPeriod);
      m_hEMAFast = iMA(symbol, tf, m_emaFast, 0, MODE_EMA, PRICE_CLOSE);
      m_hEMASlow = iMA(symbol, tf, m_emaSlow, 0, MODE_EMA, PRICE_CLOSE);
      return (m_hATR != INVALID_HANDLE &&
              m_hEMAFast != INVALID_HANDLE &&
              m_hEMASlow != INVALID_HANDLE);
   }

   void Update()
   {
      double atr[5], emaFast[3], emaSlow[3];
      if(CopyBuffer(m_hATR,     0, 0, 5, atr)     < 5) return;
      if(CopyBuffer(m_hEMAFast, 0, 0, 3, emaFast) < 3) return;
      if(CopyBuffer(m_hEMASlow, 0, 0, 3, emaSlow) < 3) return;

      double avgATR = 0;
      for(int i = 1; i < 5; i++) avgATR += atr[i];
      avgATR /= 4.0;

      double currentATR = atr[1];
      double atrRatio   = (avgATR > 0) ? currentATR / avgATR : 1.0;

      // High volatility detection
      if(atrRatio > 1.8)
      {
         m_current = REGIME_HIGH_VOLATILITY;
         return;
      }

      // Low volatility detection
      if(atrRatio < 0.6)
      {
         m_current = REGIME_LOW_VOLATILITY;
         return;
      }

      // Trending or Ranging based on EMA spread
      double emaSpread = MathAbs(emaFast[1] - emaSlow[1]);
      double spreadPct = (emaSlow[1] > 0) ? emaSpread / emaSlow[1] * 100.0 : 0;

      if(spreadPct > 0.15) // EMAs diverged - trending
      {
         m_current = (emaFast[1] > emaSlow[1]) ?
                     REGIME_TRENDING_UP : REGIME_TRENDING_DOWN;
      }
      else
      {
         m_current = REGIME_RANGING;
      }
   }

   ENUM_MARKET_REGIME GetCurrentRegime() const { return m_current; }

   string RegimeToString() const
   {
      switch(m_current)
      {
         case REGIME_TRENDING_UP:    return "TREND_UP";
         case REGIME_TRENDING_DOWN:  return "TREND_DOWN";
         case REGIME_RANGING:        return "RANGING";
         case REGIME_HIGH_VOLATILITY: return "HIGH_VOL";
         case REGIME_LOW_VOLATILITY:  return "LOW_VOL";
         default:                    return "UNDEFINED";
      }
   }
};

//+------------------------------------------------------------------+
//|  NewsFilter.mqh                                                  |
//|  High-Impact News Avoidance Filter                               |
//+------------------------------------------------------------------+
class CNewsFilter
{
private:
   int m_minsBuffer;

public:
   CNewsFilter(int minsBuffer) { m_minsBuffer = minsBuffer; }

   //--- Check if current time is within news window
   //--- Note: Full implementation requires calendar API or external feed
   bool IsNewsTime()
   {
      // Check MQL5 Calendar events
      MqlCalendarValue values[];
      datetime fromTime = TimeCurrent() - (m_minsBuffer * 60);
      datetime toTime   = TimeCurrent() + (m_minsBuffer * 60);

      int count = CalendarValueHistory(values, fromTime, toTime);
      if(count <= 0) return false;

      for(int i = 0; i < count; i++)
      {
         MqlCalendarEvent event;
         if(!CalendarEventById(values[i].event_id, event)) continue;

         // Only block high-impact events
         if(event.importance == CALENDAR_IMPORTANCE_HIGH)
         {
            Print("NewsFilter: High-impact event detected: ", event.name,
                  " at ", TimeToString(values[i].time));
            return true;
         }
      }
      return false;
   }
};

//+------------------------------------------------------------------+
//|  Logger.mqh                                                      |
//|  Structured Logging System                                       |
//+------------------------------------------------------------------+
class CLogger
{
private:
   string m_name;

   void Log(string level, string msg)
   {
      string line = StringFormat("[%s][%s] %s: %s",
                                  TimeToString(TimeCurrent(), TIME_DATE|TIME_SECONDS),
                                  level, m_name, msg);
      Print(line);
   }

public:
   CLogger(string name) { m_name = name; }

   void Debug(string msg) { Log("DEBUG", msg); }
   void Info(string msg)  { Log("INFO",  msg); }
   void Warn(string msg)  { Log("WARN",  msg); }
   void Error(string msg) { Log("ERROR", msg); }
};
//+------------------------------------------------------------------+
