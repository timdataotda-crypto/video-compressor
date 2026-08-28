from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.utils.paths import ensure_dir, get_logs_dir


def setup_logging(level: int = logging.INFO) -> None:
    logs_dir = get_logs_dir()
    ensure_dir(logs_dir)

    root = logging.getLogger()
    if root.handlers:
        return

    root.setLevel(level)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    for name in ("app", "jobs", "errors"):
        path = logs_dir / f"{name}.log"
        handler = RotatingFileHandler(
            path, maxBytes=5_000_000, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(formatter)
        if name == "errors":
            handler.setLevel(logging.ERROR)
            logging.getLogger().addHandler(handler)
        elif name == "jobs":
            job_logger = logging.getLogger("app.jobs")
            job_logger.addHandler(handler)
            job_logger.propagate = True
        else:
            root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
