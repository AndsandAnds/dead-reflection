"""
Centralized logging.

We keep this minimal for now (stdlib logging), but the intent is the same as the
reference project: one place to configure logging for the whole app.
"""

from __future__ import annotations

import logging
from functools import lru_cache


@lru_cache
def initialize_logger() -> logging.Logger:
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        level=logging.INFO,
    )
    return logging.getLogger("reflections")


logger = initialize_logger()
