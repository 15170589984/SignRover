"""Qoder 每日签到任务执行器。

任务清单（每日）：
- 领取当轮签到奖励（100 Credits，10:00 UTC+8 滚动，领取后 30 天有效）

与社区类 provider 的差异：
- Qoder 是 PC 工具，没有模拟器；凭证优先从本机客户端登录态自动读取，
  读不到再手动粘贴 token
- 只有一次「领活动奖励」的接口调用，没有浏览 / 点赞等互动任务
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field

from communities.qoder.client import BASE_CN, BASE_INTL, QoderClient, uid_of
from communities.qoder.client import campaign_amount, parse_usage, pick_campaign
from core.models import CoinInfo, Credential, MissionItem, TaskKind, TaskResult, TaskStatus
from core.storage import Storage


class QoderError(RuntimeError):
    pass


@dataclass
class QoderSnapshot:
    daily: list[MissionItem] = field(default_factory=list)
    more: list[MissionItem] = field(default_factory=list)
    coin: CoinInfo = field(default_factory=CoinInfo)
    roles: list = field(default_factory=list)
    signed_boards: dict[str, bool] = field(default_factory=dict)
    checked: bool = False


class QoderProvider:
    def __init__(self, cred: Credential, storage: Storage | None = None,
                 min_interval: float | None = None):
        if not cred.token:
            raise QoderError("缺少 Qoder token：可以让程序自动读取本机 Qoder 客户端登录态，"
                             "或在账号页手动粘贴 token（Bearer 后面那段，dt- 开头）")
        if min_interval is None:
            from core.settings import settings
            min_interval = settings().interval
        self.cred = cred
        self.storage = storage
        # 国内版 / 国际版是两套独立服务，token 不通用，域名必须跟着账号走
        base = (cred.extra or {}).get("base") or BASE_CN
        self.client = QoderClient(cred.token, base=base, min_interval=min_interval)
        self._log: list[str] = []

    def close(self) -> None:
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def log(self, msg: str) -> None:
        self._log.append(msg)

    # ---------- 记账 ----------
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
            raise QoderError(f"{action}失败：登录态已失效。"
                             "请打开一次 Qoder 客户端重新登录，或手动粘贴新的 token")
        if not r.ok:
            raise QoderError(f"{action}失败：{r}")

    # ---------- 快照 ----------
    def _state(self) -> tuple[int, dict | None, int]:
        """返回 (余额, 当轮活动, 当轮奖励数)。"""
        total = 0
        r = self.client.usage()
        if r.ok:
            total, _, _ = parse_usage(r.data)
        c = None
        rc = self.client.campaigns()
        if rc.ok:
            c = pick_campaign(rc.data)
        return total, c, campaign_amount(c)

    def snapshot(self, with_sign_state: bool = True) -> QoderSnapshot:
        snap = QoderSnapshot()
        total, c, amount = self._state()
        claimed = str((c or {}).get("claimStatus") or "").upper() == "CLAIMED"
        snap.checked = claimed
        desc = f"+{amount} {self.cred.currency}（领后 30 天有效）" if amount else self.cred.currency
        snap.daily = [MissionItem(
            mission_id=1, name="每日领取 Credits",
            desc=desc, points=amount, threshold=1,
            happened_times=1 if claimed else 0,
            is_get_award=claimed, mission_key="checkin")]
        snap.coin = CoinInfo(
            total=max(total, 0),
            today=amount if claimed else 0,
            can_get=0 if claimed else amount,
            received=amount if claimed else 0, cap=0)
        if self.storage:
            self.storage.add_coin_snapshot(self.cred.key, snap.coin.total, snap.coin.today)
        if with_sign_state:
            snap.signed_boards = {"Qoder": claimed}
        return snap

    # ---------- 签到 ----------
    def run_checkin(self) -> list[TaskResult]:
        target = "Qoder 每日领取"
        total_before = -1
        ru = self.client.usage()
        if ru.ok:
            total_before, _, _ = parse_usage(ru.data)

        rc = self.client.campaigns()
        self._guard(rc, "查询签到活动")
        c = pick_campaign(rc.data)
        if not c:
            return [self._record(TaskKind.TOOL_SIGN, target, TaskStatus.SKIPPED,
                                 "当前没有可领取的签到活动（每日 10:00 UTC+8 刷新新一轮）")]
        amount = campaign_amount(c)
        status = str(c.get("claimStatus") or "").upper()
        if status == "CLAIMED":
            extra = f"，今日已得 {amount} {self.cred.currency}" if amount else ""
            return [self._record(TaskKind.TOOL_SIGN, target, TaskStatus.SKIPPED,
                                 f"今日已领取{extra}")]

        r = self.client.claim(str(c.get("campaignId") or ""))
        self._guard(r, "领取奖励")
        data = r.data if isinstance(r.data, dict) else {}
        got = campaign_amount({"benefit": data.get("benefit")}) if data.get("benefit") else amount
        if data.get("replayed"):
            return [self._record(TaskKind.TOOL_SIGN, target, TaskStatus.SKIPPED,
                                 f"今日已领取（服务端回放），{got} {self.cred.currency} 此前已到账")]

        # claim 没带数量时，用领取前后余额差值兜底
        if got <= 0:
            time.sleep(0.5)
            ra = self.client.usage()
            after, _, _ = parse_usage(ra.data) if ra.ok else (0, 0, 0)
            if total_before >= 0 and after > total_before:
                got = after - total_before
        return [self._record(TaskKind.TOOL_SIGN, target, TaskStatus.SUCCESS,
                             "领取成功", points=max(got, 0))]

    def claim_all(self) -> list[TaskResult]:
        return self.run_checkin()

    def build_steps(self, options: dict) -> list[tuple[str, object]]:
        o = options or {}
        steps: list[tuple[str, object]] = []
        if o.get("checkin"):
            steps.append(("每日领取", self.run_checkin))
        return steps


def uid_from_token(token: str) -> str:
    tok = (token or "").strip()
    return hashlib.md5(tok.encode("utf-8")).hexdigest()[:10] if tok else ""


# ---------------- 平台约定接口 ----------------
Provider = QoderProvider


def _probe(token: str, bases: list[str]) -> tuple[str, str]:
    """逐个域名试 token，返回 (可用域名, userId)。

    token 只在签发它的那套服务上有效：国内版 token 打到国际域名会 401，
    反之亦然。所以不能写死一个域名，也不能"猜错就当成功"。
    """
    for base in bases:
        try:
            c = QoderClient(token, base=base, min_interval=0)
            r = c.usage()
            c.close()
        except Exception:
            continue
        if r.ok:
            return base, uid_of(r.data)
        if not r.token_invalid:
            # 域名能通、只是暂时出错（5xx / 网络），别再换域名了
            return base, ""
    return "", ""


def prepare_import(cred) -> None:
    """token 留空时自动读本机 Qoder 客户端登录态；仍拿不到就要求手动填。

    域名处理：Qoder 国内版（openapi.qoder.com.cn）和国际版（openapi.qoder.sh）
    是两套独立服务，token 不通用。导入时按「账号里记的 → 本机客户端目录 →
    国内 → 国际」依次探测，命中哪个就把域名写进 cred.extra["base"]，
    任务执行时用它发请求。两个域名都判 token 失效才报错，不会存一个用不上的账号。
    """
    local_name = local_uid = local_base = ""
    if not cred.token:
        from communities.qoder.local_auth import read_desktop_token
        token, info = read_desktop_token()
        if token:
            cred.token = token
            cred.extra["token_source"] = "本机 Qoder 客户端"
            local_base = str(info.get("base") or "")
            if info.get("expiresAt"):
                cred.extra["token_expires"] = str(info["expiresAt"])
            local_name = str(info.get("user_name") or "")
            local_uid = str(info.get("user_id") or "")
    if not cred.token:
        raise ValueError(
            "没有读到 Qoder 登录态。请先打开并登录 Qoder 客户端，或手动粘贴 token：\n"
            "  · 桌面端登录态里的设备令牌以 dt- 开头\n"
            "  · 抓包时取请求头 Authorization 里 Bearer 后面那段")

    bases: list[str] = []
    for b in ((cred.extra or {}).get("base"), local_base, BASE_CN, BASE_INTL):
        if b and b not in bases:
            bases.append(b)
    base, uid = _probe(cred.token, bases)
    if not base:
        raise ValueError(
            "这个 Qoder token 已失效（国内版 openapi.qoder.com.cn 和国际版 "
            "openapi.qoder.sh 都试过了）。\n请打开 Qoder 客户端重新登录后再获取一次；"
            "抓包时用最新的请求，旧包里的 token 可能已经轮换。")
    cred.extra["base"] = base
    cred.extra["domain"] = "国内版" if base == BASE_CN else "国际版"
    if not uid:
        uid = local_uid
    cred.uid = uid or uid_from_token(cred.token)
    if not cred.nickname:
        cred.nickname = local_name
