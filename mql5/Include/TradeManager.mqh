//+------------------------------------------------------------------+
//|  TradeManager.mqh                                                |
//|  Automated Trade Management: BE, Trailing Stop, Partial Close    |
//+------------------------------------------------------------------+
#pragma once
#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>

class CTradeManager
{
private:
   double   m_partialR;        // R-multiple to trigger partial close
   double   m_partialPct;      // % of position to close partially
   double   m_trailATR;        // ATR multiplier for trailing stop
   double   m_beATR;           // ATR multiplier for break-even buffer
   long     m_magic;
   CTrade  *m_trade;
   CPositionInfo m_pos;

public:
   CTradeManager(double partialR, double partialPct, double trailATR,
                  double beATR, long magic, CTrade *trade)
   {
      m_partialR   = partialR;
      m_partialPct = partialPct;
      m_trailATR   = trailATR;
      m_beATR      = beATR;
      m_magic      = magic;
      m_trade      = trade;
   }

   //--- Called every tick to manage all open positions
   void ManagePositions()
   {
      int hATR = iATR(_Symbol, PERIOD_CURRENT, 14);
      double atrBuf[1];
      if(CopyBuffer(hATR, 0, 1, 1, atrBuf) <= 0) return;
      double atr = atrBuf[0];

      for(int i = PositionsTotal() - 1; i >= 0; i--)
      {
         if(!m_pos.SelectByIndex(i)) continue;
         if(m_pos.Magic() != m_magic) continue;

         double entryPrice = m_pos.PriceOpen();
         double currentSL  = m_pos.StopLoss();
         double currentTP  = m_pos.TakeProfit();
         double bid        = SymbolInfoDouble(m_pos.Symbol(), SYMBOL_BID);
         double ask        = SymbolInfoDouble(m_pos.Symbol(), SYMBOL_ASK);
         ulong  ticket     = m_pos.Ticket();

         bool isBuy = (m_pos.PositionType() == POSITION_TYPE_BUY);

         // --- Break Even Management ---
         double beLevel = isBuy ?
                          entryPrice + (atr * m_beATR) :
                          entryPrice - (atr * m_beATR);

         bool pricePassedBE = isBuy ? (bid > beLevel) : (ask < beLevel);

         if(pricePassedBE)
         {
            double newSL = isBuy ?
                           entryPrice + (_Point * 2) :
                           entryPrice - (_Point * 2);

            newSL = NormalizeDouble(newSL, _Digits);

            // Only update if SL would improve
            bool shouldMoveBE = isBuy  ? (newSL > currentSL || currentSL == 0) :
                                          (newSL < currentSL || currentSL == 0);

            if(shouldMoveBE && MathAbs(newSL - currentSL) > _Point)
            {
               if(m_trade.PositionModify(ticket, newSL, currentTP))
                  Print("TradeManager: Break-even set for ticket ", ticket);
            }
         }

         // --- Trailing Stop Management ---
         double trailDistance = atr * m_trailATR;
         double trailSL;

         if(isBuy)
         {
            trailSL = NormalizeDouble(bid - trailDistance, _Digits);
            if(trailSL > currentSL && trailSL > entryPrice)
            {
               if(m_trade.PositionModify(ticket, trailSL, currentTP))
                  Print("TradeManager: Trail stop updated to ", trailSL, " | ticket ", ticket);
            }
         }
         else
         {
            trailSL = NormalizeDouble(ask + trailDistance, _Digits);
            if((trailSL < currentSL || currentSL == 0) && trailSL < entryPrice)
            {
               if(m_trade.PositionModify(ticket, trailSL, currentTP))
                  Print("TradeManager: Trail stop updated to ", trailSL, " | ticket ", ticket);
            }
         }

         // --- Partial Close at 1R ---
         CheckPartialClose(ticket, isBuy, entryPrice, bid, ask, atr);
      }

      IndicatorRelease(hATR);
   }

private:
   // Track which tickets have already been partially closed
   ulong m_partialClosed[100];
   int   m_partialCount = 0;

   bool AlreadyPartiallyClosed(ulong ticket)
   {
      for(int i = 0; i < m_partialCount; i++)
         if(m_partialClosed[i] == ticket) return true;
      return false;
   }

   void MarkPartiallyClosed(ulong ticket)
   {
      if(m_partialCount < 100)
         m_partialClosed[m_partialCount++] = ticket;
   }

   void CheckPartialClose(ulong ticket, bool isBuy, double entry,
                           double bid, double ask, double atr)
   {
      if(AlreadyPartiallyClosed(ticket)) return;

      double initialSLDist = atr * 1.5; // Assumed SL distance
      double targetProfit  = initialSLDist * m_partialR;

      bool triggered = isBuy ?
                       (bid >= entry + targetProfit) :
                       (ask <= entry - targetProfit);

      if(!triggered) return;

      if(!m_pos.SelectByTicket(ticket)) return;

      double closeVol = NormalizeDouble(m_pos.Volume() * (m_partialPct / 100.0), 2);
      double minLot   = SymbolInfoDouble(m_pos.Symbol(), SYMBOL_VOLUME_MIN);
      if(closeVol < minLot) closeVol = minLot;
      if(closeVol >= m_pos.Volume()) return; // Don't full close here

      if(m_trade.PositionClosePartial(ticket, closeVol))
      {
         Print("TradeManager: Partial close ", closeVol, " lots at 1R | ticket ", ticket);
         MarkPartiallyClosed(ticket);
      }
   }
};
//+------------------------------------------------------------------+
