"""从本机 Qoder 客户端读登录态（省去手动抓包）。

Windows 下 Qoder 客户端（Electron）把会话存在：
    %APPDATA%\\com.qodercn.app.stable\\auth.v1.dat     （国内版，接口走 openapi.qoder.com.cn）
    %APPDATA%\\com.qoder.app.stable\\auth.v1.dat       （国际版，接口走 openapi.qoder.sh）
格式是 Chromium 的 OSCrypt 信封：`v10` + 12 字节 nonce + AES-256-GCM 密文，
密钥在 `Local State` 的 `os_crypt.encrypted_key` 里（DPAPI 保护的 32 字节）。

两个版本的 token 不能跨域名用，所以读的时候要顺带把「这个客户端属于哪个域名」带出来，
否则国际版的 token 打到国内域名会一律 TOKEN_EXPIRE。

只在 Windows 上实现；其它平台返回空，让用户手动粘贴 token 即可。
**只读取，不修改任何文件；解出来的 token 仅用于当次请求，不落盘。**
"""
from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes as wt
import json
import os
import sys
from pathlib import Path

BASE_CN = "https://openapi.qoder.com.cn"
BASE_INTL = "https://openapi.qoder.sh"

# 客户端数据目录 → 该客户端使用的 API 域名（按优先级排列）
APP_DIRS: tuple[tuple[str, str], ...] = (
    ("com.qodercn.app.stable", BASE_CN),
    ("com.qoder.app.stable", BASE_INTL),
    ("com.qoder.app", BASE_INTL),
    ("com.qodercn.app", BASE_CN),
)
AUTH_FILE = "auth.v1.dat"


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi_unprotect(data: bytes) -> bytes:
    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = _DataBlob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = _DataBlob()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out))
    if not ok:
        raise OSError("DPAPI 解密失败")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def _candidates() -> list[tuple[Path, str]]:
    """返回 [(客户端数据目录, 该客户端对应的域名)]，只保留真实存在的目录。"""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return []
    out: list[tuple[Path, str]] = []
    for name, base in APP_DIRS:
        p = Path(appdata) / name
        if p.is_dir():
            out.append((p, base))
    return out


def decrypt_auth_file(dat_path: Path, local_state: Path) -> dict:
    """解 auth.v1.dat，返回里面的 JSON（token / refreshToken / expiresAt …）。"""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM   # 延迟导入

    state = json.loads(local_state.read_text(encoding="utf-8"))
    enc_key = (state.get("os_crypt") or {}).get("encrypted_key")
    if not enc_key:
        raise OSError("Local State 里没有 os_crypt.encrypted_key")
    raw = base64.b64decode(enc_key)
    if raw[:5] != b"DPAPI":
        raise OSError("不支持的密钥封装格式")
    key = _dpapi_unprotect(raw[5:])

    blob = dat_path.read_bytes()
    if blob[:3] != b"v10":
        raise OSError(f"不支持的登录态格式：{blob[:3]!r}")
    plain = AESGCM(key).decrypt(blob[3:15], blob[15:], None)
    return json.loads(plain.decode("utf-8"))


def read_desktop_token() -> tuple[str, dict]:
    """返回 (token, 附加信息)。读不到时 token 为空，info 里带上原因。

    info["base"] 是该客户端对应的 API 域名（国内 / 国际），后续请求必须用它，
    否则另一边的服务端会直接判 token 失效。
    """
    if sys.platform != "win32":
        return "", {"error": "只支持 Windows 自动读取"}
    dirs = _candidates()
    if not dirs:
        names = " / ".join(n for n, _ in APP_DIRS)
        return "", {"error": f"%APPDATA% 下没有 Qoder 客户端目录（找过 {names}）"}
    last_err = ""
    for ud, base in dirs:
        dat, state = ud / AUTH_FILE, ud / "Local State"
        if not dat.is_file() or not state.is_file():
            last_err = f"{ud} 里没有登录态文件"
            continue
        try:
            info = decrypt_auth_file(dat, state)
        except ImportError as e:
            return "", {"error": f"缺少解密依赖：{e}"}
        except Exception as e:       # 没登录 / 格式变了，换下一个目录试
            last_err = f"{type(e).__name__}: {e}"
            continue
        token = str(info.get("token") or "")
        if not token:
            last_err = f"{dat} 里没有 token 字段"
            continue
        user = info.get("user") if isinstance(info.get("user"), dict) else {}
        return token, {
            "expiresAt": info.get("expiresAt", ""),
            "source": str(dat),
            "base": base,
            "user_id": str(user.get("id") or ""),
            "user_name": str(user.get("name") or ""),
            "user_email": str(user.get("email") or ""),
        }
    return "", {"error": last_err or "没有读到登录态"}
