"""Bounded, read-only evidence from an operator-configured printer log."""
from __future__ import annotations

import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path

from .collector import redact_text
from .printer_config import active_printer, config_path

MAX_LOG_BYTES = 64 * 1024


def get_log_events() -> dict:
    """Read a local collected log; never accept paths from model arguments."""
    printer = active_printer()
    if config_path().exists():
        configured = printer.local_log if printer else ""
    else:
        configured = os.environ.get("CALICLAW_PRINTER_LOG", "")
    configured = configured.strip()
    unavailable = {"available": False, "events": [], "reason": "Printer log unavailable."}
    if not configured:
        return unavailable
    try:
        # Nonblocking open avoids hanging on a misconfigured FIFO/device.
        fd = os.open(Path(configured), os.O_RDONLY | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                return unavailable
            offset = max(0, info.st_size - MAX_LOG_BYTES)
            stream.seek(offset)
            raw = stream.read(MAX_LOG_BYTES)
        if offset:
            # Do not expose a partial line whose secret label was truncated.
            raw = raw.partition(b"\n")[2]
        text = raw.decode("utf-8", errors="replace")
        text = redact_text(text)
        # Cover quoted key/value logs as well as plain collector text.
        text = re.sub(
            r'''(?i)(["']?(?:api[_-]?key|token|password|secret|authorization)["']?\s*[:=]\s*)(?:"[^"\n]*"|'[^'\n]*'|[^\s,}]+)''',
            r'\1<redacted>', text,
        )
        text = re.sub(r"https?://[^\s\"'<>]+", "<redacted-url>", text)
        events = [{"message": line} for line in text.splitlines() if line.strip()]
        return {
            "available": True,
            "source": "configured_printer_log",
            "source_updated_at": datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat(),
            "truncated": offset > 0,
            "events": events,
            "note": "Collected log snapshot; it may not reflect the current printer state.",
        }
    except (OSError, ValueError):
        return unavailable
