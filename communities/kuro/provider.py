"""库街区任务执行器。

任务清单（每日，合计 80 库洛币）：
- 用户签到      +30
- 浏览 3 篇帖子 +20
- 点赞 5 次     +20
- 分享 1 次帖子 +10

和米游社最大的区别：这四项全部由服务端按接口调用记账，纯协议即可完成，
不需要驱动模拟器里的 App。
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field

from communities.kuro.boards import DEFAULT_FORUM, FORUMS
from communities.kuro.client import KuroClient, KuroPost, KuroRole
from core.models import CoinInfo, Credential, MissionItem, TaskKind, TaskResult, TaskStatus
from core.storage import Storage


class KuroError(RuntimeError):
    pass


@dataclass
class KuroSnapshot:
    daily: list[MissionItem] = field(default_factory=list)
    more: list[MissionItem] = field(default_factory=list)
    coin: CoinInfo = field(default_factory=CoinInfo)
    roles: list[KuroRole] = field(default_factory=list)
    signed_boards: dict[str, bool] = field(default_factory=dict)


# 任务备注 → (任务类型, 每日上限)
TASK_MAP = {
    "用户签到": (TaskKind.BBS_SIGN, 1),
    "浏览3篇帖子": (TaskKind.BROWSE, 3),
    "点赞5次": (TaskKind.LIKE, 5),
    "分享1次帖子": (TaskKind.SHARE, 1),
}


class KuroProvider:
    def __init__(self, cred: Credential, storage: Storage | None = None,
                 min_interval: float | None = None):
        if not cred.token:
            raise KuroError("缺少库街区 token，请重新从模拟器提取凭证")
        if min_interval is None:
            from core.settings import settings
            min_interval = settings().interval
        self.cred = cred
        self.storage = storage
        self.client = KuroClient(cred.token, uid_of(cred), min_interval=min_interval)
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

    def _distribute(self, results: list[TaskResult], delta: int) -> None:
        """把这一组动作真实到账的币，平摊到成功的记录上（合计恰好等于 delta）。

        单条接口只返回「成功」，具体进多少币要到任务进度里看，所以用前后差值：
        既不会虚报，也不用在代码里硬编码每步的奖励数。
        """
        if delta <= 0:
            return
        targets = [r for r in results if r.status is TaskStatus.SUCCESS and not r.points]
        if not targets:
            return
        base, rest = divmod(int(delta), len(targets))
        for i, r in enumerate(targets):
            r.points = base + (1 if i < rest else 0)
            r.currency = self.cred.currency
            if self.storage and r.run_id:
                self.storage.set_run_points(r.run_id, r.points)

    def _today_gold(self) -> int:
        """当前今日已得币；拿不到返回 -1（表示没法算差额）。"""
        try:
            _, today, _ = self.task_progress()
            return int(today)
        except KuroError:
            return -1

    @staticmethod
    def _gap(tasks: list[MissionItem], remark: str, default: int) -> int:
        for t in tasks:
            if t.name == remark:
                return max(0, t.threshold - t.happened_times)
        return default

    def _guard(self, r, action: str) -> None:
        """统一处理 token 失效与风控。"""
        if r.token_invalid:
            raise KuroError(f"{action}失败：token 已失效，请在模拟器里重新登录库街区后重新提取凭证")

    # ---------- 快照 ----------
    def task_progress(self) -> tuple[list[MissionItem], int, int]:
        """返回 (任务列表, 今日已得, 每日上限)。"""
        r = self.client.task_process()
        self._guard(r, "获取任务进度")
        if not r.ok or not isinstance(r.data, dict):
            raise KuroError(f"获取任务进度失败：{r}")
        d = r.data
        items: list[MissionItem] = []
        for i, t in enumerate(d.get("dailyTask", []) or [], 1):
            remark = t.get("remark", "") or f"任务{i}"
            need = int(t.get("needActionTimes", 0) or 0)
            done = int(t.get("completeTimes", 0) or 0)
            items.append(MissionItem(
                mission_id=i,
                name=remark,
                desc=f"+{t.get('gainGold', 0)} {self.cred.currency}",
                points=int(t.get("gainGold", 0) or 0),
                threshold=need,
                happened_times=done,
                # 库街区完成任务即时到账，没有「待领取」状态
                is_get_award=need > 0 and done >= need,
                mission_key=remark,
            ))
        return items, int(d.get("currentDailyGold", 0) or 0), int(d.get("maxDailyGold", 0) or 0)

    def account_info(self) -> dict:
        r = self.client.mine()
        self._guard(r, "获取账号信息")
        if r.ok and isinstance(r.data, dict):
            return r.data.get("mine", {}) or {}
        return {}

    def roles(self) -> list[KuroRole]:
        return self.client.default_roles()

    def snapshot(self, with_sign_state: bool = True) -> KuroSnapshot:
        snap = KuroSnapshot()
        info = self.account_info()
        tasks, today, cap = self.task_progress()
        snap.daily = tasks
        snap.coin = CoinInfo(
            total=int(info.get("goldNum", 0) or 0),
            today=today,
            can_get=max(0, cap - today),
            received=today,
            cap=cap,
        )
        if info.get("userName") and not self.cred.nickname:
            self.cred.nickname = info["userName"]
        snap.roles = self.roles()
        if self.storage:
            self.storage.add_coin_snapshot(self.cred.key, snap.coin.total, snap.coin.today)
        if with_sign_state:
            bbs = next((t for t in tasks if t.name == "用户签到"), None)
            snap.signed_boards = {"库街区": bool(bbs and bbs.is_get_award)}
        return snap

    # ---------- 取帖子 ----------
    def _fresh_posts(self, limit: int = 20) -> list[KuroPost]:
        """从各分版取最新帖子，去重后返回。"""
        seen: dict[str, KuroPost] = {}
        for f in FORUMS:
            for p in self.client.forum_posts(f.game_id, f.forum_id, page_size=max(limit, 20)):
                seen.setdefault(p.post_id, p)
            if len(seen) >= limit:
                break
        return list(seen.values())[:limit]

    def _state(self) -> tuple[list[MissionItem], int]:
        """一次拿到任务进度和今日已得币；失败时币数返回 -1（不做差额填充）。"""
        try:
            items, today, _ = self.task_progress()
            return items, int(today)
        except KuroError:
            return [], -1

    # ---------- 社区签到 ----------
    def run_bbs_sign(self, gids: list[str] | None = None) -> list[TaskResult]:
        tasks, gold0 = self._state()
        if self._gap(tasks, "用户签到", 1) == 0:
            return [self._record(TaskKind.BBS_SIGN, "库街区签到", TaskStatus.SKIPPED,
                                 "今日已签到")]
        r = self.client.bbs_sign()
        self._guard(r, "社区签到")
        if r.ok:
            d = r.data or {}
            results = [self._record(
                TaskKind.BBS_SIGN, "库街区签到", TaskStatus.SUCCESS,
                f"签到成功（连续 {d.get('continueDays', '?')} 天）")]
        elif r.code == 1551:
            results = [self._record(TaskKind.BBS_SIGN, "库街区签到", TaskStatus.SKIPPED,
                                    "今日已签到")]
        else:
            return [self._record(TaskKind.BBS_SIGN, "库街区签到", TaskStatus.FAILED, str(r))]
        if gold0 >= 0:
            gained = self._today_gold()
            if gained >= 0:
                self._distribute(results, gained - gold0)
        return results

    # ---------- 游戏签到 ----------
    def run_game_sign(self, game_ids: list[str] | None = None) -> list[TaskResult]:
        results: list[TaskResult] = []
        roles = [r for r in self.roles() if not game_ids or r.game_id in game_ids]
        if not roles:
            return [self._record(TaskKind.GAME_SIGN, "游戏签到", TaskStatus.SKIPPED,
                                 "未找到库街区绑定的游戏角色")]
        month = f"{datetime.date.today().month:02d}"
        for role in roles:
            label = f"{role.game_name}（{role.name or role.role_id}）"
            info = self.client.game_sign_info(role)
            self._guard(info, f"{role.game_name}签到")
            if not info.ok or not isinstance(info.data, dict):
                results.append(self._record(TaskKind.GAME_SIGN, label, TaskStatus.FAILED,
                                            f"查询失败：{info}"))
                continue
            d = info.data
            days = int(d.get("sigInNum", 0) or 0)
            if d.get("isSigIn"):
                results.append(self._record(TaskKind.GAME_SIGN, label, TaskStatus.SKIPPED,
                                            f"今日已签到（本月 {days} 天）"))
                continue
            r = self.client.game_sign(role, month)
            self._guard(r, f"{role.game_name}签到")
            if r.ok:
                results.append(self._record(TaskKind.GAME_SIGN, label, TaskStatus.SUCCESS,
                                            f"签到成功（本月 {days + 1} 天）"))
            elif r.code == 1511:
                results.append(self._record(TaskKind.GAME_SIGN, label, TaskStatus.SKIPPED,
                                            "今日已签到"))
            else:
                results.append(self._record(TaskKind.GAME_SIGN, label, TaskStatus.FAILED, str(r)))
        return results

    # ---------- 浏览 ----------
    def run_browse(self, need: int | None = None) -> list[TaskResult]:
        tasks, gold0 = self._state()
        gap = self._gap(tasks, "浏览3篇帖子", 3) if need is None else need
        if gap <= 0:
            return [self._record(TaskKind.BROWSE, "浏览帖子", TaskStatus.SKIPPED, "今日已完成")]
        posts = self._fresh_posts(limit=max(gap + 3, 6))
        if not posts:
            return [self._record(TaskKind.BROWSE, "浏览帖子", TaskStatus.FAILED,
                                 "拉取帖子列表为空")]
        results: list[TaskResult] = []
        done = 0
        for p in posts:
            if done >= gap:
                break
            r = self.client.post_detail(p.post_id)
            self._guard(r, "浏览帖子")
            title = p.title[:14] or p.post_id
            if r.ok:
                done += 1
                results.append(self._record(TaskKind.BROWSE, f"《{title}》",
                                            TaskStatus.SUCCESS, "已阅读"))
            elif r.code == 522:
                continue          # 帖子被删，换下一篇
            else:
                results.append(self._record(TaskKind.BROWSE, f"《{title}》",
                                            TaskStatus.FAILED, str(r)))
        if done < gap:
            results.append(self._record(TaskKind.BROWSE, "浏览汇总", TaskStatus.FAILED,
                                        f"只完成 {done}/{gap} 篇"))
        return self._finish(results, gold0)

    # ---------- 点赞 ----------
    def run_like(self, need: int | None = None) -> list[TaskResult]:
        tasks, gold0 = self._state()
        gap = self._gap(tasks, "点赞5次", 5) if need is None else need
        if gap <= 0:
            return [self._record(TaskKind.LIKE, "点赞帖子", TaskStatus.SKIPPED, "今日已完成")]
        posts = self._fresh_posts(limit=max(gap * 2, 10))
        if not posts:
            return [self._record(TaskKind.LIKE, "点赞帖子", TaskStatus.FAILED,
                                 "拉取帖子列表为空")]
        results: list[TaskResult] = []
        done = 0
        for p in posts:
            if done >= gap:
                break
            title = p.title[:14] or p.post_id
            # 已经赞过的帖子再赞不会加进度，先取消再点赞
            if p.is_liked:
                self.client.like(p.post_id, p.user_id, on=False)
            r = self.client.like(p.post_id, p.user_id, on=True)
            self._guard(r, "点赞帖子")
            if r.ok:
                done += 1
                results.append(self._record(TaskKind.LIKE, f"《{title}》",
                                            TaskStatus.SUCCESS, "已点赞"))
            elif r.code == 522:
                continue
            else:
                results.append(self._record(TaskKind.LIKE, f"《{title}》",
                                            TaskStatus.FAILED, str(r)))
        if done < gap:
            results.append(self._record(TaskKind.LIKE, "点赞汇总", TaskStatus.FAILED,
                                        f"只完成 {done}/{gap} 次"))
        return self._finish(results, gold0)

    # ---------- 分享 ----------
    def run_share(self, need: int | None = None) -> list[TaskResult]:
        tasks, gold0 = self._state()
        gap = self._gap(tasks, "分享1次帖子", 1) if need is None else need
        if gap <= 0:
            return [self._record(TaskKind.SHARE, "分享帖子", TaskStatus.SKIPPED, "今日已完成")]
        posts = self._fresh_posts(limit=5)
        if not posts:
            return [self._record(TaskKind.SHARE, "分享帖子", TaskStatus.FAILED,
                                 "拉取帖子列表为空")]
        results: list[TaskResult] = []
        done = 0
        for p in posts:
            if done >= gap:
                break
            f = DEFAULT_FORUM
            r = self.client.share_task(p.post_id, game_id=f.game_id)
            self._guard(r, "分享帖子")
            title = p.title[:14] or p.post_id
            if r.ok:
                done += 1
                results.append(self._record(TaskKind.SHARE, f"《{title}》",
                                            TaskStatus.SUCCESS, "已分享"))
            elif r.code == 522:
                continue
            else:
                results.append(self._record(TaskKind.SHARE, f"《{title}》",
                                            TaskStatus.FAILED, str(r)))
        return self._finish(results, gold0)

    def _finish(self, results: list[TaskResult], gold0: int) -> list[TaskResult]:
        """跑完一组后按今日币数差额回填，拿不到进度就保持 0。"""
        if gold0 >= 0:
            gold1 = self._today_gold()
            if gold1 >= 0:
                self._distribute(results, gold1 - gold0)
        return results

    # ---------- 领奖 ----------
    def claim_all(self) -> list[TaskResult]:
        """库街区任务完成即到账，没有单独的领奖动作。"""
        return [self._record(TaskKind.CLAIM, "领取奖励", TaskStatus.SKIPPED,
                             "库街区任务完成后自动到账，无需领取")]

    def build_steps(self, options: dict) -> list[tuple[str, object]]:
        """把任务页的勾选项翻译成执行步骤（单账号 / 全部平台共用）。"""
        o = options or {}
        steps: list[tuple[str, object]] = []
        if o.get("bbs_sign"):
            steps.append(("社区签到", self.run_bbs_sign))
        if o.get("game_sign"):
            steps.append(("游戏签到", lambda: self.run_game_sign(o.get("game_ids"))))
        if o.get("browse"):
            steps.append(("浏览帖子", self.run_browse))
        if o.get("like"):
            steps.append(("点赞任务", self.run_like))
        if o.get("share"):
            steps.append(("分享任务", self.run_share))
        return steps


def uid_of(cred: Credential) -> str:
    """从凭证里取库街区账号 userId（优先 extra，其次 uid，最后解 JWT）。"""
    if cred.extra.get("user_id"):
        return str(cred.extra["user_id"])
    if cred.uid:
        return str(cred.uid)
    return decode_uid(cred.token)


def decode_uid(token: str) -> str:
    """库街区 token 的 payload 里直接带 userId，不用额外填。"""
    import base64
    import json as _json
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        payload = _json.loads(base64.urlsafe_b64decode(part).decode("utf-8"))
        return str(payload.get("userId", ""))
    except Exception:                       # noqa: BLE001
        return ""


# ---------------- 平台约定接口 ----------------
Provider = KuroProvider


def prepare_import(cred) -> None:
    """手动导入库街区凭证：token 必填，UID 缺省从 token 解析。"""
    if not cred.token:
        raise ValueError("库街区必须填 token")
    if not cred.uid:
        cred.uid = decode_uid(cred.token)
    cred.extra = {"user_id": cred.uid}
