"""界面主题：中性灰底 + 白卡片 + 细边框的现代工具风。

配色与控件密度参考 shadcn/ui、Linear、Vercel Dashboard 这类主流开源工具的
做法：底色浅灰、内容区纯白、1px 淡边框代替阴影、圆角统一 8~10px、
主色只用在「主操作按钮 / 选中态 / 强调数字」上，其余全部中性灰。

样式集中在这里，页面代码只负责摆布局，避免各处零散 setStyleSheet
（零散样式会让 Qt 反复重新 polish 控件，是界面卡顿的常见来源）。
"""
from __future__ import annotations

import tempfile
from pathlib import Path

# ---------------- 调色板 ----------------
BG = "#F6F7F9"            # 页面底色
SURFACE = "#FFFFFF"       # 卡片 / 输入框
SUBTLE = "#FAFAFB"        # 侧栏 / 表头 / 次级面
BORDER = "#E8E9EE"
BORDER_STRONG = "#DCDEE5"
TEXT = "#14181F"
TEXT_SUB = "#6F7787"
TEXT_MUTED = "#98A0AE"
ACCENT = "#2F6FED"
ACCENT_HOVER = "#2560D8"
ACCENT_PRESSED = "#1E4FBF"
ACCENT_SOFT = "#EDF3FE"
GREEN = "#0E9F6E"
RED = "#E02424"
ORANGE = "#F59E0B"
GOLD = "#B7791F"

# 少数旧代码按 PRIMARY 引用，保留别名
PRIMARY = ACCENT

_ICON_DIR = Path(tempfile.gettempdir()) / "signrover_ui_v3"


def _draw(name: str, size: int, paint) -> str:
    """画一张 3 倍尺寸的 PNG 并按逻辑尺寸引用，保证高 DPI 下不糊。"""
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QImage, QPainter

        _ICON_DIR.mkdir(parents=True, exist_ok=True)
        png = _ICON_DIR / f"{name}.png"
        if not png.exists():
            scale = 3
            img = QImage(size * scale, size * scale, QImage.Format_ARGB32)
            img.fill(Qt.transparent)
            p = QPainter(img)
            p.setRenderHint(QPainter.Antialiasing, True)
            paint(p, size * scale)
            p.end()
            img.save(str(png))
        return png.as_posix()
    except Exception:                     # noqa: BLE001
        return ""


def _check() -> str:
    def paint(p, s: int) -> None:
        from PySide6.QtCore import QPoint, QRectF, Qt
        from PySide6.QtGui import QColor, QPen

        p.setBrush(QColor(ACCENT))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(0, 0, s, s), s * 0.25, s * 0.25)
        pen = QPen(QColor("#FFFFFF"))
        pen.setWidthF(s * 0.13)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        u = s / 16.0
        p.drawPolyline([QPoint(int(4 * u), int(8.4 * u)),
                        QPoint(int(6.8 * u), int(11.2 * u)),
                        QPoint(int(11.6 * u), int(5.2 * u))])

    return _draw("check", 16, paint)


def _chevron(direction: str) -> str:
    def paint(p, s: int) -> None:
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtGui import QColor, QPen

        pen = QPen(QColor(TEXT_SUB))
        pen.setWidthF(s * 0.13)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        if direction == "down":
            p.drawPolyline([QPoint(int(s * 0.28), int(s * 0.4)),
                            QPoint(int(s * 0.5), int(s * 0.62)),
                            QPoint(int(s * 0.72), int(s * 0.4))])
        else:
            p.drawPolyline([QPoint(int(s * 0.28), int(s * 0.62)),
                            QPoint(int(s * 0.5), int(s * 0.4)),
                            QPoint(int(s * 0.72), int(s * 0.62))])

    return _draw(f"chevron_{direction}", 12, paint)


def _search() -> str:
    def paint(p, s: int) -> None:
        from PySide6.QtCore import QPointF, QRectF, Qt
        from PySide6.QtGui import QColor, QPen

        pen = QPen(QColor(TEXT_MUTED))
        pen.setWidthF(s * 0.1)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        r = s * 0.3
        p.drawEllipse(QRectF(s * 0.16, s * 0.16, r * 2, r * 2))
        p.drawLine(QPointF(s * 0.68, s * 0.68), QPointF(s * 0.86, s * 0.86))

    return _draw("search", 16, paint)


CHECK_ICON = _check()
CHEVRON_DOWN = _chevron("down")
CHEVRON_UP = _chevron("up")
SEARCH_ICON = _search()

check_image = f"image: url({CHECK_ICON});" if CHECK_ICON else ""
combo_arrow = f"image: url({CHEVRON_DOWN});" if CHEVRON_DOWN else "image: none;"
spin_up = f"image: url({CHEVRON_UP});" if CHEVRON_UP else ""
spin_down = f"image: url({CHEVRON_DOWN});" if CHEVRON_DOWN else ""


QSS = f"""
/* ================= 基础 ================= */
QWidget {{
    color: {TEXT};
    background: transparent;
}}
QMainWindow, QWidget#Root, QWidget#Page {{ background: {BG}; }}
QDialog {{ background: {SURFACE}; }}

QLabel {{ background: transparent; }}
QLabel#PageTitle {{ font-size: 19px; font-weight: 700; color: #101620; }}
QLabel#PageSub {{ font-size: 12px; color: {TEXT_MUTED}; }}
QLabel#CardTitle {{ font-size: 14px; font-weight: 600; color: {TEXT}; }}
QLabel#Muted {{ color: {TEXT_SUB}; font-size: 12px; }}
QLabel#Hint {{ color: {TEXT_MUTED}; font-size: 12px; }}
QLabel#FieldLabel {{ color: {TEXT_SUB}; font-size: 12px; }}
QLabel#BigNum {{ font-size: 27px; font-weight: 700; color: #101620; }}

/* ================= 侧栏 ================= */
QWidget#Sidebar {{
    background: {SUBTLE};
    border-right: 1px solid #ECEDF2;
}}
QLabel#Logo {{
    background: {ACCENT};
    color: #FFFFFF;
    border-radius: 9px;
    font-size: 15px;
    font-weight: 700;
}}
QLabel#Brand {{ font-size: 15px; font-weight: 700; color: {TEXT}; }}
QLabel#BrandSub {{ font-size: 11px; color: {TEXT_MUTED}; }}
QLabel#NavSection {{
    color: {TEXT_MUTED}; font-size: 11px; font-weight: 600;
    padding: 0 20px;
}}

QPushButton#Nav {{
    text-align: left;
    padding: 0 12px;
    min-height: 36px;
    margin: 1px 10px;
    border: none;
    border-radius: 8px;
    background: transparent;
    color: #4C5464;
    font-size: 13.5px;
}}
QPushButton#Nav:hover {{ background: #F0F1F5; color: {TEXT}; }}
QPushButton#Nav:checked {{
    background: {ACCENT_SOFT};
    color: {ACCENT_HOVER};
    font-weight: 600;
}}

/* ================= 卡片 ================= */
QFrame#Card, QFrame#StatCard {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}

/* ================= 按钮 ================= */
QPushButton {{
    background: {SURFACE};
    border: 1px solid {BORDER_STRONG};
    border-radius: 8px;
    min-height: 30px;
    padding: 0 14px;
    color: #262B36;
    font-size: 13px;
}}
QPushButton:hover {{ background: #F7F8FA; border-color: #C9CCD5; }}
QPushButton:pressed {{ background: #EDEFF3; }}
QPushButton:disabled {{
    background: #FAFAFB; border-color: #EEEFF3; color: #B4B9C4;
}}
QPushButton:focus {{ outline: none; }}

QPushButton#Primary {{
    background: {ACCENT}; border: 1px solid {ACCENT}; color: #FFFFFF;
    font-weight: 600; padding: 0 18px;
}}
QPushButton#Primary:hover {{ background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
QPushButton#Primary:pressed {{ background: {ACCENT_PRESSED}; }}
QPushButton#Primary:disabled {{
    background: #C8D7F9; border-color: #C8D7F9; color: #FFFFFF;
}}

QPushButton#Ghost {{
    background: transparent; border: 1px solid transparent; color: #525A68;
    padding: 0 10px;
}}
QPushButton#Ghost:hover {{ background: #EFF1F5; color: {TEXT}; }}
QPushButton#Ghost:pressed {{ background: #E6E9EF; }}

QPushButton#Danger {{ color: {RED}; }}
QPushButton#Danger:hover {{
    background: #FDF2F2; border-color: #F3C9C9; color: {RED};
}}

/* 任务页执行中的「停止」：实心红，和蓝色「开始执行」明显区分 */
QPushButton#DangerSolid {{
    background: {RED}; border: 1px solid {RED}; color: #FFFFFF;
    font-weight: 600; padding: 0 18px;
}}
QPushButton#DangerSolid:hover {{ background: #B2202A; border-color: #B2202A; }}
QPushButton#DangerSolid:pressed {{ background: #9B1B24; }}
QPushButton#DangerSolid:disabled {{
    background: #EFC9CC; border-color: #EFC9CC; color: #FFFFFF;
}}

QPushButton#Pager {{
    min-height: 26px; padding: 0 10px; border-radius: 6px;
    font-size: 12px; color: #525A68; background: {SURFACE};
}}
QPushButton#Pager:disabled {{ color: #C2C7D1; background: #FBFBFC; border-color: #EFF0F4; }}
QPushButton#Pager:hover:!disabled {{ background: #F3F5F9; border-color: #CFD3DC; }}

/* ================= 输入 ================= */
QLineEdit, QComboBox, QSpinBox, QAbstractSpinBox {{
    background: {SURFACE};
    border: 1px solid {BORDER_STRONG};
    border-radius: 8px;
    min-height: 30px;
    padding: 0 10px;
    color: {TEXT};
    selection-background-color: #DCE7FD;
    selection-color: {TEXT};
}}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover {{ border-color: #C9CCD5; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {ACCENT}; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{
    background: #F5F6F8; border-color: #ECEDF1; color: #A9AFBB;
}}

QComboBox {{ padding-right: 26px; }}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 24px;
    border: none;
    background: transparent;
}}
QComboBox::down-arrow {{ {combo_arrow} width: 10px; height: 10px; }}
QComboBox QAbstractItemView {{
    background: {SURFACE};
    border: 1px solid #E1E3E9;
    border-radius: 8px;
    padding: 4px;
    outline: 0;
    selection-background-color: {ACCENT_SOFT};
    selection-color: {TEXT};
}}
QComboBox QAbstractItemView::item {{
    min-height: 28px;
    padding: 0 8px;
    border-radius: 6px;
    color: {TEXT};
}}
QComboBox QAbstractItemView::item:hover {{ background: #F4F5F8; }}

QSpinBox {{ padding-right: 20px; }}
QSpinBox::up-button, QSpinBox::down-button {{
    width: 18px; border: none; background: transparent;
}}
QSpinBox::up-arrow {{ {spin_up} width: 8px; height: 8px; }}
QSpinBox::down-arrow {{ {spin_down} width: 8px; height: 8px; }}

/* ================= 表格 / 列表 ================= */
QTableView, QTableWidget, QListView, QTreeView {{
    background: {SURFACE};
    alternate-background-color: #FBFCFD;
    border: none;
    border-radius: 10px;
    gridline-color: transparent;
    selection-background-color: {ACCENT_SOFT};
    selection-color: {TEXT};
    outline: 0;
}}
QTableView::item, QTableWidget::item, QListView::item {{
    padding: 0 8px;
    border: none;
}}
QTableView::item:selected, QTableWidget::item:selected {{ background: {ACCENT_SOFT}; }}

QHeaderView {{ background: transparent; border: none; }}
QHeaderView::section {{
    background: {SUBTLE};
    color: {TEXT_SUB};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 0 8px;
    height: 32px;
    font-size: 12px;
    font-weight: 600;
}}
QHeaderView::section:first {{ border-top-left-radius: 10px; }}
QHeaderView::section:last {{ border-top-right-radius: 10px; }}
QTableCornerButton::section {{ background: {SUBTLE}; border: none; }}

/* ================= 勾选 ================= */
QCheckBox {{ spacing: 8px; color: #262B36; font-size: 13px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: 4px;
    border: 1px solid #C7CBD4; background: {SURFACE};
}}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{
    background: {ACCENT}; border-color: {ACCENT}; {check_image}
}}
QCheckBox::indicator:disabled {{ background: #F3F4F7; border-color: #E3E5EA; }}

/* ================= 滚动条 ================= */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{
    background: #D4D8E0; border-radius: 3px; min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{ background: #B9BFCA; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{
    background: #D4D8E0; border-radius: 3px; min-width: 32px;
}}
QScrollBar::handle:horizontal:hover {{ background: #B9BFCA; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ================= 页签（登录账号对话框） ================= */
QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 8px;
    background: {SURFACE};
    top: -1px;               /* 让选中页签的下划线和内容框连上 */
}}
QTabBar {{ background: transparent; }}
QTabBar::tab {{
    background: transparent;
    color: {TEXT_SUB};
    padding: 7px 18px 6px 18px;
    margin-right: 4px;
    border: none;
    border-bottom: 2px solid transparent;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    font-size: 13px;
}}
QTabBar::tab:hover:!selected {{ color: {TEXT}; background: #F3F5F9; }}
QTabBar::tab:selected {{
    color: {ACCENT_HOVER};
    border-bottom: 2px solid {ACCENT};
    font-weight: 600;
}}

/* ================= 其它 ================= */
QTextEdit {{
    background: {SUBTLE};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 8px;
    color: #242B38;
    font-family: "Cascadia Mono", "Consolas", "Menlo", monospace;
    font-size: 12px;
}}
/* 执行日志：浅灰底衬白卡片，字色加深一档，避免白底上发灰看不清 */
QTextEdit#Log {{
    background: #FBFCFD;
    border: 1px solid {BORDER};
    border-radius: 8px;
    margin: 0 14px 14px 14px;
    padding: 10px 12px;
    color: #242B38;
    font-size: 12.5px;
}}
QProgressBar {{
    border: none; background: #ECEEF3; border-radius: 3px;
    height: 6px; text-align: center; color: transparent;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}

QStatusBar {{
    background: {SURFACE};
    border-top: 1px solid #ECEDF2;
    color: {TEXT_SUB};
    font-size: 12px;
}}
QStatusBar::item {{ border: none; }}
QToolTip {{
    background: #1F2430; color: #FFFFFF; border: none;
    border-radius: 6px; padding: 6px 8px; font-size: 12px;
}}
QMenu {{
    background: {SURFACE}; border: 1px solid {BORDER};
    border-radius: 8px; padding: 4px;
}}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {ACCENT_SOFT}; color: {TEXT}; }}
"""


def apply_app_style(app) -> None:
    """统一设置：Fusion 基础样式 + 全局字体 + 全局 QSS。

    Fusion 比 Windows 原生样式在 QSS 下的表现更稳定、重绘更轻；
    字体只设一次，样式表里不再写 `*` 通配选择器（通配符会让每个控件
    都走一遍样式解析，页面切换时能感觉到迟滞）。
    """
    from PySide6.QtGui import QFont

    app.setStyle("Fusion")
    f = QFont()
    f.setFamilies(["Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI"])
    f.setPointSize(9)
    f.setHintingPreference(QFont.PreferNoHinting)
    app.setFont(f)
    app.setStyleSheet(QSS)
