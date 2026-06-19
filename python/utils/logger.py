"""
Structured logging setup with file rotation + console output.
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from datetime import datetime


def setup_logger(name: str, log_dir: str = "./logs") -> logging.Logger:
    os.makedirs(log_dir, exist_ok=True)
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        "[%(asctime)s][%(levelname)s][%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    # File (rotating 10MB x 5)
    log_file = os.path.join(log_dir, f"{name}.log")
    fh = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    # Error-only file
    err_file = os.path.join(log_dir, "errors.log")
    efh = RotatingFileHandler(err_file, maxBytes=5 * 1024 * 1024, backupCount=3)
    efh.setLevel(logging.ERROR)
    efh.setFormatter(formatter)
    logger.addHandler(efh)

    return logger
