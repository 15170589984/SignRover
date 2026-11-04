"""通用界面组件：卡片、统计卡、页头、搜索框、标签等。

样式一律走 theme.QSS 的 objectName，不在控件上零散 setStyleSheet，
这样切换页面时 Qt 不需要重新解析样式，交互也更顺。
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QVBoxLayout, QWidget)

from app.ui import theme
from app.ui.theme import TEXT_MUTED


class Card(QFrame):
    """白底圆角卡片。"""

    def __init__(self, parent: QWidget | None = None, padding: int = 16,
                 spacing: int = 10):
        super().__init__(parent)
        self.setObjectName("Card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(padding, padding, padding, padding)
        self._layout.setSpacing(spacing)

    def body(self) -> QVBoxLayout:
        return self._layout

    def add(self, w: QWidget) -> QWidget:
        self._layout.addWidget(w)
        return w


class StatCard(Card):
    """数字统计卡片：小标题 + 大数字 + 说明。"""

    def __init__(self, title: str, value: str = "-", sub: str = "",
                 accent: str | None = None):
        super().__init__(padding=16, spacing=2)
        self.setObjectName("StatCard")
        self.title_label = QLabel(title)
        self.title_label.setObjectName("Muted")
        self.value_label = QLabel(value)
        self.value_label.setObjectName("BigNum")
        if accent:
            self.value_label.setStyleSheet(f"color: {accent};")
        self.sub_label = QLabel(sub)
        self.sub_label.setObjectName("Hint")
        self._layout.addWidget(self.title_label)
        self._layout.addSpacing(2)
        self._layout.addWidget(self.value_label)
        self._layout.addWidget(self.sub_label)
        self._layout.addStretch(1)

    def set_value(self, value: str, sub: str | None = None) -> None:
        self.value_label.setText(value)
        if sub is not None:
            self.sub_label.setText(sub)

    def set_title(self, text: str) -> None:
        self.title_label.setText(text)


def page_header(title_text: str, sub: str = "") -> QWidget:
    """页面标题块：主标题 + 一行说明。"""
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(3)
    lb = QLabel(title_text)
    lb.setObjectName("PageTitle")
    lay.addWidget(lb)
    if sub:
        s = QLabel(sub)
        s.setObjectName("PageSub")
        lay.addWidget(s)
    return w


def field_label(text: str) -> QLabel:
    lb = QLabel(text)
    lb.setObjectName("FieldLabel")
    return lb


def search_box(placeholder: str = "搜索", width: int | None = None) -> QLineEdit:
    """带放大镜图标的搜索输入框。"""
    e = QLineEdit()
    e.setPlaceholderText(placeholder)
    e.setClearButtonEnabled(True)
    if width:
        e.setFixedWidth(width)
    if theme.SEARCH_ICON:
        ico = QIcon(theme.SEARCH_ICON)
        act = QAction(ico, "", e)
        act.setEnabled(False)
        e.addAction(act, QLineEdit.LeadingPosition)
    return e


def badge(text: str, color: str = TEXT_MUTED, bg: str = "#F3F4F7") -> QLabel:
    """小圆角状态标签。"""
    lb = QLabel(text)
    lb.setStyleSheet(
        f"color:{color};background:{bg};border-radius:5px;"
        f"padding:2px 8px;font-size:11.5px;font-weight:600;")
    return lb


def ghost_button(text: str) -> QPushButton:
    b = QPushButton(text)
    b.setObjectName("Ghost")
    b.setCursor(Qt.PointingHandCursor)
    return b


def pager_button(text: str) -> QPushButton:
    b = QPushButton(text)
    b.setObjectName("Pager")
    b.setCursor(Qt.PointingHandCursor)
    return b


def hline() -> QFrame:
    ln = QFrame()
    ln.setFrameShape(QFrame.HLine)
    ln.setFixedHeight(1)
    ln.setStyleSheet(f"background:{theme.BORDER};border:none;")
    return ln


def row(*widgets: QWidget, spacing: int = 10) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(spacing)
    for x in widgets:
        lay.addWidget(x)
    return w


def vspace(h: int = 8) -> QWidget:
    w = QWidget()
    w.setFixedHeight(h)
    return w


def muted(text: str) -> QLabel:
    lb = QLabel(text)
    lb.setObjectName("Muted")
    return lb


def hint(text: str) -> QLabel:
    lb = QLabel(text)
    lb.setObjectName("Hint")
    lb.setWordWrap(True)
    return lb


def title(text: str, size: int = 14) -> QLabel:
    lb = QLabel(text)
    lb.setObjectName("CardTitle")
    if size != 14:
        lb.setStyleSheet(f"font-size:{size}px;font-weight:700;")
    return lb


def dot(color: str, size: int = 8) -> QLabel:
    """小圆点，用于任务完成状态。"""
    lb = QLabel()
    lb.setFixedSize(size, size)
    lb.setStyleSheet(f"background:{color};border-radius:{size // 2}px;")
    return lb


def color_icon(hex_color: str, size: int = 12) -> QIcon:
    pm = QPixmap(QSize(size, size))
    pm.fill(QColor(hex_color))
    return QIcon(pm)
