"""Qoder（AI 编程 IDE）签到协议客户端。

端点与字段按 Qoder CN（2026-11）真实响应校准：

- 域名：`https://openapi.qoder.com.cn`（国际版为 openapi.qoder.sh，结构一致）
- 鉴权：`Authorization: Bearer <token>`。桌面端登录态里的 `dt-` 设备令牌可以直接用，
  不需要先换 jobToken；在控制台申请的 PAT 同样走 Bearer。
- 每日奖励是「活动」形式：10:00(UTC+8) 滚动一轮，每轮 100 Credits，领取后 30 天有效。

实测端点：
- GET  /sash/api/v2/me/usage                      额度用量
- GET  /sash/api/v1/me/campaigns                  活动列表（含领取状态）
- POST /sash/api/v1/me/campaigns/{campaignId}/claim  领取（幂等，重复领 replayed=true）
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass

import httpx

from core.http import ssl_verify

BASE_CN = "https://openapi.qoder.com.cn"
BASE_INTL = "https://openapi.qoder.sh"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) QoderCN/0.5.2 Chrome/150.0.7871.114 "
      "Electron/43.1.1 Safari/537.36")


@dataclass
class QoderResult:
    code: str = ""            # 上游错误码，如 TOKEN_INVALID
    msg: str = ""
    data: object = None
    http_status: int = 0
    raw: str = ""

    @property
    def ok(self) -> bool:
        return self.http_status == 200 and not self.code

    @property
    def token_invalid(self) -> bool:
        return self.http_status in (401, 403) or self.code in ("TOKEN_INVALID", "UNAUTHORIZED")

    def __str__(self) -> str:
        if self.code:
            return f"{self.code} {self.msg}".strip()
        return f"HTTP {self.http_status} {self.msg}".strip()


def _f(v, default: float = 0.0) -> float:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else default


class QoderClient:
    def __init__(self, token: str, base: str = BASE_CN,
                 timeout: float = 20.0, min_interval: float = 1.0):
        tok = (token or "").strip()
        for prefix in ("bearer ", "Bearer "):
            if tok.lower().startswith(prefix.strip().lower()):
                tok = tok[len(prefix):].strip()
        self.token = tok
        self.base = (base or BASE_CN).rstrip("/")
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
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Cosy-ClientType": "10",
            "User-Agent": UA,
        }

    def _throttle(self) -> None:
        gap = time.monotonic() - self._last
        if gap < self.min_interval:
            time.sleep(self.min_interval - gap)
        self._last = time.monotonic()

    def _call(self, method: str, path: str, json_body: dict | None = None,
              retries: int = 1) -> QoderResult:
        url = f"{self.base}{path}"
        last = QoderResult(msg="未执行")
        for attempt in range(retries + 1):
            self._throttle()
            try:
                r = self.http.request(method, url, json=json_body, headers=self._headers())
                body = (r.text or "")[:600]
                if r.status_code != 200:
                    code, msg = "", f"HTTP {r.status_code}"
                    try:
                        j = r.json()
                        code = str(j.get("code") or "")
                        msg = str(j.get("message") or msg)
                    except (json.JSONDecodeError, ValueError):
                        pass
                    last = QoderResult(code=code, msg=msg, http_status=r.status_code, raw=body)
                else:
                    try:
                        j = r.json()
                    except (json.JSONDecodeError, ValueError):
                        return QoderResult(msg="返回非 JSON", http_status=200, raw=body)
                    last = QoderResult(data=j, http_status=200, raw=body)
            except httpx.HTTPError as e:
                last = QoderResult(msg=f"{type(e).__name__}: {e}")
            if last.ok or last.token_invalid or attempt >= retries:
                return last
            time.sleep(1.5)
        return last

    # ---------- 业务端点 ----------
    def usage(self) -> QoderResult:
        """额度用量：qoderUsage.userQuota + addOnQuota。"""
        return self._call("GET", "/sash/api/v2/me/usage")

    def campaigns(self) -> QoderResult:
        return self._call("GET", "/sash/api/v1/me/campaigns")

    def claim(self, campaign_id: str) -> QoderResult:
        """领取某轮活动奖励。服务端幂等：重复领取返回 replayed=true。"""
        return self._call("POST", f"/sash/api/v1/me/campaigns/{campaign_id}/claim", json_body={})


# ---------------- 响应解析 ----------------
def parse_usage(data) -> tuple[int, int, str]:
    """返回 (剩余积分, 套餐内剩余, 加购包剩余)。"""
    u = (data or {}).get("qoderUsage") or {}
    plan = u.get("userQuota") or {}
    addon = u.get("addOnQuota") or {}
    plan_left = int(round(_f(plan.get("remaining"))))
    addon_left = int(round(_f(addon.get("remaining"))))
    return plan_left + addon_left, plan_left, addon_left


def uid_of(data) -> str:
    u = (data or {}).get("qoderUsage") or {}
    return str(u.get("userId") or "")


def pick_campaign(data, now: float | None = None) -> dict | None:
    """挑出当前时间窗内、领取积分的那一轮活动。

    活动窗口的 startAt/endAt 是**秒级**时间戳。窗口内优先；都不在窗口内时，
    退一步返回最近一轮 CLAIM_BENEFIT，交给调用方判断是否已领。
    """
    now = time.time() if now is None else now
    items = [c for c in ((data or {}).get("campaigns") or [])
             if isinstance(c, dict) and c.get("actionType") == "CLAIM_BENEFIT"]
    if not items:
        return None
    for c in items:
        start, end = _f(c.get("startAt")), _f(c.get("endAt"))
        if start <= now <= end:
            return c
    items.sort(key=lambda c: _f(c.get("startAt")), reverse=True)
    return items[0]


def campaign_amount(c: dict | None) -> int:
    benefit = (c or {}).get("benefit") or {}
    return int(round(_f(benefit.get("amount"))))
