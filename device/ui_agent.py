"""基于 adb 的界面自动化（不依赖 uiautomator2，打包无额外体积）。

能力：
- 导出界面层级（uiautomator dump）
- 按文本 / resource-id / 描述查找元素并点击
- 滑动、返回、等待
- 文本输入（ASCII 直送；中文走剪贴板中转）

米游社的浏览 / 点赞 / 评论 / 发帖这几项任务由米游社按真实行为判定，
纯协议读接口不会计入进度，所以这几项必须驱动真实界面。
"""
from __future__ import annotations

import re
import subprocess
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass

BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


class UiError(RuntimeError):
    pass


@dataclass
class UIElement:
    text: str
    desc: str
    rid: str
    cls: str
    bounds: tuple[int, int, int, int]
    clickable: bool
    scrollable: bool
    checked: bool
    selected: bool

    @property
    def center(self) -> tuple[int, int]:
        x1, y1, x2, y2 = self.bounds
        return (x1 + x2) // 2, (y1 + y2) // 2

    @property
    def label(self) -> str:
        return self.text or self.desc

    def __str__(self) -> str:
        return f"<{self.cls.split('.')[-1]} '{self.label}' {self.bounds}>"


class UiAgent:
    """一个进程内复用的界面操作句柄。"""

    def __init__(self, adb: str, serial: str = "", verbose: bool = False):
        self.adb = adb
        self.serial = serial
        self.verbose = verbose

    # ---------- 底层 ----------
    def _base(self) -> list[str]:
        return [self.adb] + (["-s", self.serial] if self.serial else [])

    def _shell(self, *args: str, timeout: int = 40) -> str:
        p = subprocess.run(self._base() + ["shell", *args], capture_output=True, timeout=timeout)
        return (p.stdout or p.stderr).decode("utf-8", "replace")

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(f"[ui] {msg}", flush=True)

    @property
    def size(self) -> tuple[int, int]:
        m = re.search(r"(\d+)x(\d+)", self._shell("wm", "size"))
        return (int(m.group(1)), int(m.group(2))) if m else (1080, 1920)

    # ---------- 界面层级 ----------
    def dump(self) -> list[UIElement]:
        for _ in range(3):
            out = self._shell("uiautomator", "dump", "/sdcard/signrover_ui.xml")
            if "dumped" in out or "UI hierchary" in out:
                break
            time.sleep(0.5)
        else:
            raise UiError(f"导出界面失败：{out.strip()[:80]}")
        p = subprocess.run(self._base() + ["exec-out", "cat /sdcard/signrover_ui.xml"],
                           capture_output=True, timeout=40)
        raw = p.stdout.decode("utf-8", "replace")
        if not raw.strip():
            raise UiError("界面层级为空，可能正处于动画或加载中")
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as e:
            raise UiError(f"界面层级解析失败：{e}") from e
        return [self._to_el(n) for n in root.iter("node")]

    @staticmethod
    def _to_el(node: ET.Element) -> UIElement:
        b = BOUNDS_RE.search(node.get("bounds", ""))
        bounds = tuple(int(x) for x in b.groups()) if b else (0, 0, 0, 0)
        return UIElement(
            text=node.get("text", ""),
            desc=node.get("content-desc", ""),
            rid=node.get("resource-id", ""),
            cls=node.get("class", ""),
            bounds=bounds,
            clickable=node.get("clickable") == "true",
            scrollable=node.get("scrollable") == "true",
            checked=node.get("checked") == "true",
            selected=node.get("selected") == "true",
        )

    # ---------- 查找 ----------
    def find(self, text: str | None = None, contains: str | None = None,
             desc: str | None = None, rid: str | None = None,
             cls: str | None = None, clickable: bool | None = None,
             elements: list[UIElement] | None = None) -> UIElement | None:
        for el in elements if elements is not None else self.dump():
            if text is not None and el.text != text:
                continue
            if contains is not None and contains not in el.label:
                continue
            if desc is not None and el.desc != desc:
                continue
            if rid is not None and not el.rid.endswith(rid):
                continue
            if cls is not None and not el.cls.endswith(cls):
                continue
            if clickable is not None and el.clickable != clickable:
                continue
            return el
        return None

    def find_all(self, contains: str, label_only: bool = True,
                 elements: list[UIElement] | None = None) -> list[UIElement]:
        out = []
        for el in elements if elements is not None else self.dump():
            hay = el.label if label_only else f"{el.text}|{el.desc}|{el.rid}"
            if contains in hay and el.bounds != (0, 0, 0, 0):
                out.append(el)
        return out

    # ---------- 操作 ----------
    def tap(self, x: int, y: int) -> None:
        self._log(f"tap ({x},{y})")
        self._shell("input", "tap", str(x), str(y))
        time.sleep(0.4)

    def tap_el(self, el: UIElement) -> None:
        self.tap(*el.center)

    def tap_text(self, text: str, contains: bool = True, timeout: float = 8.0) -> bool:
        el = self.wait_for(text=text if not contains else None,
                           contains=text if contains else None, timeout=timeout)
        if el:
            self.tap_el(el)
            return True
        return False

    def swipe(self, x1: int, y1: int, x2: int, y2: int, ms: int = 300) -> None:
        self._log(f"swipe ({x1},{y1})->({x2},{y2})")
        self._shell("input", "swipe", str(x1), str(y1), str(x2), str(y2), str(ms))
        time.sleep(0.5)

    def scroll(self, direction: str = "down", ratio: float = 0.55) -> None:
        w, h = self.size
        cx = w // 2
        span = int(h * ratio)
        if direction == "down":
            self.swipe(cx, int(h * 0.75), cx, int(h * 0.75) - span, 260)
        else:
            self.swipe(cx, int(h * 0.35), cx, int(h * 0.35) + span, 260)

    def back(self) -> None:
        self._log("back")
        self._shell("input", "keyevent", "4")
        time.sleep(0.6)

    def wait_for(self, text: str | None = None, contains: str | None = None,
                 rid: str | None = None, cls: str | None = None,
                 timeout: float = 8.0, interval: float = 0.6) -> UIElement | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                el = self.find(text=text, contains=contains, rid=rid, cls=cls)
            except UiError:
                el = None
            if el:
                return el
            time.sleep(interval)
        return None

    def wait_gone(self, contains: str, timeout: float = 12.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if not self.find(contains=contains):
                    return True
            except UiError:
                return True
            time.sleep(0.6)
        return False

    # ---------- 输入 ----------
    def input_text(self, s: str) -> None:
        """输入文本。纯 ASCII 直接送；含中文时走剪贴板中转。"""
        if not s:
            return
        if all(ord(c) < 128 for c in s):
            self._shell("input", "text", s.replace(" ", "%s"))
            return
        self.set_clipboard(s)
        # 长按输入框后粘贴由调用方保证（不同输入框菜单差异大）
        raise UiError("含中文的文本需要先 set_clipboard 再手动粘贴，或改用 paste_into")

    def set_clipboard(self, s: str) -> None:
        """把文本放进系统剪贴板（Android 8+ 需 App 在前台才能读取）。"""
        esc = s.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
        self._shell("am", "broadcast", "-a", "clipper.set", "-e", "text", f"'{esc}'")
