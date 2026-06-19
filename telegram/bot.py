"""
Telegram Bot Integration
Full command panel + real-time trade notifications.
Commands: /status /start /stop /profit /loss /opentrades /performance
"""

import logging
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any
from functools import wraps

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.constants import ParseMode

logger = logging.getLogger("telegram_bot")


# ---------------------------------------------------------------
# Auth decorator: restrict to admin IDs
# ---------------------------------------------------------------
def admin_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        admin_ids = context.bot_data.get("admin_ids", [])
        if admin_ids and user_id not in admin_ids:
            await update.message.reply_text("⛔ Unauthorized access.")
            return
        return await func(update, context)
    return wrapper


# ---------------------------------------------------------------
# Bot State (shared across handlers)
# ---------------------------------------------------------------
class BotState:
    is_running: bool       = True
    circuit_breaker: bool  = False
    start_time: datetime   = datetime.utcnow()
    trade_stats: Dict      = {}
    open_trades: list      = []
    account_info: Dict     = {}


state = BotState()


# ---------------------------------------------------------------
# Helper: format currency
# ---------------------------------------------------------------
def fmt(v: float, decimals: int = 2) -> str:
    sign = "+" if v > 0 else ""
    return f"{sign}{v:,.{decimals}f}"


def emoji_profit(v: float) -> str:
    return "🟢" if v >= 0 else "🔴"


# ---------------------------------------------------------------
# Commands
# ---------------------------------------------------------------

async def cmd_start_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enable trading."""
    state.is_running = True
    await update.message.reply_text(
        "✅ *Trading ENABLED*\nBot is now accepting new signals.",
        parse_mode=ParseMode.MARKDOWN,
    )
    logger.info(f"Trading enabled by {update.effective_user.username}")


async def cmd_stop_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Disable trading (keeps positions open)."""
    state.is_running = False
    await update.message.reply_text(
        "🛑 *Trading DISABLED*\nNo new trades will be opened.\nExisting positions are still managed.",
        parse_mode=ParseMode.MARKDOWN,
    )
    logger.info(f"Trading disabled by {update.effective_user.username}")


@admin_only
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    acc   = state.account_info
    uptime = str(datetime.utcnow() - state.start_time).split(".")[0]

    text = (
        "📊 *EA BOT TRADING — Status*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{'🟢' if state.is_running else '🔴'} Trading: `{'ACTIVE' if state.is_running else 'PAUSED'}`\n"
        f"{'🔴' if state.circuit_breaker else '🟢'} Circuit Breaker: `{'ON' if state.circuit_breaker else 'OFF'}`\n"
        f"⏱ Uptime: `{uptime}`\n\n"
        f"💰 Balance:   `{acc.get('balance', 0):,.2f}`\n"
        f"📈 Equity:    `{acc.get('equity', 0):,.2f}`\n"
        f"🔓 Free Margin: `{acc.get('margin_free', 0):,.2f}`\n\n"
        f"📂 Open Trades: `{len(state.open_trades)}`\n"
        f"🕐 Server Time: `{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC`\n"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="refresh_status"),
         InlineKeyboardButton("📊 Performance", callback_data="performance")],
        [InlineKeyboardButton("📂 Open Trades", callback_data="open_trades"),
         InlineKeyboardButton("🛑 Stop Trading", callback_data="stop_trading")],
    ])

    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN,
                                     reply_markup=keyboard)


@admin_only
async def cmd_profit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = state.trade_stats
    total_profit = stats.get("total_pnl", 0)

    text = (
        "💵 *Profit Summary*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Today:    `{fmt(stats.get('daily_pnl', 0))}`\n"
        f"This Week: `{fmt(stats.get('weekly_pnl', 0))}`\n"
        f"This Month: `{fmt(stats.get('monthly_pnl', 0))}`\n"
        f"All Time: `{fmt(total_profit)}`\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


@admin_only
async def cmd_loss(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = state.trade_stats

    text = (
        "⚠️ *Loss Summary*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Daily Loss:    `{fmt(stats.get('daily_loss', 0))}`\n"
        f"Weekly Loss:   `{fmt(stats.get('weekly_loss', 0))}`\n"
        f"Max Drawdown:  `{stats.get('max_drawdown', 0):.2f}%`\n"
        f"Consec Losses: `{stats.get('consecutive_losses', 0)}`\n"
        f"Circuit Breaker: `{'🔴 ACTIVE' if state.circuit_breaker else '🟢 OFF'}`\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


@admin_only
async def cmd_open_trades(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not state.open_trades:
        await update.message.reply_text("📂 No open trades currently.")
        return

    text = "📂 *Open Trades*\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for i, t in enumerate(state.open_trades, 1):
        pnl = t.get("pnl", 0)
        text += (
            f"*{i}. {t.get('symbol')}* `{t.get('direction')}`\n"
            f"   Entry: `{t.get('open_price', 0):.5f}`\n"
            f"   SL: `{t.get('sl', 0):.5f}` | TP: `{t.get('tp', 0):.5f}`\n"
            f"   Lots: `{t.get('lots', 0):.2f}` | PnL: `{emoji_profit(pnl)} {fmt(pnl)}`\n\n"
        )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


@admin_only
async def cmd_performance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = state.trade_stats

    text = (
        "📈 *Performance Report*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Total Trades:    `{stats.get('total_trades', 0)}`\n"
        f"Win Rate:        `{stats.get('win_rate', 0):.1f}%`\n"
        f"Profit Factor:   `{stats.get('profit_factor', 0):.2f}`\n"
        f"Sharpe Ratio:    `{stats.get('sharpe_ratio', 0):.3f}`\n"
        f"Sortino Ratio:   `{stats.get('sortino_ratio', 0):.3f}`\n"
        f"Max Drawdown:    `{stats.get('max_drawdown', 0):.2f}%`\n"
        f"Avg Win:         `{fmt(stats.get('avg_win', 0))}`\n"
        f"Avg Loss:        `{fmt(stats.get('avg_loss', 0))}`\n"
        f"Risk/Reward:     `{stats.get('rr_ratio', 0):.2f}`\n"
        f"Expectancy:      `{fmt(stats.get('expectancy', 0))}`\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🤖 *EA BOT TRADING — Commands*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "/status      — Full system status\n"
        "/start       — Enable trading\n"
        "/stop        — Pause trading\n"
        "/profit      — Show profit summary\n"
        "/loss        — Show loss & drawdown\n"
        "/opentrades  — List open positions\n"
        "/performance — Full analytics report\n"
        "/help        — Show this message\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# ---------------------------------------------------------------
# Callback Query Handlers
# ---------------------------------------------------------------

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "refresh_status":
        await cmd_status(update, context)
    elif query.data == "performance":
        await cmd_performance(update, context)
    elif query.data == "open_trades":
        await cmd_open_trades(update, context)
    elif query.data == "stop_trading":
        state.is_running = False
        await query.edit_message_text("🛑 Trading has been paused via panel.")


# ---------------------------------------------------------------
# Notification Sender (call from trade logic)
# ---------------------------------------------------------------

class TelegramNotifier:
    """
    Send real-time notifications to the Telegram channel.
    """

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id   = chat_id
        self._app: Optional[Application] = None

    async def send(self, message: str):
        if not self.bot_token or not self.chat_id:
            return
        try:
            from telegram import Bot
            bot = Bot(token=self.bot_token)
            await bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")

    async def notify_entry(self, symbol: str, direction: str, lots: float,
                            entry: float, sl: float, tp: float,
                            confidence: float, regime: str):
        rr = abs(tp - entry) / abs(sl - entry) if abs(sl - entry) > 0 else 0
        emoji = "🟢📈" if direction == "BUY" else "🔴📉"
        msg = (
            f"{emoji} *TRADE OPENED*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Symbol:     `{symbol}`\n"
            f"Direction:  `{direction}`\n"
            f"Lots:       `{lots:.2f}`\n"
            f"Entry:      `{entry:.5f}`\n"
            f"Stop Loss:  `{sl:.5f}`\n"
            f"Take Profit: `{tp:.5f}`\n"
            f"R:R:        `1:{rr:.1f}`\n"
            f"Confidence: `{confidence:.1f}%`\n"
            f"Regime:     `{regime}`\n"
            f"⏱ `{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC`"
        )
        await self.send(msg)

    async def notify_exit(self, symbol: str, direction: str, lots: float,
                           entry: float, exit_price: float, profit: float,
                           reason: str):
        emoji = "✅" if profit >= 0 else "❌"
        pnl_emoji = "💵" if profit >= 0 else "💸"
        msg = (
            f"{emoji} *TRADE CLOSED*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Symbol:    `{symbol}`\n"
            f"Direction: `{direction}`\n"
            f"Lots:      `{lots:.2f}`\n"
            f"Entry:     `{entry:.5f}`\n"
            f"Exit:      `{exit_price:.5f}`\n"
            f"{pnl_emoji} PnL:      `{fmt(profit)}`\n"
            f"Reason:    `{reason}`\n"
            f"⏱ `{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC`"
        )
        await self.send(msg)

    async def notify_circuit_breaker(self, consecutive_losses: int):
        msg = (
            "🚨 *CIRCUIT BREAKER ACTIVATED*\n"
            f"Trading paused after `{consecutive_losses}` consecutive losses.\n"
            "Will auto-reset at start of next trading day.\n"
            "Use /status to check current state."
        )
        await self.send(msg)

    async def notify_error(self, error: str):
        msg = f"⚠️ *SYSTEM ERROR*\n```\n{error}\n```"
        await self.send(msg)

    async def notify_daily_summary(self, stats: dict):
        pnl = stats.get("daily_pnl", 0)
        emoji = "🟢" if pnl >= 0 else "🔴"
        msg = (
            f"{emoji} *Daily Summary*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Trades Today:  `{stats.get('daily_trades', 0)}`\n"
            f"Win Rate:      `{stats.get('daily_wr', 0):.1f}%`\n"
            f"Daily PnL:     `{fmt(pnl)}`\n"
            f"Max Drawdown:  `{stats.get('max_dd', 0):.2f}%`\n"
            f"Date: `{datetime.utcnow().strftime('%Y-%m-%d')}`"
        )
        await self.send(msg)


# ---------------------------------------------------------------
# Bot Application Builder
# ---------------------------------------------------------------

def build_bot(token: str, admin_ids: list) -> Application:
    """Build and configure the Telegram bot application."""
    app = Application.builder().token(token).build()
    app.bot_data["admin_ids"] = admin_ids

    # Command handlers
    app.add_handler(CommandHandler("start",       cmd_start_bot))
    app.add_handler(CommandHandler("stop",        cmd_stop_bot))
    app.add_handler(CommandHandler("status",      cmd_status))
    app.add_handler(CommandHandler("profit",      cmd_profit))
    app.add_handler(CommandHandler("loss",        cmd_loss))
    app.add_handler(CommandHandler("opentrades",  cmd_open_trades))
    app.add_handler(CommandHandler("performance", cmd_performance))
    app.add_handler(CommandHandler("help",        cmd_help))

    # Callback handler
    app.add_handler(CallbackQueryHandler(callback_handler))

    # Unknown command
    app.add_handler(MessageHandler(
        filters.COMMAND,
        lambda u, c: u.message.reply_text("❓ Unknown command. Use /help")
    ))

    return app
