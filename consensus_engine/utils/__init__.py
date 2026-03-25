"""Utility modules for the consensus engine."""

import logging
import sys
from consensus_engine import config as cfg


def setup_logging() -> logging.Logger:
    """Configure structured logging for the engine."""
    log_level = cfg.get("logging.level", "INFO")
    log_format = cfg.get("logging.format", "%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    log_file = cfg.get("logging.file")

    root_logger = logging.getLogger("consensus_engine")
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    if root_logger.handlers:
        return root_logger

    formatter = logging.Formatter(log_format)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root_logger.addHandler(console)

    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    return root_logger
