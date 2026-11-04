"""HTTP 公共配置。

证书策略：certifi 的 CA 包 + Windows 系统证书库合并。

- 打包成 onedir 后 Python 找不到系统证书路径，certifi 必须显式喂给 httpx；
- 但本机开了抓包 / 企业代理时（如 Reqable），TLS 会被其根证书重签，
  该证书装在 Windows 系统信任库里、certifi 里没有——只喂 certifi 会报
  CERTIFICATE_VERIFY_FAILED。所以这里把两个来源合并成一个 SSLContext。
"""
from __future__ import annotations

import ssl
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def _context() -> ssl.SSLContext | None:
    try:
        ctx = ssl.create_default_context()      # Windows 上会枚举系统 ROOT/CA 库
    except Exception:                           # noqa: BLE001
        return None
    try:
        import certifi
        cafile = certifi.where()
        if Path(cafile).is_file():
            ctx.load_verify_locations(cafile=cafile)
    except Exception:                           # noqa: BLE001
        pass
    return ctx


def ssl_verify():
    """返回传给 httpx 的 verify 参数；拿不到证书环境时回退默认行为。"""
    ctx = _context()
    return ctx if ctx is not None else True
