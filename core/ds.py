"""米游社 DS 动态签名。

两种算法，由接口决定用哪一个：

- DS1（``x-rpc-client_type: 5``）：luna 签到与 binding 查询
  ``md5("salt=<salt>&t=<t>&r=<6位随机字母数字>")``
- DS2（``x-rpc-client_type: 2``）：BBS App 接口，把 body 与排序后的 query 折进哈希
  ``md5("salt=<salt>&t=<t>&r=<6位数字>&b=<body>&q=<query>")``

DS2 的盐值跨客户端版本稳定；DS1 的盐值随版本变化，需要随 App 更新同步替换。
"""
from __future__ import annotations

import hashlib
import random
import time
import urllib.parse

# BBS App 接口（DS2）—— 长期稳定
SALT_BBS = "t0qEgfub6cvueAPgR5m9aQWWVciEer7v"
# luna / binding（DS1）—— 对应 app_version 2.109.0，客户端升级后可能需要更新
SALT_APP = "d9200c846b10886e8c874fc33c8f308b"
# 网页端盐值
SALT_WEB = "6cqshh5dhw73bzxn20oex7qa7pjyb6vq"

_ALNUM = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def _rand_text6() -> str:
    return "".join(random.choices(_ALNUM, k=6))


def _rand_int6() -> str:
    n = random.randint(100001, 200000)
    return str(n)


def _md5(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def ds1(salt: str = SALT_APP) -> str:
    t = str(int(time.time()))
    r = _rand_text6()
    return f"{t},{r},{_md5(f'salt={salt}&t={t}&r={r}')}"


def sort_query(query: str | dict | None) -> str:
    """把 query 规范成按 key 升序、且逐项 URL 编码的形式。"""
    if not query:
        return ""
    if isinstance(query, dict):
        items = list(query.items())
    else:
        items = urllib.parse.parse_qsl(str(query), keep_blank_values=True)
    items.sort(key=lambda kv: kv[0])
    return "&".join(f"{urllib.parse.quote(str(k), safe='')}={urllib.parse.quote(str(v), safe='')}"
                    for k, v in items)


def ds2(salt: str = SALT_BBS, query: str | dict | None = "", body: str = "") -> str:
    t = str(int(time.time()))
    r = _rand_int6()
    q = sort_query(query)
    return f"{t},{r},{_md5(f'salt={salt}&t={t}&r={r}&b={body}&q={q}')}"


def build_ds(salt: str, query: str | dict | None = "", body: str = "",
             client_type: str = "2") -> str:
    """client_type=2 用 DS2（BBS App），client_type=5 用 DS1（luna/binding）。"""
    return ds1(salt) if client_type == "5" else ds2(salt, query, body)


def verify_salt(salt: str, t: str, r: str, c: str, query: str | dict | None = "",
                body: str = "") -> bool:
    """用抓到的真实请求反推校验 salt 是否正确。"""
    if _md5(f"salt={salt}&t={t}&r={r}&b={body}&q={sort_query(query)}") == c:
        return True
    return _md5(f"salt={salt}&t={t}&r={r}") == c
