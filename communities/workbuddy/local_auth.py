"""读取本机 WorkBuddy 客户端里**未加密**的那部分信息。

桌面端登录态文件 `workbuddy-desktop.info` 里，`accessToken` 从 5.6.2 起是
`$wbEncrypted` 信封（AES-GCM），本程序**不去破解**它；但 `account.uid` 和
`auth.domain` 仍是明文，可以自动带出来，用户只需要粘贴 token。

路径（Windows）：%LOCALAPPDATA%\\CodeBuddyExtension\\Data\\Public\\auth\\workbuddy-desktop.info
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REL = Path("CodeBuddyExtension") / "Data" / "Public" / "auth" / "workbuddy-desktop.info"
ALLOWED_DOMAIN_SUFFIX = (".workbuddy.cn", ".codebuddy.cn", "workbuddy.cn", "codebuddy.cn")


def info_path() -> Path | None:
    if sys.platform == "win32":
        root = os.environ.get("LOCALAPPDATA")
    else:
        root = None
    candidates = []
    if root:
        candidates.append(Path(root) / REL)
    candidates.append(Path.home() / ".local" / "share" / REL)     # Linux 约定
    for p in candidates:
        if p.is_file():
            return p
    return None


def read_account() -> dict:
    """返回 {"uid": ..., "domain": ...}；读不到返回空 dict。"""
    p = info_path()
    if not p:
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    acc = d.get("account") or {}
    auth = d.get("auth") or {}
    uid = str(acc.get("uid") or "")
    domain = str(auth.get("domain") or "")
    # 域名只允许官方后缀，避免被改过的本地文件带去任意主机
    if domain and not domain.lower().endswith(ALLOWED_DOMAIN_SUFFIX):
        domain = ""
    out = {}
    if uid and not uid.startswith("$wb"):
        out["uid"] = uid
    if domain:
        out["domain"] = f"https://{domain}"
    return out


def read_memory_tokens(max_verify: int = 6):
    """从本机 WorkBuddy 客户端进程内存里找候选 accessToken。

    桌面端的 accessToken 落盘是加密信封，但主进程发请求时是明文 JWT，
    和米游扫模拟器内存取 stoken 同一思路。返回候选列表（可能有旧的），
    由调用方用平台接口逐个验证后使用。
    """
    try:
        from core.winmem import scan_for_jwt
    except Exception:
        return []
    return scan_for_jwt(("workbuddy",))
