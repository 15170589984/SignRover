"""Trae（字节跳动 IDE）签到协议客户端。

端点全部在 https://api.trae.cn。已按真实抓包校准：
- 鉴权头：`Authorization: Cloud-IDE-JWT <token>`（不是 Bearer！粘贴时
  带不带 Cloud-IDE-JWT 前缀都能识别）
- 需要的请求头：x-app-version / package-type / x-user-region / x-device-id，
  UA 为 VSCode 形态（如 `VSCode 1.107.1 (Trae CN)`）
- 响应字段直接放顶层（不是 {code, data} 包裹），如
  `{code: 0, checked_in: true, credits: 100, extra_credits: 100}`
- claim 响应只有 {code, message}，不含数量，到账数用 status 前后差值算

抓包观察到的相关端点：
- GET/POST /trae/api/v2/ug/checkin_credits/status   签到状态
- POST     /trae/api/v2/ug/checkin_credits/claim    领取当日签到积分
- GET/POST /trae/api/v2/ug/activity/info            活动 / 任务信息
- GET/POST /trae/api/v2/pay/ide_user_ent_usage      账户积分余额 / 用量
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass

import httpx

from core.http import ssl_verify

BASE = "https://api.trae.cn"
UA = "VSCode 1.107.1 (Trae CN)"
APP_VERSION = "3.4.13"
PACKAGE_TYPE = "stable_cn"
AUTH_PREFIX = "Cloud-IDE-JWT"

# 表示「已签到 / 已领取」的常见字段名（统一按小写比较）
CHECKED_KEYS = ("checked_in", "did_checked_in", "checked", "isChecked", "is_checked",
                "isCheckIn", "is_check_in", "signed", "isSigned", "todaySigned",
                "signedToday", "hasCheckIn", "has_checkin", "checkin", "checkInToday",
                "checkinToday", "todayCheckin", "claimed", "hasClaimed", "todayClaimed")
# 表示「积分数额」的常见字段名
AMOUNT_KEYS = ("credits", "credit", "points", "amount", "reward", "rewardCredits",
               "totalCredits", "balance", "total", "num", "value")
# 用户昵称的常见字段名
NAME_KEYS = ("nickname", "nickName", "name", "userName", "username", "email")


@dataclass
class TraeResult:
    code: int = -1
    msg: str = ""
    data: object = None
    http_status: int = 0
    raw: str = ""            # 原始响应体片段（调试 / 校准用）

    @property
    def ok(self) -> bool:
        if self.code == 0 or self.code == 200:
            return True
        if isinstance(self.data, dict) and self.data.get("success"):
            return True
        return False

    @property
    def token_invalid(self) -> bool:
        return self.code in (401, 403, 40101, 40300)

    def __str__(self) -> str:
        base = f"code={self.code} {self.msg}".strip()
        if self.raw:
            base += f" | {self.raw}"
        return base


def find_first(data, keys, only_int: bool = False, only_bool: bool = False,
               substr: bool = False):
    """在嵌套 dict/list 里递归找第一个命中字段的值（字段名大小写不敏感）。

    substr=True 时退一步用「字段名包含关键词」匹配，用于 creditBalance 这类
    组合命名；只在精确匹配拿不到结果时才启用。
    """
    want = {k.lower() for k in keys}

    def hit(name: str, v, loose: bool) -> bool:
        n = str(name).lower()
        matched = n in want if not loose else any(k in n for k in want)
        if not matched:
            return False
        if only_int and (isinstance(v, bool) or not isinstance(v, (int, float))):
            return False
        if only_bool and not isinstance(v, bool):
            return False
        return True

    for loose in (False, True) if substr else (False,):
        found = _walk(data, keys, hit, loose)
        if found is not None:
            return found
    return None


def _walk(data, keys, hit, loose: bool):
    if isinstance(data, dict):
        for k, v in data.items():
            if hit(k, v, loose):
                return v
        for v in data.values():
            found = _walk(v, keys, hit, loose)
            if found is not None:
                return found
    elif isinstance(data, list):
        for it in data:
            found = _walk(it, keys, hit, loose)
            if found is not None:
                return found
    return None


class TraeClient:
    def __init__(self, token: str, min_interval: float = 1.0, timeout: float = 20.0):
        tok = (token or "").strip()
        # 兼容粘贴整头：Bearer xxx / Cloud-IDE-JWT xxx / 裸 token
        for prefix in (f"{AUTH_PREFIX} ", "bearer ", "Bearer "):
            if tok.lower().startswith(prefix.lower()):
                tok = tok[len(prefix):].strip()
        self.token = tok
        self.device_id = str(uuid.uuid4())
        self.min_interval = min_interval
        self._last = 0.0
        self.http = httpx.Client(timeout=timeout, follow_redirects=True, verify=ssl_verify())

    def close(self) -> None:
        self.http.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---------- 请求 ----------
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"{AUTH_PREFIX} {self.token}",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "User-Agent": UA,
            "x-app-version": APP_VERSION,
            "package-type": PACKAGE_TYPE,
            "x-user-region": "CN",
            "x-device-id": self.device_id,
        }

    def _throttle(self) -> None:
        gap = time.monotonic() - self._last
        if gap < self.min_interval:
            time.sleep(self.min_interval - gap)
        self._last = time.monotonic()

    def _call(self, method: str, path: str, json_body: dict | None = None,
              retries: int = 1) -> TraeResult:
        url = f"{BASE}/{path.lstrip('/')}"
        last = TraeResult(msg="未执行")
        for attempt in range(retries + 1):
            self._throttle()
            try:
                r = self.http.request(method, url, json=json_body, headers=self._headers())
                body = (r.text or "")[:400]
                if r.status_code != 200:
                    last = TraeResult(code=-r.status_code, msg=f"HTTP {r.status_code}",
                                      http_status=r.status_code, raw=body)
                else:
                    try:
                        j = r.json()
                    except json.JSONDecodeError:
                        return TraeResult(code=-1, msg="返回非 JSON", http_status=200, raw=body)
                    code = j.get("code")
                    if code is None:
                        # activity/info、ent_usage 这类接口直接返回数据体，没有 code
                        code = 0 if (j.get("success") is not False) else -1
                    last = TraeResult(code=int(code),
                                      msg=str(j.get("message") or j.get("msg") or ""),
                                      data=j.get("data", j), http_status=200, raw=body)
            except httpx.HTTPError as e:
                last = TraeResult(code=-1, msg=f"{type(e).__name__}: {e}")
            # token 失效 / 已成功就不用重试了
            if last.ok or last.token_invalid or attempt >= retries:
                return last
            time.sleep(1.5)
        return last

    def _call_auto(self, path: str, prefer_get: bool = True,
                   json_body: dict | None = None) -> TraeResult:
        """不知道端点是 GET 还是 POST 时，先按首选方法发，405/404/400 再换另一种。"""
        first, second = ("GET", "POST") if prefer_get else ("POST", "GET")
        r = self._call(first, path, json_body=json_body)
        if r.http_status in (400, 404, 405):
            r2 = self._call(second, path, json_body=json_body)
            if r2.ok or r2.http_status == 200:
                return r2
        return r

    # ---------- 业务端点 ----------
    @staticmethod
    def _body() -> dict:
        """Trae 桌面端的通用请求体（已实测：claim / activity 都认）。"""
        return {"version_code": APP_VERSION, "req_source": 1}

    def checkin_status(self) -> TraeResult:
        """签到状态：GET 或 POST 都可以，返回 checked_in / credits。"""
        return self._call_auto("trae/api/v2/ug/checkin_credits/status", prefer_get=True)

    def checkin_claim(self) -> TraeResult:
        """领取当日签到积分。已签到时服务端幂等返回 success。"""
        r = self._call("POST", "trae/api/v2/ug/checkin_credits/claim", json_body=self._body())
        if r.ok:
            return r
        r2 = self._call("POST", "trae/api/v2/ug/checkin_credits/claim", json_body=None)
        return r2 if r2.ok else r

    def activity_info(self) -> TraeResult:
        return self._call("POST", "trae/api/v2/ug/activity/info", json_body=self._body())

    def ent_usage(self) -> TraeResult:
        """账户积分额度 / 用量：usage_summary.total_amount - consumed_amount 即余额。"""
        r = self._call("POST", "trae/api/v2/pay/ide_user_ent_usage", json_body=self._body())
        if r.ok:
            return r
        return self._call_auto("trae/api/v2/pay/ide_user_ent_usage", prefer_get=True,
                               json_body=self._body())

    def user_info(self) -> TraeResult:
        """用户资料（昵称 / 用户名 / 邮箱 / 头像）。

        客户端登录后调的是 cloudide 的 GetUserInfo（POST，返回 {Result:{...}}），
        成功后把昵称写进账号，界面就不再显示「账号5xxxx」这种编号名。
        拿不到时退回 iCube 的 /icube/api/v1/user，两个都失败也不算致命——
        签到本身不依赖它。
        """
        r = self._call("POST", "cloudide/api/v3/trae/GetUserInfo",
                       json_body={"ReqSource": "IDE", "IDEVersion": APP_VERSION})
        if r.ok and r.data:
            return r
        r2 = self._call_auto("icube/api/v1/user", prefer_get=True)
        if r2.ok and r2.data:
            return r2
        return r
