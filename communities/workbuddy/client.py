"""WorkBuddy（腾讯 AI 办公工作台）签到协议客户端。

端点（实测可达，未带凭证时统一返回 401，说明路径正确）：
- POST /v2/billing/meter/checkin-activity-status   只读：今天签了没（today_checked_in）
- POST /v2/billing/meter/daily-checkin             执行签到（成功 {"credit": 100}）
- POST /billing/meter/get-user-resource            积分资源包汇总

鉴权：`Authorization: Bearer <accessToken>` + `X-User-Id: <uid>`，请求体都是 {}。
签到接口幂等：今天签过再调返回 code=10001「今天已签到，请明天再来」，不会多发。

注意：桌面端的 accessToken 从 5.6.2 起在本地文件里是加密的（$wbEncrypted），
程序不去破解它，改为手动导入（和 Trae 一样）。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass

import httpx

from core.http import ssl_verify

BASE_DEFAULT = "https://www.workbuddy.cn"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")

# 已经签到的业务码
CODE_ALREADY = 10001


@dataclass
class WbResult:
    code: int = -1
    msg: str = ""
    data: object = None
    http_status: int = 0
    raw: str = ""

    @property
    def ok(self) -> bool:
        return self.http_status == 200 and self.code in (0, 200)

    @property
    def already(self) -> bool:
        return self.code == CODE_ALREADY or "已签到" in (self.msg or "")

    @property
    def token_invalid(self) -> bool:
        return self.http_status in (401, 403) or self.code in (401, 403, 40100, 40300)

    def __str__(self) -> str:
        base = f"code={self.code} {self.msg}".strip()
        if self.raw:
            base += f" | {self.raw}"
        return base


def _num(v) -> int | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return int(round(v))


def _find_bool(data, keys: tuple[str, ...]) -> bool | None:
    want = {k.lower() for k in keys}
    for k, v in (data or {}).items() if isinstance(data, dict) else []:
        if str(k).lower() in want and isinstance(v, bool):
            return v
    # 再往下钻一层（有的接口把状态包在 data / activity 里）
    for v in (data or {}).values() if isinstance(data, dict) else []:
        if isinstance(v, dict):
            got = _find_bool(v, keys)
            if got is not None:
                return got
    return None


def _find_int(data, keys: tuple[str, ...]) -> int | None:
    want = {k.lower() for k in keys}
    if isinstance(data, dict):
        for k, v in data.items():
            if str(k).lower() in want:
                got = _num(v)
                if got is not None:
                    return got
        for v in data.values():
            if isinstance(v, dict):
                got = _find_int(v, keys)
                if got is not None:
                    return got
    return None


CHECKED_KEYS = ("today_checked_in", "todayCheckedIn", "checked_in", "checkedIn",
                "signed", "todaySigned", "is_signed", "isSigned")
TODAY_KEYS = ("today_credit", "todayCredit", "daily_credit", "dailyCredit",
              "today_credits", "credit_today")
TOTAL_KEYS = ("total_credit", "totalCredit", "credit_balance", "creditBalance",
              "available_credit", "remaining_credit", "balance")


class WorkBuddyClient:
    def __init__(self, token: str, uid: str, base: str = BASE_DEFAULT,
                 timeout: float = 20.0, min_interval: float = 1.0):
        tok = (token or "").strip()
        for prefix in ("bearer ", "Bearer "):
            if tok.lower().startswith(prefix.strip().lower()):
                tok = tok[len(prefix):].strip()
        self.token = tok
        self.uid = (uid or "").strip()
        self.base = (base or BASE_DEFAULT).rstrip("/")
        self.timeout = timeout
        self.min_interval = min_interval
        self._last = 0.0
        self.http = httpx.Client(timeout=timeout, follow_redirects=False, verify=ssl_verify())

    def close(self) -> None:
        self.http.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _headers(self) -> dict[str, str]:
        h = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": UA,
        }
        # 空值时不带头，否则 httpx 会因 "Bearer " 抛 Illegal header value
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        if self.uid:
            h["X-User-Id"] = self.uid
        return h

    def _throttle(self) -> None:
        gap = time.monotonic() - self._last
        if gap < self.min_interval:
            time.sleep(self.min_interval - gap)
        self._last = time.monotonic()

    def _call(self, method: str, path: str, body: dict | None = None,
              retries: int = 1) -> WbResult:
        url = f"{self.base}{path}"
        last = WbResult(msg="未执行")
        for attempt in range(retries + 1):
            self._throttle()
            try:
                r = self.http.request(method, url, json=body if body is not None else {},
                                      headers=self._headers())
                text = (r.text or "").strip()
                body_snip = text[:400]
                if r.status_code != 200:
                    last = WbResult(code=-r.status_code, msg=f"HTTP {r.status_code}",
                                    http_status=r.status_code, raw=body_snip)
                elif not text:
                    # 已签到时服务端可能直接返回空体 / null
                    last = WbResult(code=CODE_ALREADY, msg="今天已签到",
                                    http_status=200, raw="(empty)")
                else:
                    try:
                        j = json.loads(text)
                    except ValueError:
                        return WbResult(msg="返回非 JSON", http_status=200, raw=body_snip)
                    if j is None:
                        last = WbResult(code=CODE_ALREADY, msg="今天已签到",
                                        http_status=200, raw="null")
                    elif isinstance(j, dict):
                        code = j.get("code")
                        code = 0 if code is None else int(code)
                        last = WbResult(code=code,
                                        msg=str(j.get("msg") or j.get("message") or ""),
                                        data=j.get("data", j), http_status=200, raw=body_snip)
                    else:
                        last = WbResult(code=0, data=j, http_status=200, raw=body_snip)
            except httpx.HTTPError as e:
                last = WbResult(msg=f"{type(e).__name__}: {e}")
            if last.ok or last.already or last.token_invalid or attempt >= retries:
                return last
            time.sleep(1.5)
        return last

    # ---------- 业务端点 ----------
    def checkin_status(self) -> WbResult:
        return self._call("POST", "/v2/billing/meter/checkin-activity-status", {})

    def daily_checkin(self) -> WbResult:
        return self._call("POST", "/v2/billing/meter/daily-checkin", {})

    def resource(self) -> WbResult:
        """积分资源包：服务端按账号下所有资源包返回明细（空请求体即可）。"""
        return self._call("POST", "/billing/meter/get-user-resource", {})


# ---------------- 响应解析 ----------------
def parse_status(data) -> tuple[bool | None, int | None]:
    """返回 (今日已签, 今日已得积分)。拿不到返回 None。"""
    return _find_bool(data, CHECKED_KEYS), _find_int(data, TODAY_KEYS)


def _remaining_of(item: dict) -> int | None:
    """从一个资源包里取「还剩多少」。字段名各家不一，按常见顺序试。"""
    for key in ("remaining", "remain", "left", "available", "availableAmount",
                "remainAmount", "unused", "surplus", "balance", "credit",
                "CapacityRemain", "capacityRemain"):          # WorkBuddy PascalCase
        got = _num(item.get(key))
        if got is not None:
            return got
    # total / capacity - used
    for total_key, used_key in (("total", "used"), ("capacity", "used"),
                                ("totalAmount", "usedAmount"),
                                ("capacityAmount", "consumedAmount"),
                                ("CycleCapacity", "CycleUsed"),
                                ("Capacity", "Used"),
                                ("CapacitySize", "CapacityUsed")):
        total, used = _num(item.get(total_key)), _num(item.get(used_key))
        if total is not None:
            return max(total - (used or 0), 0)
    return None


def parse_resource(data) -> int:
    """把资源包 / 配额桶汇总成可用积分。解析不出来返回 -1。"""
    if not isinstance(data, (dict, list)):
        return -1

    # WorkBuddy 资源包（实测结构）：data.Response.Data.Accounts[]
    # 每项带 CapacityUnit / CapacityRemain / CapacityUsed / CapacitySize
    try:
        accounts = data["Response"]["Data"]["Accounts"]
        if isinstance(accounts, list) and accounts:
            total = 0
            hit = False
            for a in accounts:
                if not isinstance(a, dict):
                    continue
                unit = str(a.get("CapacityUnit") or "").lower()
                if unit and unit != "credits":
                    continue
                remain = _num(a.get("CapacityRemain"))
                if remain is not None:
                    total += remain
                    hit = True
            if hit:
                return int(total)
    except (KeyError, TypeError):
        pass

    buckets: list[dict] = []

    def walk(node, depth: int = 0):
        if depth > 4:
            return
        if isinstance(node, dict):
            if _remaining_of(node) is not None and any(
                    k in node for k in ("remaining", "remain", "total", "capacity",
                                        "totalAmount", "CycleCapacity", "Capacity")):
                buckets.append(node)
            for v in node.values():
                walk(v, depth + 1)
        elif isinstance(node, list):
            for v in node:
                walk(v, depth + 1)

    walk(data)
    total = sum(_remaining_of(b) or 0 for b in buckets)
    if total:
        return int(total)
    got = _find_int(data, TOTAL_KEYS)
    return got if got is not None else -1


def uid_from_jwt(token: str) -> str:
    """accessToken 是 JWT 时，从 payload 里抠 uid（取不到返回空）。"""
    import base64
    parts = (token or "").split(".")
    if len(parts) < 2:
        return ""
    seg = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(seg).decode("utf-8"))
    except Exception:
        return ""
    for key in ("uid", "userId", "user_id", "sub", "uin", "accountId"):
        v = payload.get(key)
        if isinstance(v, str) and v:
            return v
    return ""


def profile_from_jwt(token: str) -> dict:
    """从 JWT payload 里取用户资料（nickname / preferred_username / sub）。

    Keycloak 签发的 accessToken 里 nickname 是真实昵称（如「枫镜辞」），
    preferred_username 通常是手机号，sub 就是 X-User-Id。取不到返回空串。
    """
    import base64
    parts = (token or "").split(".")
    if len(parts) < 2:
        return {}
    seg = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(seg).decode("utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    nickname = str(payload.get("nickname") or "")
    username = str(payload.get("preferred_username") or "")
    sub = str(payload.get("sub") or "")
    return {"nickname": nickname, "username": username, "sub": sub}


def parse_pasted(text: str) -> tuple[str, str]:
    """从粘贴内容里抠出 (token, uid)。

    支持三种粘法，用户从 F12 复制哪种都行：
    1. 只有 token：`eyJhbGciOi…` / `Bearer eyJ…`
    2. 请求头几行：`authorization: Bearer …` + `x-user-id: …`
    3. 右键 Copy as cURL：`curl 'https://…' -H 'authorization: Bearer …' -H 'x-user-id: …'`
    抠不到 uid 时返回空串，交给 JWT / 本机客户端兜底。
    """
    import re
    raw = (text or "").strip()
    if not raw:
        return "", ""
    token, uid = "", ""
    # 头部整段：不区分大小写，允许被单双引号包着（cURL 的 -H '...'）
    m = re.search(r"authorization\s*:\s*(?:bearer\s+)?([A-Za-z0-9._\-+/=]{16,})",
                  raw, re.I)
    if m:
        token = m.group(1)
    m2 = re.search(r"x-user-id\s*:\s*([A-Za-z0-9._\-]{8,})", raw, re.I)
    if m2:
        uid = m2.group(1)
    if not token:
        # 纯 token：去掉可能残留的 Bearer 前缀
        cand = re.sub(r"^(?:bearer\s+)", "", raw, flags=re.I).strip().strip("'\"")
        if re.fullmatch(r"[A-Za-z0-9._\-+/=]{16,}", cand):
            token = cand
    return token, uid
