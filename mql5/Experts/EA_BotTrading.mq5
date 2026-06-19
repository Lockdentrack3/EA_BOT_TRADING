//+------------------------------------------------------------------+
//|  EA_BotTrading.mq5                                               |
//|  Institutional-Grade Algorithmic Trading Bot                     |
//|  Architecture: Multi-Factor Signal + AI Scoring + SMC            |
//+------------------------------------------------------------------+
#property copyright "EA_BOT_TRADING"
#property version   "2.00"
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\OrderInfo.mqh>
#include "../Include/SignalEngine.mqh"
#include "../Include/RiskManager.mqh"
#include "../Include/TradeManager.mqh"
#include "../Include/MarketRegime.mqh"
#include "../Include/NewsFilter.mqh"
#include "../Include/Logger.mqh"

//--- Input Parameters
input group "=== RISK MANAGEMENT ==="
input double   InpRiskPercent        = 1.0;    // Max Risk Per Trade (%)
input double   InpMaxDailyLoss       = 3.0;    // Max Daily Loss (%)
input double   InpMaxWeeklyLoss      = 8.0;    // Max Weekly Loss (%)
input int      InpMaxOpenTrades      = 3;      // Max Open Trades
input int      InpMaxCorrelated      = 2;      // Max Correlated Positions
input int      InpMaxConsecLosses    = 3;      // Circuit Breaker: Consecutive Losses

input group "=== SIGNAL ENGINE ==="
input int      InpEMA_Fast           = 50;     // EMA Fast Period
input int      InpEMA_Slow           = 200;    // EMA Slow Period
input int      InpRSI_Period         = 14;     // RSI Period
input int      InpATR_Period         = 14;     // ATR Period
input int      InpBB_Period          = 20;     // Bollinger Bands Period
input double   InpBB_Deviation       = 2.0;    // Bollinger Bands Deviation
input int      InpMACD_Fast          = 12;     // MACD Fast
input int      InpMACD_Slow          = 26;     // MACD Slow
input int      InpMACD_Signal        = 9;      // MACD Signal
input int      InpStoch_K            = 5;      // Stochastic %K
input int      InpStoch_D            = 3;      // Stochastic %D

input group "=== TRADE MANAGEMENT ==="
input double   InpPartialCloseR      = 1.0;    // Partial Close at R-Multiple
input double   InpPartialClosePct    = 50.0;   // Partial Close Percentage (%)
input double   InpTrailingATR        = 1.5;    // Trailing Stop ATR Multiplier
input double   InpBreakEvenATR       = 0.5;    // Break Even ATR Buffer
input double   InpSLMultiplier       = 1.5;    // Stop Loss ATR Multiplier
input double   InpTPMultiplier       = 3.0;    // Take Profit ATR Multiplier

input group "=== AI CONFIDENCE ==="
input double   InpMinConfidence      = 85.0;   // Minimum Trade Confidence (%)

input group "=== NEWS FILTER ==="
input bool     InpUseNewsFilter      = true;   // Enable News Filter
input int      InpNewsMinsBeforeAfter = 30;    // Minutes Before/After News

input group "=== PYTHON BRIDGE ==="
input string   InpPythonAPIURL       = "http://localhost:8000"; // FastAPI URL
input bool     InpUsePythonSignals   = true;   // Use Python AI Signals

input group "=== MAGIC & ID ==="
input long     InpMagicNumber        = 202401; // EA Magic Number
input string   InpEAComment          = "EA_BOT_v2"; // Trade Comment

//--- Global Objects
CTrade         g_trade;
CPositionInfo  g_position;
CSignalEngine  *g_signal;
CRiskManager   *g_risk;
CTradeManager  *g_tradeMgr;
CMarketRegime  *g_regime;
CNewsFilter    *g_news;
CLogger        *g_logger;

//--- State Variables
bool     g_isRunning       = true;
bool     g_circuitBreaker  = false;
int      g_consecLosses    = 0;
double   g_dailyStartBalance = 0;
double   g_weeklyStartBalance = 0;
datetime g_lastDayReset    = 0;
datetime g_lastWeekReset   = 0;
int      g_totalTrades     = 0;
int      g_winningTrades   = 0;

//+------------------------------------------------------------------+
//| Expert initialization                                            |
//+------------------------------------------------------------------+
int OnInit()
{
   Print("=== EA_BOT_TRADING v2.0 Initializing ===");

   // Set trade parameters
   g_trade.SetExpertMagicNumber(InpMagicNumber);
   g_trade.SetDeviationInPoints(10);
   g_trade.SetTypeFilling(ORDER_FILLING_IOC);

   // Initialize subsystems
   g_logger  = new CLogger("EA_BOT_TRADING");
   g_signal  = new CSignalEngine(
      InpEMA_Fast, InpEMA_Slow,
      InpRSI_Period, InpATR_Period,
      InpBB_Period, InpBB_Deviation,
      InpMACD_Fast, InpMACD_Slow, InpMACD_Signal,
      InpStoch_K, InpStoch_D
   );
   g_risk    = new CRiskManager(
      InpRiskPercent, InpMaxDailyLoss, InpMaxWeeklyLoss,
      InpMaxOpenTrades, InpMaxCorrelated, InpMaxConsecLosses,
      InpMagicNumber
   );
   g_tradeMgr = new CTradeManager(
      InpPartialCloseR, InpPartialClosePct,
      InpTrailingATR, InpBreakEvenATR,
      InpMagicNumber, &g_trade
   );
   g_regime  = new CMarketRegime(InpATR_Period, InpEMA_Fast, InpEMA_Slow);
   g_news    = new CNewsFilter(InpNewsMinsBeforeAfter);

   if(!g_signal.Initialize(_Symbol, PERIOD_CURRENT))
   {
      g_logger.Error("Signal Engine initialization failed");
      return INIT_FAILED;
   }
   if(!g_regime.Initialize(_Symbol, PERIOD_CURRENT))
   {
      g_logger.Error("Market Regime initialization failed");
      return INIT_FAILED;
   }

   // Snapshot starting balances
   g_dailyStartBalance  = AccountInfoDouble(ACCOUNT_BALANCE);
   g_weeklyStartBalance = g_dailyStartBalance;
   g_lastDayReset       = TimeCurrent();
   g_lastWeekReset      = TimeCurrent();

   g_logger.Info("EA initialized successfully on " + _Symbol +
                 " | Magic: " + (string)InpMagicNumber);

   EventSetTimer(60); // 1-minute heartbeat
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| Expert deinitialization                                          |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();

   // Cleanup objects
   if(g_signal)   { delete g_signal;   g_signal   = NULL; }
   if(g_risk)     { delete g_risk;     g_risk     = NULL; }
   if(g_tradeMgr) { delete g_tradeMgr; g_tradeMgr = NULL; }
   if(g_regime)   { delete g_regime;   g_regime   = NULL; }
   if(g_news)     { delete g_news;     g_news     = NULL; }
   if(g_logger)   { delete g_logger;   g_logger   = NULL; }

   Print("=== EA_BOT_TRADING Deinitialized | Reason: ", reason, " ===");
}

//+------------------------------------------------------------------+
//| Expert tick function                                             |
//+------------------------------------------------------------------+
void OnTick()
{
   // Fast path: Not running or circuit breaker active
   if(!g_isRunning || g_circuitBreaker) return;

   // Reset daily/weekly trackers
   ResetPeriodicCounters();

   // Update all subsystems
   g_signal.Update();
   g_regime.Update();

   // Manage existing positions first (always)
   g_tradeMgr.ManagePositions();

   // Check if new bar formed (trade only on new bars)
   static datetime lastBarTime = 0;
   datetime currentBarTime = iTime(_Symbol, PERIOD_CURRENT, 0);
   if(currentBarTime == lastBarTime) return;
   lastBarTime = currentBarTime;

   // --- Pre-trade checks ---
   if(InpUseNewsFilter && g_news.IsNewsTime())
   {
      g_logger.Info("News filter active - skipping trade evaluation");
      return;
   }

   if(!g_risk.CanTrade())
   {
      g_logger.Warn("Risk limits reached - trading suspended");
      return;
   }

   // Count open positions for this EA
   int openCount = CountOpenPositions();
   if(openCount >= InpMaxOpenTrades)
   {
      return; // Max positions reached
   }

   // --- Generate Signal ---
   STradeSignal signal;
   if(!g_signal.GenerateSignal(signal))
   {
      return; // No valid signal
   }

   // --- AI Confidence Score ---
   double confidence = CalculateConfidenceScore(signal);
   if(confidence < InpMinConfidence)
   {
      g_logger.Debug(StringFormat("Signal rejected - Confidence: %.1f%% (min: %.1f%%)",
                                   confidence, InpMinConfidence));
      return;
   }

   // --- Market Regime Filter ---
   ENUM_MARKET_REGIME regime = g_regime.GetCurrentRegime();
   if(!IsRegimeFavorable(signal, regime))
   {
      g_logger.Info("Market regime unfavorable for signal direction");
      return;
   }

   // --- Calculate Position Size ---
   double atr        = g_signal.GetATR();
   double slDistance = atr * InpSLMultiplier;
   double lots       = g_risk.CalculateLotSize(_Symbol, slDistance);
   if(lots <= 0)
   {
      g_logger.Error("Invalid lot size calculated");
      return;
   }

   // --- Execute Trade ---
   double entryPrice, slPrice, tpPrice;
   entryPrice = (signal.direction == SIGNAL_BUY) ?
                SymbolInfoDouble(_Symbol, SYMBOL_ASK) :
                SymbolInfoDouble(_Symbol, SYMBOL_BID);

   if(signal.direction == SIGNAL_BUY)
   {
      slPrice = entryPrice - slDistance;
      tpPrice = entryPrice + (atr * InpTPMultiplier);
   }
   else
   {
      slPrice = entryPrice + slDistance;
      tpPrice = entryPrice - (atr * InpTPMultiplier);
   }

   // Normalize prices
   slPrice = NormalizeDouble(slPrice, _Digits);
   tpPrice = NormalizeDouble(tpPrice, _Digits);

   string comment = StringFormat("%s|C:%.0f|R:%s",
                                  InpEAComment, confidence,
                                  EnumToString(regime));

   bool executed = ExecuteTrade(signal.direction, lots, slPrice, tpPrice, comment);
   if(executed)
   {
      g_logger.Info(StringFormat("Trade EXECUTED | %s | Lots:%.2f | SL:%.5f | TP:%.5f | Conf:%.1f%%",
                                  (signal.direction == SIGNAL_BUY ? "BUY" : "SELL"),
                                  lots, slPrice, tpPrice, confidence));
   }
}

//+------------------------------------------------------------------+
//| OnTradeTransaction - track wins/losses                           |
//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &trans,
                         const MqlTradeRequest    &request,
                         const MqlTradeResult     &result)
{
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;

   CDealInfo deal;
   if(!deal.SelectByIndex(HistoryDealGetTicket(0))) return;
   if(deal.Magic() != InpMagicNumber) return;
   if(deal.Entry() != DEAL_ENTRY_OUT) return;

   double profit = deal.Profit() + deal.Swap() + deal.Commission();
   g_totalTrades++;

   if(profit > 0)
   {
      g_winningTrades++;
      g_consecLosses = 0;
      g_logger.Info(StringFormat("WIN | Profit: %.2f | WinRate: %.1f%%",
                                  profit,
                                  (g_totalTrades > 0 ?
                                   (double)g_winningTrades / g_totalTrades * 100.0 : 0)));
   }
   else
   {
      g_consecLosses++;
      g_logger.Warn(StringFormat("LOSS | Profit: %.2f | Consecutive: %d",
                                  profit, g_consecLosses));

      if(g_consecLosses >= InpMaxConsecLosses)
      {
         g_circuitBreaker = true;
         g_logger.Error(StringFormat("CIRCUIT BREAKER TRIGGERED after %d consecutive losses",
                                      g_consecLosses));
      }
   }
}

//+------------------------------------------------------------------+
//| Timer - hourly tasks                                             |
//+------------------------------------------------------------------+
void OnTimer()
{
   // Reset circuit breaker at start of new day
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   if(dt.hour == 0 && dt.min < 2 && g_circuitBreaker)
   {
      g_circuitBreaker = false;
      g_consecLosses   = 0;
      g_logger.Info("Circuit breaker reset at new day start");
   }

   // Log heartbeat
   g_logger.Debug(StringFormat("Heartbeat | Balance:%.2f | Open:%d | CircBreaker:%s",
                                AccountInfoDouble(ACCOUNT_BALANCE),
                                CountOpenPositions(),
                                g_circuitBreaker ? "ON" : "OFF"));
}

//+------------------------------------------------------------------+
//| Calculate composite AI confidence score (0-100)                  |
//+------------------------------------------------------------------+
double CalculateConfidenceScore(const STradeSignal &signal)
{
   double score = 0;

   // Trend Score (30% weight)
   score += signal.trendScore * 0.30;

   // Momentum Score (25% weight)
   score += signal.momentumScore * 0.25;

   // Volume Score (20% weight)
   score += signal.volumeScore * 0.20;

   // Liquidity / SMC Score (15% weight)
   score += signal.liquidityScore * 0.15;

   // Volatility Score (10% weight)
   score += signal.volatilityScore * 0.10;

   return NormalizeDouble(MathMax(0, MathMin(100, score)), 2);
}

//+------------------------------------------------------------------+
//| Check if market regime is favorable for signal                   |
//+------------------------------------------------------------------+
bool IsRegimeFavorable(const STradeSignal &signal, ENUM_MARKET_REGIME regime)
{
   switch(regime)
   {
      case REGIME_TRENDING_UP:
         return (signal.direction == SIGNAL_BUY);
      case REGIME_TRENDING_DOWN:
         return (signal.direction == SIGNAL_SELL);
      case REGIME_RANGING:
         // Reduced confidence requirement in range - handled upstream
         return true;
      case REGIME_HIGH_VOLATILITY:
         return false; // Avoid high volatility regimes
      case REGIME_LOW_VOLATILITY:
         return true;
      default:
         return false;
   }
}

//+------------------------------------------------------------------+
//| Execute a trade order                                            |
//+------------------------------------------------------------------+
bool ExecuteTrade(ENUM_SIGNAL_DIRECTION direction, double lots,
                  double sl, double tp, string comment)
{
   bool result = false;

   if(direction == SIGNAL_BUY)
   {
      result = g_trade.Buy(lots, _Symbol, 0, sl, tp, comment);
   }
   else if(direction == SIGNAL_SELL)
   {
      result = g_trade.Sell(lots, _Symbol, 0, sl, tp, comment);
   }

   if(!result)
   {
      g_logger.Error(StringFormat("Order failed | Error: %d | %s",
                                   g_trade.ResultRetcode(),
                                   g_trade.ResultRetcodeDescription()));
   }

   return result;
}

//+------------------------------------------------------------------+
//| Count open positions for this EA                                 |
//+------------------------------------------------------------------+
int CountOpenPositions()
{
   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(g_position.SelectByIndex(i))
      {
         if(g_position.Magic() == InpMagicNumber &&
            g_position.Symbol() == _Symbol)
            count++;
      }
   }
   return count;
}

//+------------------------------------------------------------------+
//| Reset daily/weekly balance counters                              |
//+------------------------------------------------------------------+
void ResetPeriodicCounters()
{
   datetime now = TimeCurrent();
   MqlDateTime dtNow, dtLast;
   TimeToStruct(now, dtNow);
   TimeToStruct(g_lastDayReset, dtLast);

   // Daily reset
   if(dtNow.day != dtLast.day)
   {
      g_dailyStartBalance = AccountInfoDouble(ACCOUNT_BALANCE);
      g_lastDayReset      = now;
      g_logger.Info(StringFormat("Daily reset | New balance snapshot: %.2f", g_dailyStartBalance));
   }

   // Weekly reset (Monday)
   if(dtNow.day_of_week == 1 && dtLast.day_of_week != 1)
   {
      g_weeklyStartBalance = AccountInfoDouble(ACCOUNT_BALANCE);
      g_lastWeekReset      = now;
      g_logger.Info(StringFormat("Weekly reset | New balance snapshot: %.2f", g_weeklyStartBalance));
   }
}
//+------------------------------------------------------------------+
