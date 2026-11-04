"""用户设置持久化（~/.signrover/settings.json）。"""
from __future__ import annotations

import json
from pathlib import Path

DEFAULT_INTERVAL = 2.0
DEFAULTS: dict = {"adb": "", "interval": DEFAULT_INTERVAL}


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


_cache: Settings | None = None


def settings() -> Settings:
    """全局单例，避免各处重复读盘。"""
    global _cache
    if _cache is None:
        _cache = Settings()
    return _cache
