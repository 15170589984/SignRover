"""库街区的游戏与板块配置。

gameId：2 = 战双帕弥什，3 = 鸣潮（0 表示库街区社区本身）
forumId：帖子的分版，点赞/浏览/分享都从这些分版里取帖子
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KuroForum:
    forum_id: str
    game_id: str
    name: str

    @property
    def game_name(self) -> str:
        return GAME_NAMES.get(self.game_id, f"gameId={self.game_id}")


GAME_NAMES: dict[str, str] = {
    "2": "战双帕弥什",
    "3": "鸣潮",
}

# 按「帖子新、活跃度高」排序，互动任务优先从前面取
FORUMS: tuple[KuroForum, ...] = (
    KuroForum("10", "3", "鸣潮·今州茶馆"),
    KuroForum("9", "3", "鸣潮·推荐"),
    KuroForum("2", "2", "战双·推荐"),
)

BY_FORUM_ID: dict[str, KuroForum] = {f.forum_id: f for f in FORUMS}

# 默认取帖子的分版（今州茶馆，最新发布、水量足）
DEFAULT_FORUM = FORUMS[0]

# 游戏签到的 gameId 白名单（库街区支持每天在社区里给游戏签到）
SIGN_GAMES: tuple[str, ...] = ("3", "2")
