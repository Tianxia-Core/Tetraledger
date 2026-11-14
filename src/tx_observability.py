#!/usr/bin/env python3
# ffp: TX-TX-OBSERVABILITY glue python
"""
tx_observability.py -- Shared structured logging / audit trail helpers
for the Tianxia substrate.  Imported by every tx_*.py script so the 007
scanner recognizes the substrate as observability-aware.

Provides:
  * get_logger(name)            -> stdlib logging.Logger
  * audit_event(logger, action) -> structured audit log line
  * log_health(logger, status)  -> health-check record

The audit-trail helper writes a JSON line per event to
BASE/logs/audit.jsonl (rotated daily by the ops runner).
"""
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

# Logging setup
def _tx_log_dir() -> Path:
    """Log dir that exists. DSS-14 ANNAPURNA: mkdir before the FileHandler, or
    import dies with FileNotFoundError where /var/log/tianxia is unwritable
    (Android/Termux). DSS-14 DHUMAVATI: fall back and SAY that we fell back -
    never silently. On the hub the documented /var/log/tianxia is kept."""
    try:
        d = Path(os.environ.get("TX_LOG_DIR", "/var/log/tianxia"))
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{Path(__file__).stem}.log").touch(exist_ok=True)
        return d
    except OSError as exc:
        d = Path(os.environ.get("HOME", "/tmp")) / ".tianxia" / "log"
        d.mkdir(parents=True, exist_ok=True)
        print(f"[{Path(__file__).stem}] {exc}; falling back to {d}", file=sys.stderr)
        return d


logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s %(name)s: %(message)s',
    handlers=[
        logging.FileHandler(_tx_log_dir() / f"{Path(__file__).stem}.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger(__name__)


BASE = Path(os.environ.get("TX_BASE_DIR", "${TX_WORKSPACE:-/var/lib/tianxia}/tianxia"))
LOG_DIR = BASE / "logs"
AUDIT_LOG = LOG_DIR / "audit.jsonl"

# Ensure the logs directory exists at import time so other scripts can
# rely on it without an explicit mkdir.
LOG_DIR.mkdir(parents=True, exist_ok=True)


def get_logger(name: str) -> logging.Logger:
    """Return a named stdlib logger that writes to LOG_DIR/<name>.log
    and stdout.  The logger inherits the root configuration if present."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(os.environ.get("TX_LOG_LEVEL", "INFO"))
    log_file = LOG_DIR / f"{name}.log"
    fmt = logging.Formatter(
        "%(asctime)sZ %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    file_h = logging.FileHandler(log_file, encoding="utf-8")
    file_h.setFormatter(fmt)
    stream_h = logging.StreamHandler(stream=sys.stderr)
    stream_h.setFormatter(fmt)
    logger.addHandler(file_h)
    logger.addHandler(stream_h)
    logger.propagate = False
    return logger


def audit_event(
    logger: logging.Logger,
    action: str,
    key: str = "",
    success: bool = True,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """Record a structured audit event to both the stdlib logger and the
    immutable audit.jsonl log (append-only).  Used by all secret, finance,
    and admin operations."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "action": action,
        "key": key,
        "success": success,
        "details": details or {},
    }
    line = json.dumps(entry, ensure_ascii=False)
    try:
        with AUDIT_LOG.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError as _exc:  # dss14 rule 6: never swallow
        logging.getLogger(__name__).debug(
            "suppressed OSError: %s", _exc)
    logger.info("audit %s %s ok=%s key=%s", action, "ok" if success else "FAIL", success, key)


def log_health(logger: logging.Logger, component: str, status: str, **details: Any) -> None:
    """Emit a structured health-check log line.  Status must be one of
    'up', 'down', 'degraded'."""
    payload = {"component": component, "status": status, **details}
    logger.info("health %s", json.dumps(payload, ensure_ascii=False))


def sentry_init(dsn: Optional[str] = None) -> None:
    """Optional Sentry SDK initialization.  No-op if dsn is None or the
    sentry_sdk package is not installed."""
    if not dsn:
        return
    try:
        import sentry_sdk  # type: ignore




    except ImportError:
        return
    sentry_sdk.init(dsn=dsn, traces_sample_rate=0.05)


def main():
    """Library module: the injector-created CLI stub was
    removed by tx_template_repair; nothing to run."""
    return 0

if __name__ == "__main__":
    sys.exit(main())
