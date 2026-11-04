"""生成安装向导左侧位图 packaging/wizard.bmp（164x314 的 2 倍图，NSIS 会自动缩放）。

用法：python tools/make_wizard_bitmap.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QGuiApplication, QImage, QLinearGradient,
                           QPainter, QPainterPath, QPen)

W, H = 328, 628          # 164 x 314 的 2 倍


def draw() -> QImage:
    img = QImage(W, H, QImage.Format.Format_RGB32)
    img.fill(QColor("#4C6FFF"))

    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    # 背景渐变
    grad = QLinearGradient(QPointF(0, 0), QPointF(0, H))
    grad.setColorAt(0.0, QColor("#5B7CFF"))
    grad.setColorAt(1.0, QColor("#2F49C4"))
    p.fillRect(QRectF(0, 0, W, H), grad)

    # 右上角两团柔和光晕，避免整块死板
    for cx, cy, r, a in ((W * 1.02, H * 0.12, 210, 26), (W * -0.12, H * 0.92, 180, 22)):
        g2 = QLinearGradient(0, 0, 0, 0)
        p.setBrush(QColor(255, 255, 255, a))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), r, r)

    # 中间图标卡片
    size, x, y = 132, (W - 132) / 2, H * 0.30
    card = QPainterPath()
    card.addRoundedRect(QRectF(x, y, size, size), 30, 30)
    p.setBrush(QColor(255, 255, 255, 240))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawPath(card)

    pen = QPen(QColor("#3A57D6"))
    pen.setWidthF(13)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    tick = QPainterPath()
    tick.moveTo(x + size * 0.26, y + size * 0.53)
    tick.lineTo(x + size * 0.44, y + size * 0.70)
    tick.lineTo(x + size * 0.75, y + size * 0.32)
    p.drawPath(tick)

    # 产品名
    p.setPen(QColor("#FFFFFF"))
    f = QFont()
    f.setPixelSize(34)
    f.setBold(True)
    p.setFont(f)
    p.drawText(QRectF(0, H * 0.315 + size + 34, W, 48),
               Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, "社区签到助手")

    f2 = QFont()
    f2.setPixelSize(17)
    p.setFont(f2)
    p.setPen(QColor(255, 255, 255, 200))
    p.drawText(QRectF(0, H * 0.315 + size + 86, W, 30),
               Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, "游戏社区自动日常")
    p.drawText(QRectF(0, H * 0.315 + size + 114, W, 26),
               Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, "v1.0.0")

    # 底部一行小字
    f3 = QFont()
    f3.setPixelSize(14)
    p.setFont(f3)
    p.setPen(QColor(255, 255, 255, 130))
    p.drawText(QRectF(0, H - 58, W, 24),
               Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
               "米游社 · 库街区")

    p.end()
    return img


def main() -> int:
    app = QGuiApplication.instance() or QGuiApplication([])
    out = ROOT / "packaging" / "wizard.bmp"
    img = draw()
    ok = img.save(str(out), "BMP")
    print("saved", out, ok, out.stat().st_size if out.exists() else 0, "bytes")
    png = ROOT / "docs" / "wizard_preview.png"
    img.save(str(png), "PNG")
    print("preview", png)
    del app
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
