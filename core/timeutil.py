"""时间口径工具：统一用本地时区，避免 UTC 日界导致「今天」错 8 小时。"""
from __future__ import annotations

import time
from datetime import datetime, timedelta


def day_start(ts: float | None = None) -> int:
    """本地时区当天 00:00 的时间戳。"""
    d = datetime.fromtimestamp(ts if ts is not None else time.time())
    return int(d.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())


def days_before(n: int, ts: float | None = None) -> int:
    """n 天前（含今天算第 1 天，所以 n=1 就是今天 0 点）。"""
    d = datetime.fromtimestamp(ts if ts is not None else time.time())
    d = d.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=max(0, n - 1))
    return int(d.timestamp())


def fmt_ts(ts: int | float, fmt: str = "%m-%d %H:%M:%S") -> str:
    try:
        return datetime.fromtimestamp(int(ts)).strftime(fmt)
    except (OSError, ValueError, OverflowError):
        return "-"


def fmt_span(seconds: float) -> str:
    """把秒数说成人话，给「耗时」类字段用。"""
    seconds = max(0.0, float(seconds))
    if seconds < 1:
        return f"{int(seconds * 1000)} 毫秒"
    if seconds < 60:
        return f"{seconds:.1f} 秒"
    return f"{int(seconds // 60)} 分 {int(seconds % 60)} 秒"
