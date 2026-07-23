from __future__ import annotations

import logging
import sys


def configure_logging(level: str = "INFO") -> None:
    """Ensure application loggers emit to stderr at INFO level.

    Uvicorn configures its own access/error loggers but leaves the root logger
    at WARNING with no handler, so ``logger.info()`` calls under ``app.*`` are
    silently dropped. This runs at import/startup so synchronous request handlers
    (including transcription) log directly to the uvicorn console.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    root = logging.getLogger()
    handler: logging.Handler | None = None
    for existing in root.handlers:
        if isinstance(existing, logging.StreamHandler) and getattr(existing, "stream", None) is sys.stderr:
            handler = existing
            break

    if handler is None:
        handler = logging.StreamHandler(sys.stderr)
        root.addHandler(handler)

    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    handler.setLevel(log_level)
    root.setLevel(log_level)

    for logger_name in ("app", "app.services", "app.pipeline"):
        logging.getLogger(logger_name).setLevel(log_level)
