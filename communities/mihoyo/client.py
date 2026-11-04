"""米游社协议客户端（基于 2.117.0 实测接口）。

两套认证：
- App 接口（社区签到/任务/米游币）：Cookie stuid + stoken + mid
- H5 接口（游戏每日签到/角色绑定）：Cookie ltuid + cookie_token_v2 等
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass

import httpx

from core.http import ssl_verify

from core.ds import SALT_APP, SALT_BBS, ds1, ds2
from core.models import CoinInfo, Credential, GameBoard, MissionItem

BBS_API = "https://bbs-api.miyoushe.com"
TAKUMI_API = "https://api-takumi.miyoushe.com"
TAKUMI_HOYO = "https://api-takumi.mihoyo.com"

UA_APP = "okhttp/4.9.3"
UA_H5 = (
    "Mozilla/5.0 (Linux; Android 15; 2201123C Build/V417IR; wv) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Version/4.0 Chrome/110.0.5481.154 Mobile Safari/537.36 miHoYoBBS/2.117.0"
)
APP_ID = "bll8iq97cem8"


@dataclass
class ApiResult:
    ok: bool
    retcode: int
    message: str
    data: dict | list | None = None

    @classmethod
    def parse(cls, payload: dict) -> "ApiResult":
        code = int(payload.get("retcode", -1))
        return cls(code == 0, code, str(payload.get("message", "")), payload.get("data"))


@dataclass
class GameRole:
    game_biz: str
    region: str
    game_uid: str
    nickname: str
    level: int
    is_chosen: bool = False

    @property
    def game_name(self) -> str:
        from communities.mihoyo.boards import BY_GAME_BIZ
        b = BY_GAME_BIZ.get(self.game_biz)
        return b.name if b else self.game_biz

    @property
    def detail(self) -> str:
        return f"{self.region} · {self.game_uid}"


class MihoyoClient:
    def __init__(self, cred: Credential, timeout: float = 20.0, min_interval: float = 1.2):
        self.cred = cred
        self.min_interval = min_interval
        self._last_at = 0.0
        self.last_error = ""
        self.http = httpx.Client(timeout=timeout, follow_redirects=True,
                                 headers={"Accept-Encoding": "gzip, deflate"},
                                 verify=ssl_verify())

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self) -> None:
        self.http.close()

    # ---------- 底层 ----------
    def _throttle(self) -> None:
        gap = time.time() - self._last_at
        if gap < self.min_interval:
            time.sleep(self.min_interval - gap)
        self._last_at = time.time()

    def _app_headers(self) -> dict:
        return {
            "Cookie": self.cred.app_cookie,
            "User-Agent": UA_APP,
            "x-rpc-app_version": self.cred.app_version,
            "x-rpc-client_type": "2",
            "x-rpc-app_id": APP_ID,
            "x-rpc-verify_key": APP_ID,
            "x-rpc-device_id": self.cred.device_id,
            "x-rpc-device_fp": self.cred.device_fp,
            "x-rpc-device_name": self.cred.device_name,
            "x-rpc-device_model": self.cred.device_model,
            "x-rpc-sys_version": "15",
            "x-rpc-channel": "miyousheluodi",
            "x-rpc-csm_source": "",
            "Referer": "https://app.mihoyo.com",
        }

    def _h5_headers(self, signgame: str = "") -> dict:
        h = {
            "Cookie": self.cred.web_cookie,
            "User-Agent": UA_H5,
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://act.mihoyo.com",
            "Referer": "https://act.mihoyo.com/",
            "X-Requested-With": "com.mihoyo.hyperion",
        }
        if signgame:
            h["x-rpc-signgame"] = signgame
        return h

    def _call(self, method: str, url: str, *, headers: dict, params: dict | None = None,
              body: dict | None = None, raw_body: str | None = None) -> ApiResult:
        self._throttle()
        content = None
        if raw_body is not None:
            content = raw_body.encode("utf-8")
        elif body is not None:
            content = json.dumps(body, separators=(",", ":")).encode("utf-8")
        try:
            r = self.http.request(method, url, params=params, headers=headers, content=content)
        except httpx.HTTPError as e:
            return ApiResult(False, -1, f"网络错误: {e}")
        if r.status_code == 403:
            return ApiResult(False, 403, "触发风控（HTTP 403），请降低频率后稍再试")
        try:
            payload = r.json()
        except Exception:
            return ApiResult(False, r.status_code, f"响应异常 HTTP {r.status_code}: {r.text[:100]}")
        if not isinstance(payload, dict):
            return ApiResult(False, -3, "响应格式异常")
        return ApiResult.parse(payload)

    def app_get(self, url: str, params: dict | None = None, signed: bool = False) -> ApiResult:
        h = self._app_headers()
        if signed:
            h["DS"] = ds2(SALT_BBS, query=params or {})
        return self._call("GET", url, headers=h, params=params)

    def app_post(self, url: str, body: dict | None = None, params: dict | None = None,
                 signed: bool = False) -> ApiResult:
        h = self._app_headers()
        h["Content-Type"] = "application/json;charset=UTF-8"
        raw = json.dumps(body if body is not None else {}, separators=(",", ":"))
        if signed:
            h["DS"] = ds2(SALT_BBS, query=params or {}, body=raw)
        return self._call("POST", url, headers=h, raw_body=raw, params=params)

    def h5_get(self, url: str, params: dict | None = None, signgame: str = "") -> ApiResult:
        return self._call("GET", url, headers=self._h5_headers(signgame), params=params)

    # ---------- 板块 ----------
    def game_list(self) -> ApiResult:
        return self.app_get(f"{BBS_API}/apihub/api/getGameList")

    # ---------- 账号资料 ----------
    def account_info(self) -> ApiResult:
        return self.app_get(f"{BBS_API}/user/api/getUserFullInfo", {"uid": self.cred.uid})

    def game_roles(self) -> list[GameRole]:
        """已绑定到米游社的游戏角色（用于游戏签到）。

        优先走 H5 的 getUserGameRolesByCookie（只要有 Web 登录态就能通）；
        App 侧的 getUserGameRolesByStoken 需要 DS 签名，通常拿不到，作为兜底。
        """
        r = self.h5_get(f"{TAKUMI_API}/binding/api/getUserGameRolesByCookie")
        if not r.ok or not isinstance(r.data, dict):
            r = self.app_get(f"{TAKUMI_API}/binding/api/getUserGameRolesByStoken")
        out: list[GameRole] = []
        if not r.ok or not isinstance(r.data, dict):
            self.last_error = f"{r.retcode} {r.message}"
            return out
        for it in r.data.get("list", []) or []:
            out.append(GameRole(
                game_biz=it.get("game_biz", ""), region=it.get("region", ""),
                game_uid=str(it.get("game_uid", "")), nickname=it.get("nickname", ""),
                level=int(it.get("level", 0) or 0), is_chosen=bool(it.get("is_chosen")),
            ))
        # 优先当前选中的角色
        out.sort(key=lambda x: not x.is_chosen)
        return out

    # ---------- 社区签到（打卡） ----------
    def bbs_sign_status(self, gid: str) -> ApiResult:
        return self.app_get(f"{BBS_API}/apihub/sapi/querySignInStatus", {"gids": gid})

    def bbs_sign(self, gid: str) -> ApiResult:
        """社区打卡。必须带 DS2 签名，否则返回 -10001。"""
        return self.app_post(f"{TAKUMI_API}/apihub/app/api/signIn", {"gids": gid}, signed=True)

    # ---------- 帖子 ----------
    def post_list(self, gid: str, page_size: int = 10) -> list[dict]:
        """板块帖子列表。forum_id 即 gid。"""
        r = self.app_get(f"{BBS_API}/post/api/getForumPostList",
                         {"forum_id": gid, "page_size": str(page_size), "sort_type": "1"})
        if not r.ok or not isinstance(r.data, dict):
            return []
        out = []
        for it in r.data.get("list", []) or []:
            post = it.get("post") or it
            if post.get("post_id"):
                out.append(post)
        return out

    def post_full(self, post_id: str) -> ApiResult:
        return self.app_get(f"{BBS_API}/post/api/getPostFull", {"post_id": post_id})

    def post_replies(self, post_id: str, page_size: int = 5) -> list[dict]:
        r = self.app_get(f"{BBS_API}/post/api/getPostReplies",
                         {"post_id": post_id, "page_size": str(page_size), "sort_type": "2"})
        if not r.ok or not isinstance(r.data, dict):
            return []
        return r.data.get("list", []) or []

    def share_post(self, post_id: str) -> ApiResult:
        """分享任务上报。"""
        return self.app_post(f"{BBS_API}/post/api/sharePost", {"post_id": post_id}, signed=True)

    def like_post(self, post_id: str, liked: bool = True) -> ApiResult:
        """给帖子点赞 / 取消赞。返回 data.current_upvote_type：1=已赞。"""
        return self.app_post(f"{BBS_API}/post/api/post/upvote",
                             {"post_id": post_id, "is_vote": liked}, signed=True)

    # ---------- 游戏每日签到 ----------
    def _sign_headers(self, board: GameBoard) -> dict:
        h = self._h5_headers(board.signgame if board.send_signgame else "")
        if not board.send_signgame:
            h.pop("x-rpc-signgame", None)
        return h

    def game_sign_info(self, board: GameBoard, region: str, game_uid: str) -> ApiResult:
        return self._call(
            "GET", f"{board.sign_host}/event/luna/{board.signgame}/info",
            headers=self._sign_headers(board),
            params={"lang": "zh-cn", "act_id": board.act_id, "region": region, "uid": game_uid},
        )

    def game_sign(self, board: GameBoard, region: str, game_uid: str) -> ApiResult:
        return self._call(
            "POST", f"{board.sign_host}/event/luna/{board.signgame}/sign",
            headers={**self._sign_headers(board), "Content-Type": "application/json;charset=UTF-8"},
            params={"lang": "zh-cn", "act_id": board.act_id, "region": region, "uid": game_uid},
            body={"act_id": board.act_id, "region": region, "uid": game_uid},
        )

    # ---------- 米游币任务 ----------
    def missions(self) -> tuple[list[MissionItem], list[MissionItem]]:
        """返回 (每日任务, 更多任务)。"""
        r = self.app_get(f"{BBS_API}/apihub/wapi/getMissions")
        daily, more = [], []
        if not r.ok or not isinstance(r.data, dict):
            return daily, more
        for key, bucket in (("missions", daily), ("more_missions", more)):
            for it in r.data.get(key, []) or []:
                bucket.append(MissionItem(
                    mission_id=int(it.get("id", 0)), name=it.get("name", ""),
                    desc=it.get("desc", ""), points=int(it.get("points", 0)),
                    threshold=int(it.get("threshold", 1)),
                    auto_award=bool(it.get("is_auto_send_award", False)),
                    mission_key=it.get("mission_key", "") or "",
                ))
        return daily, more

    def mission_states(self) -> tuple[dict[int, dict], CoinInfo]:
        """任务进度 + 米游币概览。"""
        r = self.app_get(f"{BBS_API}/apihub/sapi/getUserMissionsState")
        states: dict[int, dict] = {}
        coin = CoinInfo()
        if not r.ok or not isinstance(r.data, dict):
            return states, coin
        for it in r.data.get("states", []) or []:
            states[int(it.get("mission_id", 0))] = it
        # 注意：today_total_points 是「今日可获得上限」（固定 50），不是已获得。
        # 今日已获 = 已领取 + 已完成待领取。
        received = int(r.data.get("already_received_points", 0) or 0)
        can_get = int(r.data.get("can_get_points", 0) or 0)
        coin = CoinInfo(
            total=int(r.data.get("total_points", 0)),
            today=received + can_get,
            can_get=can_get,
            received=received,
            cap=int(r.data.get("today_total_points", 0) or 0),
        )
        return states, coin

    def claim_award(self, mission_id: int) -> ApiResult:
        return self.app_get(f"{BBS_API}/mission/wapi/getAward",
                            {"mission_id": mission_id, "point_sn": "myb"})

    def point_config(self) -> ApiResult:
        return self.app_get(f"{BBS_API}/mission/wapi/getPointConfig", {"point_sn": "myb"})
