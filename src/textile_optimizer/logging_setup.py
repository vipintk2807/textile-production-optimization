"""Standard-library logging configuration (technical_specification 14.2).

Logs record run identifiers, fingerprints, statuses and timings - never complete datasets.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from . import config

_CONFIGURED = False


def get_logger(name: str = "textile_optimizer") -> logging.Logger:
    global _CONFIGURED
    logger = logging.getLogger("textile_optimizer")
    if not _CONFIGURED:
        logger.setLevel(logging.INFO)
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        stream = logging.StreamHandler()
        stream.setFormatter(fmt)
        logger.addHandler(stream)
        try:
            file_handler = RotatingFileHandler(
                config.log_dir() / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
            )
            file_handler.setFormatter(fmt)
            logger.addHandler(file_handler)
        except OSError:  # read-only location etc.: keep console logging only
            logger.warning("File logging is unavailable; logging to console only.")
        logger.propagate = False
        _CONFIGURED = True
    return logger if name == "textile_optimizer" else logger.getChild(name)
