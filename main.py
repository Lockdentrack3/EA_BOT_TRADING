"""
EA_BOT_TRADING - FastAPI Backend Server
Institutional-grade trading bot Python bridge
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn
import asyncio
import logging
from datetime import datetime
from contextlib import asynccontextmanager

from python.api.routes import (
    signals_router,
    risk_router,
    analytics_router,
    telegram_router,
    backtest_router,
)
from python.core.database import init_db
from python.core.config import settings
from python.core.scheduler import TaskScheduler
from python.utils.logger import setup_logger

logger = setup_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown."""
    logger.info("=== EA_BOT_TRADING Backend Starting ===")

    # Initialize database
    await init_db()
    logger.info("Database initialized")

    # Start background scheduler
    scheduler = TaskScheduler()
    await scheduler.start()
    app.state.scheduler = scheduler
    logger.info("Task scheduler started")

    yield

    # Shutdown
    await scheduler.stop()
    logger.info("=== EA_BOT_TRADING Backend Stopped ===")


app = FastAPI(
    title="EA_BOT_TRADING API",
    description="Institutional-grade algorithmic trading system backend",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(signals_router,   prefix="/api/v1/signals",   tags=["Signals"])
app.include_router(risk_router,      prefix="/api/v1/risk",       tags=["Risk"])
app.include_router(analytics_router, prefix="/api/v1/analytics",  tags=["Analytics"])
app.include_router(telegram_router,  prefix="/api/v1/telegram",   tags=["Telegram"])
app.include_router(backtest_router,  prefix="/api/v1/backtest",   tags=["Backtest"])


@app.get("/", tags=["Health"])
async def root():
    return {
        "service": "EA_BOT_TRADING",
        "version": "2.0.0",
        "status": "running",
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/health", tags=["Health"])
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "database": "connected",
    }


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="info",
        workers=1,
    )
