"""库街区（kurobbs）协议客户端。

库街区和米游社的实现差异：
- 域名单一：`https://api.kurobbs.com`，全部 POST + form-urlencoded
- 鉴权只有一个 JWT：请求头 `token: eyJ...`，且 payload 里自带 userId
- 返回体是 `{code, msg, data}`，code==200 成功、220 表示 token 失效
- **互动任务由服务端记账**，浏览/点赞/分享调接口就能推进任务进度（米游社不行）
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field

import httpx

from core.http import ssl_verify

BASE = "https://api.kurobbs.com"

# 操作类接口（签到）用的是 web 形态的 UA
UA_WEB = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 "
          "(KHTML, like Gecko)  KuroGameBox/3.1.4")
# 社区功能类接口用客户端形态的 UA
UA_APP = "KuroGameBox/20260706191836 CFNetwork/3860.600.12 Darwin/25.5.0"
APP_VERSION = "3.1.4"


@dataclass
class KuroResult:
    code: int = -1
    msg: str = ""
    data: object = None
    http_status: int = 0

    @property
    def ok(self) -> bool:
        return self.code == 200

    @property
    def token_invalid(self) -> bool:
        return self.code == 220

    def __str__(self) -> str:
        return f"code={self.code} {self.msg}"


@dataclass
class KuroRole:
    """库街区账号绑定的游戏角色。"""
    game_id: str
    role_id: str
    server_id: str
    name: str = ""
    level: int = 0

    @property
    def game_name(self) -> str:
        return GAME_NAMES.get(self.game_id, f"gameId={self.game_id}")

    # 与米游社 GameRole 对齐的展示字段，方便界面统一渲染
    @property
    def nickname(self) -> str:
        return self.name

    @property
    def game_uid(self) -> str:
        return self.role_id

    @property
    def detail(self) -> str:
        return f"roleId {self.role_id}"


GAME_NAMES = {"2": "战双帕弥什", "3": "鸣潮"}


@dataclass
class KuroPost:
    post_id: str
    user_id: str = ""
    title: str = ""
    like_count: int = 0
    is_liked: bool = False


class KuroClient:
    def __init__(self, token: str, user_id: str = "", min_interval: float = 1.2,
                 timeout: float = 20.0):
        self.token = token
        self.user_id = user_id
        self.min_interval = min_interval
        self._last = 0.0
        rid = str(uuid.uuid4())
        self._dev_code = rid
        self._distinct_id = f"{str(uuid.uuid4())}_9"
        self.http = httpx.Client(timeout=timeout, follow_redirects=True, verify=ssl_verify())

    def close(self) -> None:
        self.http.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---------- 请求 ----------
    def _headers(self, kind: int) -> dict[str, str]:
        base = {
            "Accept-Encoding": "gzip, deflate",
            "Content-Type": "application/x-www-form-urlencoded",
            "source": "ios",
            "Host": "api.kurobbs.com",
            "Accept-Language": "zh-CN,zh-Hans;q=0.9",
            "Connection": "keep-alive",
            "token": self.token,
        }
        if kind == 1:
            base.update({
                "User-Agent": UA_WEB,
                "Accept": "application/json, text/plain, */*",
                "Origin": "https://web-static.kurobbs.com",
                "Sec-Fetch-Site": "same-site",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Dest": "empty",
                "devCode": f"192.168.1.2, {UA_WEB}",
            })
        else:
            base.update({
                "User-Agent": UA_APP,
                "channelId": "1",
                "version": APP_VERSION,
                "distinct_id": self._distinct_id,
                "channel": "appstore",
                "Accept": "*/*",
                "devCode": self._dev_code,
                "ip": "192.168.1.2",
                "lang": "zh-Hans",
                "model": "iPhone15,4",
                "osVersion": "26.5.2",
            })
        return base

    def _throttle(self) -> None:
        gap = time.monotonic() - self._last
        if gap < self.min_interval:
            time.sleep(self.min_interval - gap)
        self._last = time.monotonic()

    def post(self, path: str, data: dict | None = None, kind: int = 2,
             retries: int = 2) -> KuroResult:
        url = f"{BASE}/{path.lstrip('/')}"
        payload = {k: str(v) for k, v in (data or {}).items()}
        last = KuroResult(msg="未执行")
        for attempt in range(retries + 1):
            self._throttle()
            try:
                r = self.http.post(url, data=payload, headers=self._headers(kind))
                last.http_status = r.status_code
                if r.status_code != 200:
                    last = KuroResult(code=-r.status_code, msg=f"HTTP {r.status_code}",
                                      http_status=r.status_code)
                else:
                    try:
                        j = r.json()
                    except json.JSONDecodeError:
                        return KuroResult(code=-1, msg="返回非 JSON", http_status=200)
                    return KuroResult(code=j.get("code", -1), msg=j.get("msg", "") or "",
                                      data=j.get("data"), http_status=200)
            except httpx.HTTPError as e:
                last = KuroResult(code=-1, msg=f"{type(e).__name__}: {e}")
            if attempt < retries:
                time.sleep(1.5)
        return last

    # ---------- 账号 ----------
    def mine(self) -> KuroResult:
        return self.post("user/mineV2")

    def task_process(self) -> KuroResult:
        """每日任务进度（gameId=0 表示库街区社区）。"""
        return self.post("encourage/level/getTaskProcess", {"gameId": "0"})

    def default_roles(self) -> list[KuroRole]:
        r = self.post("user/role/findUserDefaultRole", {"queryUserId": self.user_id})
        out: list[KuroRole] = []
        if not r.ok or not isinstance(r.data, dict):
            return out
        for it in r.data.get("defaultRoleList", []) or []:
            out.append(KuroRole(
                game_id=str(it.get("gameId", "")),
                role_id=str(it.get("roleId", "")),
                server_id=str(it.get("serverId", "")),
                name=it.get("roleName", "") or "",
                level=int(it.get("gameLevel", 0) or 0) if str(it.get("gameLevel", "")).isdigit() else 0,
            ))
        return out

    # ---------- 帖子 ----------
    def forum_posts(self, game_id: str, forum_id: str, page_size: int = 20) -> list[KuroPost]:
        r = self.post("forum/list", {
            "forumId": forum_id, "gameId": game_id, "pageIndex": "1",
            "pageSize": str(page_size), "searchType": "1", "timeType": "0", "topicId": "",
        })
        out: list[KuroPost] = []
        if not r.ok or not isinstance(r.data, dict):
            return out
        for it in r.data.get("postList", []) or []:
            pid = it.get("postId")
            if not pid:
                continue
            out.append(KuroPost(
                post_id=str(pid),
                user_id=str(it.get("userId", "") or ""),
                title=(it.get("postTitle") or it.get("title") or "").strip(),
                like_count=int(it.get("likeTimes", 0) or 0),
                is_liked=bool(it.get("isLike") or it.get("liked")),
            ))
        return out

    def post_detail(self, post_id: str) -> KuroResult:
        """请求帖子详情 —— 库街区按这个动作记「浏览」进度。"""
        return self.post("forum/getPostDetail", {
            "isOnlyPublisher": "0", "postId": post_id, "showOrderType": "2",
        })

    def like(self, post_id: str, to_user_id: str, game_id: str = "3",
             forum_id: str = "10", on: bool = True) -> KuroResult:
        return self.post("forum/like", {
            "forumId": forum_id, "gameId": game_id, "likeType": "1",
            "operateType": "1" if on else "2",
            "postCommentId": "0", "postCommentReplyId": "0",
            "postId": post_id, "postType": "1", "toUserId": to_user_id,
        })

    def share_task(self, post_id: str, game_id: str = "3") -> KuroResult:
        """上报分享任务进度（不需要真的把链接发出去）。"""
        return self.post("encourage/level/shareTask", {"gameId": game_id, "postId": post_id})

    # ---------- 签到 ----------
    def bbs_sign(self) -> KuroResult:
        """库街区社区签到。gameId 固定 2，geeTestData 留空即可（目前不校验）。"""
        return self.post("user/signIn", {"gameId": "2", "geeTestData": ""})

    def game_sign_info(self, role: KuroRole) -> KuroResult:
        return self.post("encourage/signIn/initSignInV2", {
            "gameId": role.game_id, "serverId": role.server_id,
            "roleId": role.role_id, "userId": self.user_id,
        }, kind=1)

    def game_sign(self, role: KuroRole, month: str) -> KuroResult:
        return self.post("encourage/signIn/v2", {
            "gameId": role.game_id, "serverId": role.server_id,
            "roleId": role.role_id, "userId": self.user_id, "reqMonth": month,
        }, kind=1)
