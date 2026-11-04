"""Trae 每日签到任务执行器。

任务清单（每日）：
- 签到领取积分（checkin_credits/claim）

与社区类 provider 的差异：
- Trae 是 PC 工具，没有模拟器，凭证（token）从抓包工具手动导入
- 签到就是一次接口调用，没有浏览 / 点赞等互动任务
"""
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field

from communities.trae.client import (
    AMOUNT_KEYS, CHECKED_KEYS, NAME_KEYS, TraeClient, TraeResult, find_first)
from core.models import CoinInfo, Credential, MissionItem, TaskKind, TaskResult, TaskStatus
from core.storage import Storage


class TraeError(RuntimeError):
    pass


@dataclass
class TraeSnapshot:
    daily: list[MissionItem] = field(default_factory=list)
    more: list[MissionItem] = field(default_factory=list)
    coin: CoinInfo = field(default_factory=CoinInfo)
    roles: list = field(default_factory=list)          # Trae 没有游戏角色
    signed_boards: dict[str, bool] = field(default_factory=dict)
    checked: bool = False


class TraeProvider:
    def __init__(self, cred: Credential, storage: Storage | None = None,
                 min_interval: float | None = None):
        if not cred.token:
            raise TraeError("缺少 Trae token，请在账号页手动导入"
                            "（抓包 Authorization 头 Cloud-IDE-JWT 后面的值）")
        if min_interval is None:
            from core.settings import settings
            min_interval = settings().interval
        self.cred = cred
        self.storage = storage
        self.client = TraeClient(cred.token, min_interval=min_interval)
        # x-device-id 必须用本机 Trae 客户端注册过的真实设备号，
        # 随机编的号领取必回 9074「当前参与用户太多」（见 local_auth.py 的说明）
        try:
            from communities.trae.local_auth import read_client_device_id
            did = read_client_device_id()
        except Exception:
            did = ""
        if did:
            self.client.device_id = did
        self._log: list[str] = []

    def close(self) -> None:
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def log(self, msg: str) -> None:
        self._log.append(msg)

    def _record(self, kind: TaskKind, target: str, status: TaskStatus,
                message: str, points: int = 0) -> TaskResult:
        currency = self.cred.currency
        run_id = 0
        if self.storage:
            run_id = self.storage.add_run(self.cred.key, kind.value, target, status.value,
                                          message, points, currency)
        return TaskResult(kind=kind, target=target, status=status, message=message,
                          points=points, currency=currency, run_id=run_id)

    def _guard(self, r: TraeResult, action: str) -> None:
        if r.token_invalid:
            raise TraeError(
                f"{action}失败：token 已失效，请重新抓包获取 Trae 的"
                " Cloud-IDE-JWT 值后更新账号")
        if not r.ok:
            raise TraeError(f"{action}失败：{r}")

    # ---------- 快照 ----------
    def _status(self) -> tuple[bool, int, TraeResult]:
        """返回 (今日已签, 今日已得积分, 原始结果)。"""
        r = self.client.checkin_status()
        if not r.ok:
            return False, -1, r
        checked = bool(find_first(r.data, CHECKED_KEYS, only_bool=True))
        amount = find_first(r.data, AMOUNT_KEYS, only_int=True, substr=True)
        return checked, int(amount) if amount is not None else -1, r

    def _balance(self) -> int:
        """积分余额 = usage_summary.total_amount - consumed_amount（实测结构）。"""
        r = self.client.ent_usage()
        if not r.ok or not isinstance(r.data, dict):
            return -1
        summary = r.data.get("usage_summary") or {}
        total = summary.get("total_amount")
        used = summary.get("consumed_amount")
        if isinstance(total, (int, float)):
            return int(round(total - (used if isinstance(used, (int, float)) else 0)))
        bal = find_first(r.data, AMOUNT_KEYS, only_int=True, substr=True)
        return int(bal) if bal is not None else -1

    def _reward(self) -> int:
        """签到每天可领多少积分：activity 列表里 checkin_credits 的 work_credits。"""
        r = self.client.activity_info()
        if not r.ok or not isinstance(r.data, dict):
            return 0
        for act in r.data.get("commercial_activities") or []:
            if isinstance(act, dict) and act.get("activity_id") == "checkin_credits":
                extra = act.get("work_extra") or {}
                for key in ("work_credits", "general_credits"):
                    v = extra.get(key)
                    if isinstance(v, (int, float)) and v > 0:
                        return int(v)
        return 0

    def snapshot(self, with_sign_state: bool = True) -> TraeSnapshot:
        snap = TraeSnapshot()
        checked, amount, _ = self._status()
        snap.checked = checked
        total = self._balance()
        reward = self._reward()
        # Trae 只有一个签到任务
        snap.daily = [MissionItem(
            mission_id=1, name="每日签到",
            desc=f"+{reward} {self.cred.currency}" if reward else self.cred.currency,
            points=reward, threshold=1,
            happened_times=1 if checked else 0,
            is_get_award=checked, mission_key="checkin")]
        snap.coin = CoinInfo(
            total=max(total, 0), today=amount if amount >= 0 else 0,
            can_get=0 if checked else reward, received=amount if checked and amount >= 0 else 0,
            cap=0)
        if self.storage:
            self.storage.add_coin_snapshot(self.cred.key, snap.coin.total, snap.coin.today)
        if with_sign_state:
            snap.signed_boards = {"Trae": checked}
        return snap

    # ---------- 签到 ----------
    # 服务端高峰期限流：code=9074「当前参与用户太多，请稍后再试」。
    # 实测退避几轮大多能挤过去；全失败时提示用户稍后再点一次。
    BUSY_CODES = {9074, 9095}
    BUSY_HINT = ("领取被服务端拒绝（9074：当前参与用户太多）。这句提示是幌子，"
                 "真实原因是设备号没过校验：本机需要装有并登录过 Trae 客户端"
                 "（程序会自动读取它注册的设备号）。注意同一个设备号一天只能"
                 "给一个账号签到，多账号请各用各的机器。")

    def run_checkin(self) -> list[TaskResult]:
        checked, amount, _ = self._status()
        if checked:
            extra = f"，今日已得 {amount} {self.cred.currency}" if amount >= 0 else ""
            return [self._record(TaskKind.TOOL_SIGN, "Trae 每日签到", TaskStatus.SKIPPED,
                                 f"今日已签到{extra}")]
        delay, tries = 4.0, 5
        r = None
        for attempt in range(tries):
            r = self.client.checkin_claim()
            if r.ok or r.token_invalid:
                break
            busy = r.code in self.BUSY_CODES or "太多" in (r.msg or "")
            if not busy or attempt >= tries - 1:
                break
            time.sleep(delay)
            delay = min(delay * 1.5, 10.0)
        if r is None:
            r = self.client.checkin_claim()
        if r.token_invalid:
            raise TraeError("签到失败：token 已失效，请重新抓包更新 Trae 凭证")
        if r.ok:
            got = find_first(r.data, AMOUNT_KEYS, only_int=True, substr=True)
            got = int(got) if got is not None else 0
            res = self._record(TaskKind.TOOL_SIGN, "Trae 每日签到", TaskStatus.SUCCESS,
                               "签到成功", points=max(got, 0))
            if got <= 0 and amount >= 0:
                # claim 响应没带数量，用签到前后 status 的差值补
                _, amount2, _ = self._status()
                if amount2 > amount >= 0:
                    res.points = amount2 - amount
                    if self.storage and res.run_id:
                        self.storage.set_run_points(res.run_id, res.points)
            return [res]
        msg = f"领取失败：{r}"
        if r.code in self.BUSY_CODES or "太多" in (r.msg or ""):
            msg += f"\n{self.BUSY_HINT}"
        return [self._record(TaskKind.TOOL_SIGN, "Trae 每日签到", TaskStatus.FAILED, msg)]

    # 兼容 build_steps 的默认入口名
    def claim_all(self) -> list[TaskResult]:
        return self.run_checkin()

    def build_steps(self, options: dict) -> list[tuple[str, object]]:
        """把任务页的勾选项翻译成执行步骤。"""
        o = options or {}
        steps: list[tuple[str, object]] = []
        if o.get("checkin"):
            steps.append(("每日签到", self.run_checkin))
        return steps


def uid_from_token(token: str) -> str:
    """Trae 没有 userId 概念，用 token 指纹当账号键（同一 token 去重）。"""
    tok = (token or "").strip().removeprefix("Bearer ").removeprefix("bearer ")
    return hashlib.md5(tok.encode("utf-8")).hexdigest()[:10] if tok else ""


def real_uid_from_token(token: str) -> str:
    """从 Cloud-IDE-JWT 的 payload 里取真实用户 id（data.id，如 854765825179040）。

    比 token 指纹好：token 会随重新登录刷新，指纹跟着变，同一账号会被
    误认成新账号；JWT 里的 data.id 是稳定的。取不到返回空串。
    """
    import base64
    import json
    tok = (token or "").strip()
    for prefix in ("Cloud-IDE-JWT ", "Bearer ", "bearer "):
        if tok.startswith(prefix):
            tok = tok[len(prefix):].strip()
    parts = tok.split(".")
    if len(parts) < 2:
        return ""
    seg = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(seg).decode("utf-8"))
    except Exception:
        return ""
    if not isinstance(payload, dict):
        return ""
    data = payload.get("data")
    if isinstance(data, dict) and data.get("id"):
        return str(data["id"])
    for key in ("uid", "userId", "user_id", "id", "sub"):
        v = payload.get(key)
        if isinstance(v, str) and v:
            return v
    return ""


# ---------------- 平台约定接口 ----------------
Provider = TraeProvider


# Trae 客户端把 token 放在 Authorization: Cloud-IDE-JWT <token> 里发出去，
# 内存里以这个前缀成对出现，按前缀抓比裸找 JWT 更准
_CLOUD_IDE_RE = re.compile(rb"Cloud-IDE-JWT[=:;\s\x00]*([A-Za-z0-9_\-\.]{24,})")


def prepare_import(cred) -> None:
    """导入 Trae 凭证：token 留空时自动读本机 Trae 客户端内存，读不到再要求粘贴。"""
    if not cred.token:
        cred.token = _autodetect_token(cred)
        if cred.token:
            cred.extra["token_source"] = "本机 Trae 客户端（内存）"
    if not cred.token:
        raise ValueError(
            "没有读到 Trae 登录态。请先启动并登录 Trae 客户端，再点一次「导入」；\n"
            "或手动粘贴：抓包工具里 Authorization 请求头的值\n"
            "（Cloud-IDE-JWT 开头，整段粘贴即可，带不带前缀都认）。")
    # uid 优先用 JWT 里的真实用户 id（跨 token 刷新稳定），取不到退回 token 指纹
    cred.uid = real_uid_from_token(cred.token) or uid_from_token(cred.token)


def _autodetect_token(cred) -> str:
    """扫本机 Trae 进程内存拿候选 token，逐个用签到状态接口验证。"""
    from core import winmem
    if not winmem.available():
        return ""
    candidates: list[str] = []
    try:
        candidates += winmem.scan_for_pattern(_CLOUD_IDE_RE, ("trae",), group=1)
    except Exception:
        pass
    try:
        candidates += winmem.scan_for_jwt(("trae",))
    except Exception:
        pass
    for tok in candidates[:8]:
        try:
            c = TraeClient(tok)
            r = c.checkin_status()
            c.close()
            if r.ok or (r.http_status == 200 and not r.token_invalid):
                return tok
        except Exception:
            pass
        time.sleep(0.4)
    return ""
