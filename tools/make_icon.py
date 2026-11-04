"""生成应用图标 tools/icon.ico（多尺寸，纯 Qt 绘制 + 手写 ICO 容器）。

用法：python tools/make_icon.py
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)

SIZES = (16, 24, 32, 48, 64, 128, 256)
BLUE_TOP = "#5B7CFF"
BLUE_BOTTOM = "#3A57D6"


def draw_icon(size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)

    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    s = float(size)
    # 内缩一点，避免 Windows 显示时贴边被裁
    pad = s * 0.055
    rect = QRectF(pad, pad, s - 2 * pad, s - 2 * pad)

    # 圆角方块 + 竖直渐变
    body = QPainterPath()
    body.addRoundedRect(rect, s * 0.24, s * 0.24)
    grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    grad.setColorAt(0.0, QColor(BLUE_TOP))
    grad.setColorAt(0.55, QColor("#4C6FFF"))
    grad.setColorAt(1.0, QColor(BLUE_BOTTOM))
    p.fillPath(body, grad)

    # 白色对勾
    pen = QPen(QColor("#FFFFFF"))
    pen.setWidthF(max(1.6, s * 0.108))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    tick = QPainterPath()
    tick.moveTo(s * 0.285, s * 0.525)
    tick.lineTo(s * 0.445, s * 0.680)
    tick.lineTo(s * 0.720, s * 0.345)
    p.drawPath(tick)

    p.end()
    return img


def png_bytes(img: QImage) -> bytes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(ba.data())


def build_ico(items: list[tuple[int, bytes]]) -> bytes:
    count = len(items)
    header = struct.pack("<HHH", 0, 1, count)
    offset = 6 + 16 * count
    entries = b""
    blobs = b""
    for size, blob in items:
        dim = 0 if size >= 256 else size      # 0 表示 256
        entries += struct.pack(
            "<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
        blobs += blob
    return header + entries + blobs


def main() -> int:
    app = QGuiApplication.instance() or QGuiApplication([])
    items = [(s, png_bytes(draw_icon(s))) for s in SIZES]
    out = ROOT / "tools" / "icon.ico"
    out.write_bytes(build_ico(items))
    print(f"written {out} ({out.stat().st_size} bytes, {len(items)} sizes)")
    # 顺带导出一张 256 png 给安装包/文档用
    png_out = ROOT / "tools" / "icon.png"
    draw_icon(256).save(str(png_out), "PNG")
    print(f"written {png_out}")
    del app
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
