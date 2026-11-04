"""米游社板块与游戏签到活动配置。

gid   : 社区板块 id，用于社区签到/浏览/发帖
act_id: 游戏每日签到活动 id（用于发游戏道具的签到）
sign_host: 签到接口域名，绝区零走 act-nap-api.mihoyo.com
send_signgame: 是否附加 x-rpc-signgame 头（崩3/未定/崩2 不需要）
"""
from __future__ import annotations

from core.models import GameBoard

HOYO = "https://api-takumi.mihoyo.com"
NAP = "https://act-nap-api.mihoyo.com"

BOARDS: dict[str, GameBoard] = {
    "2": GameBoard(gid="2", name="原神", act_id="e202311201442471",
                   signgame="hk4e", game_biz="hk4e_cn", sign_host=HOYO),
    "6": GameBoard(gid="6", name="崩坏：星穹铁道", act_id="e202304121516551",
                   signgame="hkrpg", game_biz="hkrpg_cn", sign_host=HOYO),
    "8": GameBoard(gid="8", name="绝区零", act_id="e202406242138391",
                   signgame="zzz", game_biz="nap_cn", sign_host=NAP),
    "1": GameBoard(gid="1", name="崩坏3", act_id="e202306201626331",
                   signgame="bh3", game_biz="bh3_cn", sign_host=HOYO, send_signgame=False),
    "4": GameBoard(gid="4", name="未定事件簿", act_id="e202202251749321",
                   signgame="nxx", game_biz="nxx_cn", sign_host=HOYO, send_signgame=False),
    "3": GameBoard(gid="3", name="崩坏学园2", act_id="e202203291431091",
                   signgame="bh2", game_biz="bh2_cn", sign_host=HOYO, send_signgame=False),
    "5": GameBoard(gid="5", name="大别野"),
    "9": GameBoard(gid="9", name="崩坏：因缘精灵"),
    "10": GameBoard(gid="10", name="星布谷地"),
}

# 支持游戏每日签到的板块（有 act_id）
SIGNABLE = [b for b in BOARDS.values() if b.act_id]

BY_GAME_BIZ = {b.game_biz: b for b in BOARDS.values() if b.game_biz}


def board_of(gid: str) -> GameBoard | None:
    return BOARDS.get(str(gid))
