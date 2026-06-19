//+------------------------------------------------------------------+
//|  RiskManager.mqh                                                 |
//|  Institutional Risk Management Module                            |
//+------------------------------------------------------------------+
#pragma once

class CRiskManager
{
private:
   double m_riskPct;
   double m_maxDailyLoss;
   double m_maxWeeklyLoss;
   int    m_maxOpenTrades;
   int    m_maxCorrelated;
   int    m_maxConsecLoss;
   long   m_magic;

   double m_dailyStartBal;
   double m_weeklyStartBal;

public:
   CRiskManager(double riskPct, double maxDailyLoss, double maxWeeklyLoss,
                 int maxOpen, int maxCorrel, int maxConsec, long magic)
   {
      m_riskPct       = riskPct;
      m_maxDailyLoss  = maxDailyLoss;
      m_maxWeeklyLoss = maxWeeklyLoss;
      m_maxOpenTrades = maxOpen;
      m_maxCorrelated = maxCorrel;
      m_maxConsecLoss = maxConsec;
      m_magic         = magic;

      m_dailyStartBal  = AccountInfoDouble(ACCOUNT_BALANCE);
      m_weeklyStartBal = m_dailyStartBal;
   }

   //--- Calculate lot size based on account balance and SL distance
   double CalculateLotSize(string symbol, double slPoints)
   {
      if(slPoints <= 0) return 0;

      double balance    = AccountInfoDouble(ACCOUNT_BALANCE);
      double riskAmount = balance * (m_riskPct / 100.0);

      double tickValue  = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE);
      double tickSize   = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
      double minLot     = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
      double maxLot     = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
      double lotStep    = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);

      if(tickValue == 0 || tickSize == 0) return 0;

      double slTicks    = slPoints / tickSize;
      double lots       = riskAmount / (slTicks * tickValue);

      // Normalize to allowed lot step
      lots = MathFloor(lots / lotStep) * lotStep;
      lots = MathMax(minLot, MathMin(maxLot, lots));

      return NormalizeDouble(lots, 2);
   }

   //--- Check if trading is permitted under risk rules
   bool CanTrade()
   {
      double balance  = AccountInfoDouble(ACCOUNT_BALANCE);
      double equity   = AccountInfoDouble(ACCOUNT_EQUITY);

      // Daily loss check
      double dailyLoss = (m_dailyStartBal - equity) / m_dailyStartBal * 100.0;
      if(dailyLoss >= m_maxDailyLoss)
      {
         Print("RiskManager: Daily loss limit hit: ", DoubleToString(dailyLoss, 2), "%");
         return false;
      }

      // Weekly loss check
      double weeklyLoss = (m_weeklyStartBal - equity) / m_weeklyStartBal * 100.0;
      if(weeklyLoss >= m_maxWeeklyLoss)
      {
         Print("RiskManager: Weekly loss limit hit: ", DoubleToString(weeklyLoss, 2), "%");
         return false;
      }

      return true;
   }

   //--- Update daily start balance (call at daily reset)
   void SetDailyStartBalance(double bal)  { m_dailyStartBal  = bal; }
   void SetWeeklyStartBalance(double bal) { m_weeklyStartBal = bal; }

   double GetMaxRiskPct()       const { return m_riskPct; }
   double GetMaxDailyLoss()     const { return m_maxDailyLoss; }
   double GetMaxWeeklyLoss()    const { return m_maxWeeklyLoss; }
};
//+------------------------------------------------------------------+
