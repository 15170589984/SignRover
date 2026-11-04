"""Windows 进程内存扫描：从本机 PC 工具的进程里找登录态令牌。

背景：Trae / WorkBuddy 这类 Electron 客户端把 accessToken 加密存盘，
但发请求时必然以明文存在于自身进程内存里。米游社 provider 对模拟器
内存做的是同一件事（device/emulator.py 扫 stoken），这里是 Windows 进程版。

只读已提交的私有内存（堆），不碰映像和文件映射；扫到的 JWT 需由调用方
用平台接口验证后才能使用（内存里可能残留旧 token）。
"""
from __future__ import annotations

import ctypes
import re
import sys
from ctypes import wintypes

# JWT 三段式；长度下限放宽，兼容不同平台的短签名
JWT_RE = re.compile(rb"eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}")

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
MEM_COMMIT = 0x1000
MEM_PRIVATE = 0x20000
PAGE_READABLE = (0x02, 0x04, 0x20, 0x40)   # READONLY / READWRITE / EXECUTE_READ / EXECUTE_READWRITE


class _MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p),
                ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", wintypes.DWORD),
                ("RegionSize", ctypes.c_size_t),
                ("State", wintypes.DWORD),
                ("Protect", wintypes.DWORD),
                ("Type", wintypes.DWORD)]


def _k32():
    return ctypes.windll.kernel32


def _psapi():
    return ctypes.windll.psapi


def available() -> bool:
    return sys.platform == "win32"


def find_pids(path_substrings: tuple[str, ...]) -> list[tuple[int, str]]:
    """返回 exe 路径包含任一子串（不区分大小写）的进程列表。"""
    if not available():
        return []
    arr = (wintypes.DWORD * 8192)()
    cb = wintypes.DWORD()
    if not _psapi().EnumProcesses(ctypes.byref(arr), ctypes.sizeof(arr), ctypes.byref(cb)):
        return []
    out: list[tuple[int, str]] = []
    for i in range(cb.value // ctypes.sizeof(wintypes.DWORD)):
        pid = arr[i]
        if not pid:
            continue
        h = _k32().OpenProcess(0x1000, False, pid)     # QUERY_LIMITED_INFORMATION
        if not h:
            continue
        buf = ctypes.create_unicode_buffer(512)
        size = wintypes.DWORD(512)
        try:
            if _psapi().GetModuleFileNameExW(h, None, buf, ctypes.byref(size)):
                exe = buf.value
                low = exe.lower()
                if any(s.lower() in low for s in path_substrings):
                    out.append((pid, exe))
        finally:
            _k32().CloseHandle(h)
    return out


def scan_pid_pattern(pid: int, pattern: re.Pattern, group: int = 0,
                     budget_mb: int = 350) -> list[str]:
    """扫描单个进程的私有堆内存，返回 pattern 命中的字符串（去重保序）。"""
    if not available():
        return []
    k32 = _k32()
    h = k32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
    if not h:
        return []
    found: dict[str, str] = {}
    addr = 0
    addr_max = 0x7FFFFFFEFFFF
    read_total = 0
    budget = budget_mb * 1024 * 1024
    mbi = _MBI()
    try:
        while addr < addr_max and read_total < budget:
            if not k32.VirtualQueryEx(h, ctypes.c_void_p(addr),
                                      ctypes.byref(mbi), ctypes.sizeof(mbi)):
                break
            size = mbi.RegionSize or 0x1000
            if (mbi.State == MEM_COMMIT and mbi.Type == MEM_PRIVATE
                    and mbi.Protect in PAGE_READABLE):
                buf = (ctypes.c_char * size)()
                got = ctypes.c_size_t()
                if k32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, size,
                                         ctypes.byref(got)) and got.value:
                    data = buf.raw[:got.value]
                    read_total += got.value
                    for m in pattern.finditer(data):
                        try:
                            s = m.group(group).decode("ascii", "ignore")
                        except (IndexError, UnicodeDecodeError):
                            continue
                        if s:
                            found.setdefault(s[:60] + f"#{group}", s)
            addr += size
    finally:
        k32.CloseHandle(h)
    return list(found.values())


def scan_for_jwt(path_substrings: tuple[str, ...],
                 budget_mb: int = 350, max_pids: int = 16) -> list[str]:
    """扫描匹配的进程集合，汇总去重后的候选 JWT。"""
    return scan_for_pattern(JWT_RE, path_substrings, group=0,
                            budget_mb=budget_mb, max_pids=max_pids)


def scan_for_pattern(pattern: re.Pattern, path_substrings: tuple[str, ...],
                     group: int = 0, budget_mb: int = 350,
                     max_pids: int = 16) -> list[str]:
    """按自定义正则扫描匹配的进程集合，汇总去重后的候选。"""
    toks: list[str] = []
    seen: set[str] = set()
    for pid, _exe in find_pids(path_substrings)[:max_pids]:
        for t in scan_pid_pattern(pid, pattern, group, budget_mb):
            if t not in seen:
                seen.add(t)
                toks.append(t)
    return toks
