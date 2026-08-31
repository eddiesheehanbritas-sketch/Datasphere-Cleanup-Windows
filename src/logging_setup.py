import logging
import sys
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional


class ThreadFileHandler(logging.FileHandler):
    """FileHandler that only writes records emitted from a specific OS thread.

    Used by the combined dual-tenant GUI so EU10 and US10 each get their own
    log file even though both threads share the same root logger hierarchy.
    Pass thread_ident=None to write records from any thread (default behaviour,
    used by the single-tenant app and CLI).

    The `tenant` attribute is used as a secondary discriminator so that two
    handlers with the same thread_ident (e.g. both None in concurrent mode)
    can still be distinguished and replaced independently.
    """

    def __init__(self, filename, thread_ident: Optional[int], tenant: str = "", **kwargs):
        super().__init__(filename, **kwargs)
        self._thread_ident = thread_ident
        self._tenant = tenant

    def emit(self, record):
        if self._thread_ident is None or threading.current_thread().ident == self._thread_ident:
            super().emit(record)


def setup_logging(
    logs_dir: str = "outputs/logs",
    run_id: Optional[str] = None,
    thread_ident: Optional[int] = None,
    tenant: str = "",
) -> logging.Logger:
    Path(logs_dir).mkdir(parents=True, exist_ok=True)

    if run_id is None:
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    log_file = Path(logs_dir) / f"run_{run_id}.log"

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S"
    )

    logger = logging.getLogger("datasphere-cleanup")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    # Replace any existing ThreadFileHandler for this (thread_ident, tenant) pair
    # with a fresh one pointing at the new log file. Handlers for other tenants
    # or other thread identities are left untouched.
    logger.handlers = [
        h for h in logger.handlers
        if not (
            isinstance(h, ThreadFileHandler)
            and h._thread_ident == thread_ident
            and h._tenant == tenant
        )
    ]

    file_handler = ThreadFileHandler(log_file, thread_ident=thread_ident, tenant=tenant, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)

    # Only add a StreamHandler if none exists yet (CLI path).
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
               for h in logger.handlers):
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        console_handler.setLevel(logging.INFO)
        logger.addHandler(console_handler)

    logger.info(f"Logging initialised — run_id={run_id}, log_file={log_file}")
    return logger


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"datasphere-cleanup.{name}")
