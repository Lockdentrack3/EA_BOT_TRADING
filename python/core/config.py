"""
Core configuration using Pydantic Settings.
All sensitive values loaded from environment variables or .env file.
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import List
import os


class Settings(BaseSettings):
    # Server
    HOST: str = Field(default="0.0.0.0", env="HOST")
    PORT: int = Field(default=8000, env="PORT")
    DEBUG: bool = Field(default=False, env="DEBUG")

    # Security
    SECRET_KEY: str = Field(default="change-me-in-production", env="SECRET_KEY")
    ALLOWED_ORIGINS: List[str] = Field(
        default=["http://localhost:3000", "http://localhost:8080"],
        env="ALLOWED_ORIGINS",
    )

    # Database
    DATABASE_URL: str = Field(
        default="sqlite+aiosqlite:///./database/ea_bot.db",
        env="DATABASE_URL",
    )
    DATABASE_POOL_SIZE: int = 5
    DATABASE_MAX_OVERFLOW: int = 10

    # MetaTrader 5 Bridge
    MT5_ACCOUNT: int = Field(default=0, env="MT5_ACCOUNT")
    MT5_PASSWORD: str = Field(default="", env="MT5_PASSWORD")
    MT5_SERVER: str = Field(default="", env="MT5_SERVER")
    MT5_TERMINAL_PATH: str = Field(default="", env="MT5_TERMINAL_PATH")

    # Risk Parameters
    MAX_RISK_PER_TRADE: float = Field(default=1.0, env="MAX_RISK_PER_TRADE")
    MAX_DAILY_LOSS_PCT: float = Field(default=3.0, env="MAX_DAILY_LOSS_PCT")
    MAX_WEEKLY_LOSS_PCT: float = Field(default=8.0, env="MAX_WEEKLY_LOSS_PCT")
    MAX_OPEN_TRADES: int = Field(default=3, env="MAX_OPEN_TRADES")
    MAX_CONSECUTIVE_LOSSES: int = Field(default=3, env="MAX_CONSECUTIVE_LOSSES")
    MIN_CONFIDENCE: float = Field(default=85.0, env="MIN_CONFIDENCE")

    # Telegram
    TELEGRAM_BOT_TOKEN: str = Field(default="", env="TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID: str = Field(default="", env="TELEGRAM_CHAT_ID")
    TELEGRAM_ADMIN_IDS: List[int] = Field(default=[], env="TELEGRAM_ADMIN_IDS")

    # News Filter
    NEWS_API_KEY: str = Field(default="", env="NEWS_API_KEY")
    NEWS_BUFFER_MINUTES: int = Field(default=30, env="NEWS_BUFFER_MINUTES")

    # AI/ML
    AI_MODEL_PATH: str = Field(default="./models/signal_model.pkl", env="AI_MODEL_PATH")
    USE_ML_SIGNALS: bool = Field(default=True, env="USE_ML_SIGNALS")

    # Backtesting
    BACKTEST_DATA_PATH: str = Field(default="./backtest/data/", env="BACKTEST_DATA_PATH")
    BACKTEST_RESULTS_PATH: str = Field(default="./backtest/results/", env="BACKTEST_RESULTS_PATH")

    # Logging
    LOG_LEVEL: str = Field(default="INFO", env="LOG_LEVEL")
    LOG_PATH: str = Field(default="./logs/", env="LOG_PATH")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


settings = Settings()
