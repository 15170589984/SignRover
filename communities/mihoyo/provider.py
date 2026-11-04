"""米游社任务执行器：把散落的接口组合成「一键日常」。"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from communities.mihoyo.boards import BOARDS, BY_GAME_BIZ
from communities.mihoyo.client import GameRole, MihoyoClient
from core.models import CoinInfo, Credential, GameBoard, MissionItem, TaskKind, TaskResult, TaskStatus
from core.storage import Storage


@dataclass
class AccountSnapshot:
    """一次拉取得到的账号全貌，供界面展示。"""
    daily: list[MissionItem] = field(default_factory=list)
    more: list[MissionItem] = field(default_factory=list)
    coin: CoinInfo = field(default_factory=CoinInfo)
    roles: list[GameRole] = field(default_factory=list)
    signed_boards: dict[str, bool] = field(default_factory=dict)   # gid -> 今日是否已签


class MihoyoProvider:
    def __init__(self, cred: Credential, storage: Storage | None = None,
                 min_interval: float | None = None):
        if min_interval is None:
            from core.settings import settings
            min_interval = settings().interval
        self.cred = cred
        self.storage = storage
        self.client = MihoyoClient(cred, min_interval=min_interval)
        self._log: list[str] = []

    def close(self) -> None:
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---------- 日志 ----------
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

    def _earned(self) -> int:
        """今日已完成的米游币（已领取 + 已完成待领取），拿不到返回 -1。"""
        try:
            _, coin = self.client.mission_states()
        except Exception:                       # noqa: BLE001
            return -1
        if not coin.total and not coin.received and not coin.can_get:
            return -1
        return int(coin.received) + int(coin.can_get)

    def _distribute(self, results: list[TaskResult], delta: int) -> None:
        """把这一组真实到账的币平摊到成功记录上，合计正好等于 delta。"""
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

    def _finish(self, results: list[TaskResult], before: int) -> list[TaskResult]:
        if before >= 0:
            after = self._earned()
            if after >= 0:
                self._distribute(results, after - before)
        return results

    # ---------- 快照 ----------
    def roles(self) -> list[GameRole]:
        """游戏角色：优先接口，失败则回退到模拟器本地缓存。"""
        roles = self.client.game_roles()
        if roles:
            return roles
        return self._roles_from_device()

    def _roles_from_device(self) -> list[GameRole]:
        try:
            import html as _html
            from device.emulator import Emulator
            e = Emulator()
            e.ensure_device()
            prefs = e.read_xml_prefs(
                f"/data/data/com.mihoyo.hyperion/shared_prefs/user_game_role_{self.cred.uid}.xml")
            # prefs 里的 JSON 被 XML 转义过（&quot;），必须先反转义
            raw = _html.unescape(prefs.get("current_role", "") or "")
            if not raw:
                return []
            d = json.loads(raw)
            return [GameRole(game_biz=d.get("game_biz", ""), region=d.get("region", ""),
                             game_uid=str(d.get("game_uid", "")), nickname=d.get("nickname", ""),
                             level=int(d.get("level", 0) or 0), is_chosen=True)]
        except Exception as ex:                     # noqa: BLE001
            self._log.append(f"本地角色缓存读取失败：{type(ex).__name__}: {ex}")
            return []

    def snapshot(self, with_sign_state: bool = True) -> AccountSnapshot:
        snap = AccountSnapshot()
        daily, more = self.client.missions()
        states, coin = self.client.mission_states()
        for m in daily + more:
            st = states.get(m.mission_id, {})
            m.happened_times = int(st.get("happened_times", 0) or 0)
            m.is_get_award = bool(st.get("is_get_award", False))
            if st.get("mission_key"):
                m.mission_key = st["mission_key"]
        snap.daily, snap.more, snap.coin = daily, more, coin
        snap.roles = self.roles()
        if with_sign_state:
            for gid in ("2", "6", "8", "1", "4"):
                r = self.client.bbs_sign_status(gid)
                if r.ok and isinstance(r.data, dict):
                    snap.signed_boards[gid] = bool(r.data.get("is_signed"))
        if self.storage:
            self.storage.add_coin_snapshot(self.cred.key, coin.total, coin.today)
        return snap

    # ---------- 游戏每日签到 ----------
    def run_game_sign(self, game_bizs: list[str] | None = None) -> list[TaskResult]:
        results: list[TaskResult] = []
        all_roles = self.roles()
        if game_bizs:
            all_roles = [r for r in all_roles if r.game_biz in game_bizs]
        if not all_roles:
            return [self._record(TaskKind.GAME_SIGN, "游戏签到", TaskStatus.SKIPPED,
                                 "未找到已绑定的游戏角色")]

        # 同一游戏可能有多个角色（不同区服），逐个签
        seen: dict[str, int] = {}
        for role in all_roles:
            board = BY_GAME_BIZ.get(role.game_biz)
            if not board or not board.act_id:
                continue
            seen[board.gid] = seen.get(board.gid, 0) + 1
            label = board.name if seen[board.gid] == 1 else f"{board.name}#{seen[board.gid]}"
            label = f"{label}（{role.nickname}）"

            info = self.client.game_sign_info(board, role.region, role.game_uid)
            if not info.ok:
                results.append(self._record(TaskKind.GAME_SIGN, label, TaskStatus.FAILED,
                                            f"查询失败: {info.message}"))
                continue
            if isinstance(info.data, dict) and info.data.get("is_sign"):
                results.append(self._record(
                    TaskKind.GAME_SIGN, label, TaskStatus.SKIPPED,
                    f"今日已签到（本月 {info.data.get('total_sign_day', 0)} 天）"))
                continue
            r = self.client.game_sign(board, role.region, role.game_uid)
            if r.ok:
                results.append(self._record(TaskKind.GAME_SIGN, label, TaskStatus.SUCCESS, "签到成功"))
            else:
                results.append(self._record(TaskKind.GAME_SIGN, label, TaskStatus.FAILED,
                                            f"签到失败: {r.message}"))
        return results

    # ---------- 社区打卡 ----------
    def run_bbs_sign(self, gids: list[str]) -> list[TaskResult]:
        results: list[TaskResult] = []
        before = self._earned()
        for gid in gids:
            board = BOARDS.get(gid)
            name = board.name if board else f"gid={gid}"
            st = self.client.bbs_sign_status(gid)
            if st.ok and isinstance(st.data, dict) and st.data.get("is_signed"):
                results.append(self._record(TaskKind.BBS_SIGN, name, TaskStatus.SKIPPED, "今日已签到"))
                continue
            r = self.client.bbs_sign(gid)
            if r.ok:
                results.append(self._record(TaskKind.BBS_SIGN, name, TaskStatus.SUCCESS, "社区签到成功"))
            else:
                results.append(self._record(TaskKind.BBS_SIGN, name, TaskStatus.FAILED, r.message))
        return self._finish(results, before)

    # ---------- 点赞任务 ----------
    def run_like(self, gids: list[str], need: int = 5) -> list[TaskResult]:
        """凑够 need 次点赞。拉不到帖子流的板块会自动跳过。"""
        results: list[TaskResult] = []
        before = self._earned()
        done = 0
        tried: list[str] = []
        for gid in gids:
            if done >= need:
                break
            board = BOARDS.get(gid)
            name = board.name if board else f"gid={gid}"
            posts = self.client.post_list(gid, page_size=max(10, need * 2))
            if not posts:
                tried.append(name)
                continue
            for i, post in enumerate(posts, 1):
                if done >= need:
                    break
                pid = str(post["post_id"])
                r = self.client.like_post(pid, True)
                subject = (post.get("subject") or "").strip()[:14] or pid
                if r.ok:
                    done += 1
                    results.append(self._record(TaskKind.LIKE, f"{name}#{i}",
                                                TaskStatus.SUCCESS, f"已点赞《{subject}》"))
                else:
                    results.append(self._record(TaskKind.LIKE, f"{name}#{i}",
                                                TaskStatus.FAILED, r.message))
        if done < need:
            results.append(self._record(TaskKind.LIKE, "点赞汇总", TaskStatus.FAILED,
                                        f"只完成 {done}/{need} 次"
                                        + (f"（这些板块拿不到帖子流：{'、'.join(tried)}）" if tried else "")))
        elif tried:
            results.append(self._record(TaskKind.LIKE, "点赞汇总", TaskStatus.SKIPPED,
                                        f"完成 {done} 次，跳过无帖子流的板块：{'、'.join(tried)}"))
        return self._finish(results, before)

    # ---------- 分享任务 ----------
    def run_share(self, gids: list[str], need: int = 1) -> list[TaskResult]:
        """分享指定板块的帖子（协议侧可直接上报，无需 UI）。"""
        results: list[TaskResult] = []
        before = self._earned()
        done = 0
        tried: list[str] = []
        for gid in gids:
            if done >= need:
                break
            board = BOARDS.get(gid)
            name = board.name if board else f"gid={gid}"
            posts = self.client.post_list(gid, page_size=5)
            if not posts:
                tried.append(name)
                continue
            post = posts[0]
            r = self.client.share_post(str(post["post_id"]))
            subject = (post.get("subject") or "").strip()[:16] or post["post_id"]
            if r.ok:
                done += 1
                results.append(self._record(TaskKind.SHARE, name, TaskStatus.SUCCESS,
                                            f"已分享《{subject}》"))
            else:
                results.append(self._record(TaskKind.SHARE, name, TaskStatus.FAILED, r.message))
        if not done:
            results.append(self._record(TaskKind.SHARE, "分享汇总", TaskStatus.FAILED,
                                        "所有板块都拿不到帖子流"))
        return self._finish(results, before)

    # ---------- 领奖 ----------
    def claim_all(self) -> list[TaskResult]:
        results: list[TaskResult] = []
        daily, more = self.client.missions()
        states, _ = self.client.mission_states()
        for m in daily + more:
            st = states.get(m.mission_id, {})
            times = int(st.get("happened_times", 0) or 0)
            got = bool(st.get("is_get_award", False))
            if times >= m.threshold and not got:
                r = self.client.claim_award(m.mission_id)
                status = TaskStatus.SUCCESS if r.ok else TaskStatus.FAILED
                results.append(self._record(TaskKind.CLAIM, m.name, status,
                                            r.message if not r.ok else "领取成功", m.points))
        return results

    def build_steps(self, options: dict) -> list[tuple[str, object]]:
        """把任务页的勾选项翻译成执行步骤（单账号 / 全部平台共用）。"""
        o = options or {}
        gids = o.get("gids") or ["2"]
        steps: list[tuple[str, object]] = []
        if o.get("game_sign"):
            steps.append(("游戏签到", lambda: self.run_game_sign(o.get("game_bizs"))))
        if o.get("bbs_sign"):
            steps.append(("社区打卡", lambda: self.run_bbs_sign(gids)))
        if o.get("like"):
            steps.append(("点赞任务", lambda: self.run_like(gids, need=5)))
        if o.get("share"):
            steps.append(("分享任务", lambda: self.run_share(gids[:1])))
        if o.get("claim"):
            steps.append(("领取奖励", self.claim_all))
        return steps


# ---------------- 平台约定接口 ----------------
Provider = MihoyoProvider


def prepare_import(cred) -> None:
    """手动导入米游社凭证：UID 必填。"""
    if not cred.uid:
        raise ValueError("米游社 UID 必填")
