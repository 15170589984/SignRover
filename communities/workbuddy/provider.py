"""WorkBuddy 每日签到任务执行器。

任务清单（每日）：
- 每日签到领积分（成功返回 {"credit": 100}，今日已签返回 code=10001）

与社区类 provider 的差异：
- WorkBuddy 是 PC 工具，没有模拟器；凭证从抓包 / 浏览器 F12 手动导入
- 签到是一次接口调用，没有浏览 / 点赞等互动任务
- 需要两个请求头：Authorization（Bearer）与 X-User-Id，后者可从 JWT 里自动解析
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from communities.workbuddy.client import (
    WorkBuddyClient, parse_resource, parse_status, uid_from_jwt)
from core.models import CoinInfo, Credential, MissionItem, TaskKind, TaskResult, TaskStatus
from core.storage import Storage

DEFAULT_DAILY_CREDIT = 100


class WorkBuddyError(RuntimeError):
    pass


@dataclass
class WorkBuddySnapshot:
    daily: list[MissionItem] = field(default_factory=list)
    more: list[MissionItem] = field(default_factory=list)
    coin: CoinInfo = field(default_factory=CoinInfo)
    roles: list = field(default_factory=list)
    signed_boards: dict[str, bool] = field(default_factory=dict)
    checked: bool = False


class WorkBuddyProvider:
    def __init__(self, cred: Credential, storage: Storage | None = None,
                 min_interval: float | None = None):
        if not cred.token:
            raise WorkBuddyError("缺少 WorkBuddy token，请在账号页手动导入"
                                 "（请求头 Authorization 里 Bearer 后面那段）")
        if not cred.uid:
            cred.uid = uid_from_jwt(cred.token)
        if not cred.uid:
            raise WorkBuddyError("缺少 WorkBuddy 的 X-User-Id，请把账号 uid 一起填上"
                                 "（请求头 X-User-Id 的值）")
        if min_interval is None:
            from core.settings import settings
            min_interval = settings().interval
        self.cred = cred
        self.storage = storage
        base = (cred.extra or {}).get("domain") or ""
        self.client = WorkBuddyClient(cred.token, cred.uid, base=base,
                                      min_interval=min_interval)
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

    def _guard(self, r, action: str) -> None:
        if r.token_invalid:
            raise WorkBuddyError(f"{action}失败：登录态已失效，请重新抓包获取\n"
                                 "Authorization 与 X-User-Id 后更新账号")
        if not r.ok and not r.already:
            raise WorkBuddyError(f"{action}失败：{r}")

    # ---------- 快照 ----------
    def _balance(self) -> int:
        r = self.client.resource()
        if not r.ok:
            return -1
        return parse_resource(r.data)

    def snapshot(self, with_sign_state: bool = True) -> WorkBuddySnapshot:
        snap = WorkBuddySnapshot()
        checked, today = None, None
        r = self.client.checkin_status()
        if r.ok or r.already:
            checked, today = parse_status(r.data)
        total = self._balance()
        reward = today if (today or 0) > 0 else DEFAULT_DAILY_CREDIT
        done = bool(checked)
        snap.checked = done
        snap.daily = [MissionItem(
            mission_id=1, name="每日签到",
            desc=f"+{reward} {self.cred.currency}", points=reward, threshold=1,
            happened_times=1 if done else 0,
            is_get_award=done, mission_key="checkin")]
        snap.coin = CoinInfo(
            total=max(total, 0) if total >= 0 else 0,
            today=today if (today or 0) >= 0 else 0,
            can_get=0 if done else reward,
            received=(today or 0) if done else 0, cap=0)
        if self.storage:
            self.storage.add_coin_snapshot(self.cred.key, snap.coin.total, snap.coin.today)
        if with_sign_state:
            snap.signed_boards = {"WorkBuddy": done}
        return snap

    # ---------- 签到 ----------
    def run_checkin(self) -> list[TaskResult]:
        target = "WorkBuddy 每日签到"
        before = None
        rs = self.client.checkin_status()
        if rs.ok or rs.already:
            checked, before = parse_status(rs.data)
            if checked:
                extra = f"，今日已得 {before} {self.cred.currency}" if (before or 0) > 0 else ""
                return [self._record(TaskKind.TOOL_SIGN, target, TaskStatus.SKIPPED,
                                     f"今日已签到{extra}")]

        r = self.client.daily_checkin()
        if r.already:
            return [self._record(TaskKind.TOOL_SIGN, target, TaskStatus.SKIPPED,
                                 f"今日已签到（{r.msg or '服务端返回已领取'}）")]
        self._guard(r, "签到")
        credit = 0
        data = r.data if isinstance(r.data, dict) else {}
        for key in ("credit", "credits", "amount", "reward"):
            v = data.get(key) if isinstance(data, dict) else None
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                credit = int(v)
                break
        if credit <= 0 and (before or 0) >= 0:
            # 响应没带数量：用签到后的状态差值兜底
            rs2 = self.client.checkin_status()
            if rs2.ok or rs2.already:
                _, after = parse_status(rs2.data)
                if after is not None and (before is None or after > before):
                    credit = after - (before or 0)
        return [self._record(TaskKind.TOOL_SIGN, target, TaskStatus.SUCCESS,
                             "签到成功", points=max(credit, 0))]

    def claim_all(self) -> list[TaskResult]:
        return self.run_checkin()

    def build_steps(self, options: dict) -> list[tuple[str, object]]:
        o = options or {}
        steps: list[tuple[str, object]] = []
        if o.get("checkin"):
            steps.append(("每日签到", self.run_checkin))
        return steps


def uid_from_token(token: str) -> str:
    got = uid_from_jwt(token)
    if got:
        return got
    tok = (token or "").strip()
    return hashlib.md5(tok.encode("utf-8")).hexdigest()[:10] if tok else ""


# ---------------- 平台约定接口 ----------------
Provider = WorkBuddyProvider


def prepare_import(cred) -> None:
    # 允许整段粘贴（cURL 或几行请求头），先把 token / uid 抠出来
    from communities.workbuddy.client import parse_pasted
    tok, uid = parse_pasted(cred.token or "")
    if tok:
        cred.token = tok
    if uid and not cred.uid:
        cred.uid = uid

    # uid / 域名能从本机客户端明文带出来的就先带上，用户只填 token
    if not cred.uid or not (cred.extra or {}).get("domain"):
        try:
            from communities.workbuddy.local_auth import read_account
            info = read_account()
        except Exception:
            info = {}
        if not cred.uid and info.get("uid"):
            cred.uid = info["uid"]
        if info.get("domain") and not (cred.extra or {}).get("domain"):
            cred.extra["domain"] = info["domain"]

    # token 留空：自动从本机 WorkBuddy 客户端进程内存里找，
    # 逐个用签到状态接口验证（避免拿到内存里残留的旧 token）
    if not cred.token:
        cred.token = _autodetect_token(cred)
        if cred.token:
            cred.extra["token_source"] = "本机 WorkBuddy 客户端（内存）"

    if not cred.token:
        raise ValueError(
            "没有读到 WorkBuddy 登录态。请先启动并登录 WorkBuddy 客户端再试一次；\n"
            "或手动粘贴：网页版 www.workbuddy.cn 按 F12 → Network，点一次签到，\n"
            "请求右键 Copy as cURL，整段粘进 token 框即可（自动识别）。")
    if not cred.uid:
        cred.uid = uid_from_jwt(cred.token)
    if not cred.uid:
        raise ValueError(
            "还需要 X-User-Id：同一请求头里的 X-User-Id 值（形如 d61cf768-xxxx-…）。\n"
            "粘贴整段 cURL 会自动带出来；本机装了 WorkBuddy 客户端时也会自动读取。")
    # 真实昵称就在 JWT 里（nickname 字段），取不到再留空由用户备注
    if not cred.nickname:
        from communities.workbuddy.client import profile_from_jwt
        cred.nickname = profile_from_jwt(cred.token).get("nickname", "")


def _autodetect_token(cred) -> str:
    """内存扫描 + 接口验证，返回第一个能用的 token；都失败返回空串。"""
    import time as _time

    from communities.workbuddy.client import WorkBuddyClient
    try:
        from communities.workbuddy.local_auth import read_memory_tokens
        candidates = read_memory_tokens()
    except Exception:
        return ""
    for tok in candidates[:6]:
        try:
            with WorkBuddyClient(tok, cred.uid or "") as c:
                r = c.checkin_status()
            if r.ok:
                return tok
        except Exception:
            pass
        _time.sleep(0.4)
    return ""
