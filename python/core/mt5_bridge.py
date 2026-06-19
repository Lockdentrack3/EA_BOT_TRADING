"""
MT5 Bridge — MetaTrader 5 ↔ FastAPI Connector
Polls MT5 for account data, syncs trades, pushes signals back.
Run this on the same Windows machine as MetaTrader 5.
"""

import MetaTrader5 as mt5
import httpx
import asyncio
import logging
import json
from datetime import datetime, timezone
from typing import List, Dict, Optional

logging.basicConfig(level=logging.INFO,
                    format="[%(asctime)s][%(levelname)s] %(message)s")
logger = logging.getLogger("mt5_bridge")

API_URL     = "http://localhost:8000/api/v1"
MAGIC       = 202401
POLL_SECS   = 5
SYMBOLS     = ["EURUSD", "GBPUSD", "XAUUSD", "USDJPY", "NAS100"]
TIMEFRAME   = mt5.TIMEFRAME_H1
BARS        = 300


class MT5Bridge:
    def __init__(self, account: int, password: str, server: str):
        self.account  = account
        self.password = password
        self.server   = server
        self.client   = httpx.AsyncClient(base_url=API_URL, timeout=10.0)
        self._known_tickets: set = set()

    async def connect(self) -> bool:
        if not mt5.initialize():
            logger.error(f"MT5 init failed: {mt5.last_error()}")
            return False
        if not mt5.login(self.account, self.password, self.server):
            logger.error(f"MT5 login failed: {mt5.last_error()}")
            return False
        info = mt5.account_info()
        logger.info(f"MT5 Connected | Account: {info.login} | Balance: {info.balance:.2f}")
        return True

    async def run(self):
        if not await self.connect():
            return

        logger.info("MT5 Bridge running...")
        while True:
            try:
                await self.sync_account()
                await self.sync_closed_trades()
                await self.process_signals()
            except Exception as e:
                logger.error(f"Bridge error: {e}")
            await asyncio.sleep(POLL_SECS)

    async def sync_account(self):
        info = mt5.account_info()
        if info is None:
            return
        open_trades = len([p for p in mt5.positions_get() or [] if p.magic == MAGIC])
        try:
            await self.client.post("/analytics/account_snapshot", json={
                "balance":     info.balance,
                "equity":      info.equity,
                "margin_used": info.margin,
                "margin_free": info.margin_free,
                "open_pnl":    info.profit,
                "daily_pnl":   0.0,
                "open_trades": open_trades,
            })
        except Exception as e:
            logger.debug(f"Account sync error: {e}")

    async def sync_closed_trades(self):
        """Push newly closed trades to the API."""
        from datetime import timedelta
        now   = datetime.now(timezone.utc)
        from_ = now - timedelta(hours=24)

        deals = mt5.history_deals_get(from_, now)
        if not deals:
            return

        for deal in deals:
            if deal.magic != MAGIC:
                continue
            if deal.entry != mt5.DEAL_ENTRY_OUT:
                continue
            if deal.ticket in self._known_tickets:
                continue

            self._known_tickets.add(deal.ticket)
            try:
                await self.client.put(f"/analytics/trades/{deal.order}/close", json={
                    "ticket":      deal.ticket,
                    "close_time":  datetime.fromtimestamp(deal.time).isoformat(),
                    "close_price": deal.price,
                    "profit":      deal.profit,
                    "swap":        deal.swap,
                    "commission":  deal.commission,
                })
                logger.info(f"Trade closed synced | Ticket: {deal.ticket} | P&L: {deal.profit:.2f}")
            except Exception as e:
                logger.debug(f"Trade close sync error: {e}")

    async def process_signals(self):
        """Fetch OHLCV for each symbol and request signals from API."""
        account_info = mt5.account_info()
        if account_info is None:
            return

        open_positions = [p.symbol for p in (mt5.positions_get() or [])
                          if p.magic == MAGIC]

        for symbol in SYMBOLS:
            try:
                rates = mt5.copy_rates_from_pos(symbol, TIMEFRAME, 0, BARS)
                if rates is None or len(rates) < 50:
                    continue

                import pandas as pd
                df = pd.DataFrame(rates)
                df.rename(columns={"tick_volume": "volume"}, inplace=True)
                ohlcv = df[["open", "high", "low", "close", "volume"]].to_dict("records")

                tick = mt5.symbol_info_tick(symbol)
                if tick is None:
                    continue

                current_price = (tick.bid + tick.ask) / 2

                # Risk check first
                risk_resp = await self.client.post("/risk/check", json={
                    "symbol":       symbol,
                    "balance":      account_info.balance,
                    "equity":       account_info.equity,
                    "open_symbols": open_positions,
                    "sl_distance":  0.001,  # Will be refined after signal
                })

                if risk_resp.status_code == 200:
                    risk_data = risk_resp.json()
                    if not risk_data.get("allowed"):
                        logger.debug(f"{symbol}: Risk check failed — {risk_data.get('reason')}")
                        continue

                # Get signal
                sig_resp = await self.client.post("/signals/generate", json={
                    "symbol":       symbol,
                    "ohlcv":        ohlcv,
                    "current_price": current_price,
                })

                if sig_resp.status_code != 200:
                    continue

                sig_data = sig_resp.json()
                signal   = sig_data.get("signal")

                if signal is None:
                    continue

                logger.info(f"Signal: {symbol} {signal['direction']} | "
                             f"Conf: {signal['confidence']}% | "
                             f"RR: {signal['risk_reward']}")

                # Execute trade in MT5
                await self.execute_trade(symbol, signal, account_info.balance,
                                          open_positions)

            except Exception as e:
                logger.error(f"Signal processing error for {symbol}: {e}")

    async def execute_trade(self, symbol: str, signal: dict,
                             balance: float, open_positions: List[str]):
        direction = signal["direction"]
        sl_price  = signal["stop_loss"]
        tp_price  = signal["take_profit"]
        entry     = signal["entry_price"]

        # Calculate SL distance for lot sizing
        sl_dist = abs(entry - sl_price)

        # Re-check risk with proper SL distance
        risk_resp = await self.client.post("/risk/check", json={
            "symbol":       symbol,
            "balance":      balance,
            "equity":       balance,
            "open_symbols": open_positions,
            "sl_distance":  sl_dist,
        })

        if risk_resp.status_code != 200:
            return

        risk_data = risk_resp.json()
        if not risk_data.get("allowed"):
            return

        lots = risk_data.get("max_lots", 0.01)

        order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
        price      = mt5.symbol_info_tick(symbol).ask if direction == "BUY" \
                     else mt5.symbol_info_tick(symbol).bid

        request = {
            "action":    mt5.TRADE_ACTION_DEAL,
            "symbol":    symbol,
            "volume":    lots,
            "type":      order_type,
            "price":     price,
            "sl":        sl_price,
            "tp":        tp_price,
            "deviation": 10,
            "magic":     MAGIC,
            "comment":   f"EA_BOT|C:{signal['confidence']:.0f}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"Order failed | {symbol} | retcode: {result.retcode if result else 'None'}")
            return

        ticket = result.order
        logger.info(f"ORDER PLACED | {symbol} {direction} {lots:.2f} lots | Ticket: {ticket}")

        # Record in API
        try:
            await self.client.post("/analytics/trades", json={
                "ticket":      ticket,
                "symbol":      symbol,
                "direction":   direction,
                "open_time":   datetime.utcnow().isoformat(),
                "open_price":  price,
                "lots":        lots,
                "sl":          sl_price,
                "tp":          tp_price,
                "magic":       MAGIC,
                "confidence":  signal["confidence"],
                "regime":      signal["regime"],
                "comment":     f"EA_BOT|C:{signal['confidence']:.0f}",
            })
        except Exception as e:
            logger.error(f"Trade record error: {e}")


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()

    bridge = MT5Bridge(
        account=int(os.getenv("MT5_ACCOUNT", "0")),
        password=os.getenv("MT5_PASSWORD", ""),
        server=os.getenv("MT5_SERVER", ""),
    )
    asyncio.run(bridge.run())
