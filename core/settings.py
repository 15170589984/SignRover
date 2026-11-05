"""用户设置持久化（~/.signrover/settings.json）。"""
from __future__ import annotations

import json
from pathlib import Path

DEFAULT_INTERVAL = 2.0
DEFAULT_SCHEDULE: dict = {
    "enabled": False,
    "time": "08:00",        # HH:MM，本机时间
    "days": "daily",        # daily / weekday
    "scope": "__all__",     # "__all__" 或账号 key（community:aid）
    "last_run": "",         # 上次自动执行的日期 YYYY-MM-DD，防同一天重复跑
    "suppressed": "",       # 勾选时今天的点已过 → 记今天，今天不再触发；改时间后清除
}
DEFAULTS: dict = {"adb": "", "interval": DEFAULT_INTERVAL, "schedule": DEFAULT_SCHEDULE}


class Settings:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else Path.home() / ".signrover" / "settings.json"
        self.data = dict(DEFAULTS)
        self.load()

    # ---------- 读写 ----------
    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(raw, dict):
            return
        self.data = dict(DEFAULTS)
        self.data.update(raw)          # 保留扩展字段（任务勾选等）
        if not isinstance(self.data.get("adb"), str):
            self.data["adb"] = ""
        iv = self.data.get("interval")
        self.data["interval"] = float(iv) if isinstance(iv, (int, float)) else DEFAULT_INTERVAL

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------- 取值 ----------
    @property
    def adb(self) -> str:
        return str(self.data.get("adb") or "").strip()

    @adb.setter
    def adb(self, value: str) -> None:
        self.data["adb"] = (value or "").strip()

    @property
    def interval(self) -> float:
        try:
            return max(1.0, min(30.0, float(self.data.get("interval", DEFAULT_INTERVAL))))
        except (TypeError, ValueError):
            return DEFAULT_INTERVAL

    @interval.setter
    def interval(self, value: float) -> None:
        self.data["interval"] = max(1.0, min(30.0, float(value)))

    @property
    def schedule(self) -> dict:
        """定时执行配置，字段缺失时用默认值补齐（老配置文件升级后也能用）。"""
        cur = self.data.get("schedule")
        if not isinstance(cur, dict):
            cur = {}
        out = dict(DEFAULT_SCHEDULE)
        out.update({k: v for k, v in cur.items() if k in DEFAULT_SCHEDULE})
        if out.get("days") not in ("daily", "weekday"):
            out["days"] = "daily"
        t = str(out.get("time") or "08:00")
        try:
            hh, mm = t.split(":")[:2]
            out["time"] = f"{max(0, min(23, int(hh))):02d}:{max(0, min(59, int(mm))):02d}"
        except (ValueError, AttributeError):
            out["time"] = "08:00"
        out["enabled"] = bool(out.get("enabled"))
        return out

    def set_schedule(self, **kwargs) -> dict:
        sched = self.schedule
        sched.update({k: v for k, v in kwargs.items() if k in DEFAULT_SCHEDULE})
        self.data["schedule"] = sched
        return sched


_cache: Settings | None = None


def settings() -> Settings:
    """全局单例，避免各处重复读盘。"""
    global _cache
    if _cache is None:
        _cache = Settings()
    return _cache
