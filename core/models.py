"""数据模型。"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"


class TaskKind(str, Enum):
    """任务类型，决定用哪套接口实现。"""
    GAME_SIGN = "game_sign"        # 游戏每日签到（发游戏道具）
    BBS_SIGN = "bbs_sign"          # 社区打卡（发米游币）
    BROWSE = "browse"              # 浏览帖子
    LIKE = "like"                  # 点赞
    SHARE = "share"                # 分享
    COMMENT = "comment"            # 评论
    PUBLISH = "publish"            # 发帖
    CLAIM = "claim"                # 领取任务奖励
    TOOL_SIGN = "tool_sign"        # 工具类每日签到（Trae / Qoder / WorkBuddy）


@dataclass
class GameBoard:
    """米游社的一个板块 / 游戏。"""
    gid: str
    name: str
    act_id: str = ""          # 游戏签到活动 id
    signgame: str = ""        # x-rpc-signgame 值，如 hk4e
    game_biz: str = ""        # hk4e_cn
    sign_host: str = "https://api-takumi.mihoyo.com"   # 签到接口域名（绝区零不同）
    send_signgame: bool = True                          # 是否发送 x-rpc-signgame 头


@dataclass
class Credential:
    """一个账号的凭证。

    不同社区的字段含义不同，用 community 区分：
    - mihoyo：uid=米游社 uid，stoken/web_cookies 两套会话
    - kuro：uid=库街区账号 userId，token=JWT
    """
    uid: str = ""
    nickname: str = ""
    mid: str = ""
    stoken: str = ""
    web_cookies: dict[str, str] = field(default_factory=dict)
    device_id: str = ""
    device_fp: str = ""
    device_name: str = "Xiaomi 2201123C"
    device_model: str = "2201123C"
    app_version: str = "2.117.0"
    community: str = "mihoyo"
    token: str = ""            # 库街区 JWT
    extra: dict = field(default_factory=dict)   # 社区私有字段（角色、gameId 等）

    @property
    def currency(self) -> str:
        from core.communities import get as _get
        return _get(self.community).currency

    @property
    def community_name(self) -> str:
        from core.communities import get as _get
        return _get(self.community).name

    @property
    def key(self) -> str:
        """账号在库里的唯一键（跨社区不冲突）。"""
        return f"{self.community}:{self.uid}"

    @property
    def app_cookie(self) -> str:
        """App 接口用的 cookie（stoken 体系）。"""
        return f"stuid={self.uid};stoken={self.stoken};mid={self.mid};"

    @property
    def web_cookie(self) -> str:
        """H5 / 游戏签到用的 cookie（ltoken 体系）。"""
        keys = ("ltuid", "cookie_token", "cookie_token_v2", "account_id",
                "account_id_v2", "ltmid_v2", "ltoken", "ltoken_v2")
        parts = [f"{k}={self.web_cookies[k]}" for k in keys if self.web_cookies.get(k)]
        return ";".join(parts)

    @property
    def valid(self) -> bool:
        if self.community in ("kuro", "trae"):
            return bool(self.uid and self.token)
        return bool(self.uid and (self.stoken or self.web_cookies.get("ltuid")))

    def masked(self) -> str:
        return f"{self.nickname or '未命名'}({self.uid})" if self.uid else "未命名"


@dataclass
class TaskResult:
    kind: TaskKind
    target: str               # 具体对象，如板块名/帖子 id
    status: TaskStatus
    message: str = ""
    points: int = 0
    coins_after: int | None = None
    currency: str = ""        # 该平台货币名，如 米游币 / 库洛币 / 积分
    run_id: int = 0           # 对应 runs 表主键，跑完算出差额后回填 points

    @property
    def ok(self) -> bool:
        return self.status is TaskStatus.SUCCESS


@dataclass
class MissionItem:
    """米游币任务项。"""
    mission_id: int
    name: str
    desc: str
    points: int
    threshold: int
    happened_times: int = 0
    is_get_award: bool = False
    auto_award: bool = False
    mission_key: str = ""

    @property
    def done(self) -> bool:
        return self.happened_times >= self.threshold

    @property
    def progress(self) -> str:
        return f"{min(self.happened_times, self.threshold)}/{self.threshold}"


@dataclass
class CoinInfo:
    total: int = 0            # 当前余额
    today: int = 0            # 今日已获得（已到账 + 已完成待领）
    can_get: int = 0          # 可领取
    received: int = 0         # 已领
    cap: int = 0              # 每日上限（0 表示该平台不设上限）
