"""开机自启（仅 Windows）。

用当前用户的 Run 注册表项实现，不需要管理员权限：
    HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run

值 = 程序自身路径（打包后是 SignRover.exe；源码运行时是 pythonw + app/main.py），
用户勾掉时删除该值。卸载时安装器也会清一次，避免留下指向已删除文件的空项。
"""
from __future__ import annotations

import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "SignRover"


def _command() -> str:
    """开机要执行的命令行（带引号，路径含空格也不会被拆开）。"""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    # 源码运行：用 pythonw 起主程序，避免开机弹一个黑框
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    runner = pyw if pyw.is_file() else exe
    main = Path(__file__).resolve().parent.parent / "app" / "main.py"
    return f'"{runner}" "{main}"'


def is_enabled() -> bool:
    """注册表里是否有本程序的自启项（且指向的 exe 还在）。"""
    try:
        import winreg
    except ImportError:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            value, _ = winreg.QueryValueEx(k, VALUE_NAME)
    except OSError:
        return False
    if not isinstance(value, str) or not value.strip():
        return False
    # 记录里的路径被删了（换目录、重装到别处）就当没开
    raw = value.strip()
    if raw.startswith('"'):
        target = raw[1:raw.find('"', 1)] if raw.find('"', 1) > 0 else raw
    else:
        target = raw.split(" ")[0]
    return Path(target).exists()


def enable() -> bool:
    """写入自启项；成功返回 True。"""
    try:
        import winreg
    except ImportError:
        return False
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.SetValueEx(k, VALUE_NAME, 0, winreg.REG_SZ, _command())
        return True
    except OSError:
        return False


def disable() -> bool:
    """删除自启项；本来就没有也算成功。"""
    try:
        import winreg
    except ImportError:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, VALUE_NAME)
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False


def set_enabled(on: bool) -> bool:
    return enable() if on else disable()
