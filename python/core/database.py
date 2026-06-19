"""
Database Models & Async SQLAlchemy Setup
Tables: trades, signals, account_snapshots, news_events, system_logs
"""

from sqlalchemy import (
    Column, Integer, Float, String, Boolean,
    DateTime, Text, ForeignKey, Index
)
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
import logging

from python.core.config import settings

logger = logging.getLogger("database")

Base = declarative_base()

# ---------------------------------------------------------------
# Models
# ---------------------------------------------------------------

class Trade(Base):
    __tablename__ = "trades"
    __table_args__ = (
        Index("ix_trades_symbol_open", "symbol", "open_time"),
        Index("ix_trades_magic", "magic"),
    )

    id          = Column(Integer, primary_key=True, autoincrement=True)
    ticket      = Column(Integer, unique=True, nullable=False)
    symbol      = Column(String(20), nullable=False)
    direction   = Column(String(10), nullable=False)   # BUY / SELL
    open_time   = Column(DateTime, nullable=False)
    close_time  = Column(DateTime)
    open_price  = Column(Float, nullable=False)
    close_price = Column(Float)
    lots        = Column(Float, nullable=False)
    sl          = Column(Float)
    tp          = Column(Float)
    profit      = Column(Float, default=0.0)
    swap        = Column(Float, default=0.0)
    commission  = Column(Float, default=0.0)
    net_profit  = Column(Float, default=0.0)
    status      = Column(String(20), default="OPEN")   # OPEN / CLOSED / PARTIAL
    magic       = Column(Integer, default=0)
    comment     = Column(String(255), default="")
    confidence  = Column(Float, default=0.0)
    regime      = Column(String(30), default="")
    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class Signal(Base):
    __tablename__ = "signals"
    __table_args__ = (
        Index("ix_signals_symbol_time", "symbol", "timestamp"),
    )

    id               = Column(Integer, primary_key=True, autoincrement=True)
    symbol           = Column(String(20), nullable=False)
    direction        = Column(String(10), nullable=False)
    confidence       = Column(Float, nullable=False)
    trend_score      = Column(Float)
    momentum_score   = Column(Float)
    volume_score     = Column(Float)
    liquidity_score  = Column(Float)
    volatility_score = Column(Float)
    regime           = Column(String(30))
    atr              = Column(Float)
    entry_price      = Column(Float)
    stop_loss        = Column(Float)
    take_profit      = Column(Float)
    risk_reward      = Column(Float)
    acted_on         = Column(Boolean, default=False)
    timestamp        = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class AccountSnapshot(Base):
    __tablename__ = "account_snapshots"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    balance     = Column(Float, nullable=False)
    equity      = Column(Float, nullable=False)
    margin_used = Column(Float, default=0.0)
    margin_free = Column(Float, default=0.0)
    open_pnl    = Column(Float, default=0.0)
    daily_pnl   = Column(Float, default=0.0)
    open_trades = Column(Integer, default=0)
    timestamp   = Column(DateTime, default=datetime.utcnow)


class NewsEvent(Base):
    __tablename__ = "news_events"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    title      = Column(String(255), nullable=False)
    currency   = Column(String(10))
    impact     = Column(String(20))   # HIGH / MEDIUM / LOW
    event_time = Column(DateTime, nullable=False)
    actual     = Column(String(50))
    forecast   = Column(String(50))
    previous   = Column(String(50))
    source     = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)


class SystemLog(Base):
    __tablename__ = "system_logs"

    id        = Column(Integer, primary_key=True, autoincrement=True)
    level     = Column(String(10), nullable=False)   # INFO / WARN / ERROR
    module    = Column(String(50))
    message   = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)


class DailyStats(Base):
    __tablename__ = "daily_stats"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    date           = Column(String(10), nullable=False, unique=True)
    total_trades   = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades  = Column(Integer, default=0)
    gross_profit   = Column(Float, default=0.0)
    gross_loss     = Column(Float, default=0.0)
    net_pnl        = Column(Float, default=0.0)
    win_rate       = Column(Float, default=0.0)
    profit_factor  = Column(Float, default=0.0)
    max_drawdown   = Column(Float, default=0.0)
    start_balance  = Column(Float, default=0.0)
    end_balance    = Column(Float, default=0.0)


# ---------------------------------------------------------------
# Engine & Session Factory
# ---------------------------------------------------------------

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_pre_ping=True,
)

AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def init_db():
    """Create all tables on startup."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created/verified")


async def get_db():
    """FastAPI dependency: get async DB session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
