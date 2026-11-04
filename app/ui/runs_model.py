"""执行明细的表格模型。

用 QAbstractTableModel 而不是 QTableWidget：
数据一次性装进内存，视图只渲染可见的十几行，几千条记录也不会卡。
"""
from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor

from core.communities import get as community_of
from core.timeutil import fmt_ts

HEADERS = ("时间", "账号", "类型", "目标", "结果", "获得", "说明")

STATUS_CN = {"success": "成功", "failed": "失败", "skipped": "跳过"}
STATUS_COLOR = {
    "成功": QColor("#12A150"),
    "失败": QColor("#D9363E"),
    "跳过": QColor("#8A93A6"),
}

KIND_CN = {
    "game_sign": "游戏签到",
    "bbs_sign": "社区签到",
    "browse": "浏览",
    "like": "点赞",
    "share": "分享",
    "comment": "评论",
    "publish": "发帖",
    "claim": "领奖",
    "tool_sign": "工具签到",
}

GOLD = QColor("#B7791F")


class RunsTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[tuple[str, ...]] = []
        self._names: dict[str, str] = {}     # account key -> 显示名（带昵称）

    def set_names(self, names: dict[str, str]) -> None:
        self._names = dict(names or {})

    # ---------- Qt 接口 ----------
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if orientation == Qt.Orientation.Horizontal:
            if role == Qt.ItemDataRole.DisplayRole:
                return HEADERS[section]
            if role == Qt.ItemDataRole.TextAlignmentRole and section in (4, 5):
                return int(Qt.AlignmentFlag.AlignCenter)
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return row[col]
        if role == Qt.ItemDataRole.ForegroundRole:
            if col == 4:
                return STATUS_COLOR.get(row[4])
            if col == 5 and row[5] != "—":
                return GOLD
        if role == Qt.ItemDataRole.TextAlignmentRole and col in (4, 5):
            return int(Qt.AlignmentFlag.AlignCenter)
        if role == Qt.ItemDataRole.ToolTipRole:
            return row[col]
        return None

    # ---------- 业务接口 ----------
    def set_records(self, records: list[dict]) -> None:
        self.beginResetModel()
        self._rows = [self._flatten(r, self._names) for r in records]
        self.endResetModel()

    def flat_rows(self) -> list[tuple[str, ...]]:
        """导出用：已经是给人看的格式。"""
        return list(self._rows)

    @staticmethod
    def _currency_of(r: dict) -> str:
        cur = (r.get("currency") or "").strip()
        if cur:
            return cur
        # 老记录没存货币名，按账号所属平台推断
        key = (r.get("account_uid") or "").partition(":")[0]
        try:
            return community_of(key).currency
        except Exception:                                   # noqa: BLE001
            return "币"

    @classmethod
    def _flatten(cls, r: dict, names: dict[str, str] | None = None) -> tuple[str, ...]:
        key = r.get("account_uid") or ""
        acc = (names or {}).get(key) or ""
        if not acc:
            acc = key
            if ":" in acc:
                ck, _, uid = acc.partition(":")
                try:
                    acc = f"{community_of(ck).name} {uid}"
                except Exception:                           # noqa: BLE001
                    acc = f"{ck} {uid}"
        status = STATUS_CN.get(r.get("status") or "", r.get("status") or "")
        raw_kind = r.get("kind") or ""
        text = (r.get("message") or "").replace("\r", " ").replace("\n", " ").strip()
        points = int(r.get("points") or 0)
        gain = f"+{points} {cls._currency_of(r)}" if points else "—"
        return (
            fmt_ts(r.get("created_at") or 0),
            acc,
            KIND_CN.get(raw_kind, raw_kind),
            r.get("target") or "",
            status,
            gain,
            text,
        )
