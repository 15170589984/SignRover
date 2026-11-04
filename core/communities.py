"""社区注册表：把「签到助手」从米游社专用扩展成多社区。

新增一个平台只需要三步，**不需要改任何 UI 代码**：
1. 在这里登记元数据（key / 名称 / 导入字段 / 任务勾选项）
2. 在 communities/<key>/provider.py 里实现 Provider 类（约定：
   - `Provider`            执行器，实现 snapshot() / build_steps(options)
   - `prepare_import(cred)` 手动导入时的校验与补全（可省略）
   - `run_<task_key>()`    每个任务勾选项对应一个执行方法
3. 在 runs_model.KIND_CN 里补任务类型的中文名（明细页显示用）
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ImportField:
    """手动导入对话框里的一行输入。key 对应 Credential 的属性名。"""
    key: str                    # uid / token / stoken / mid / cookie
    label: str
    placeholder: str = ""
    required: bool = False


@dataclass(frozen=True)
class TaskOption:
    """任务页的一个勾选项。key 会原样传给 provider.build_steps。"""
    key: str
    label: str                  # 勾选框完整文案
    short: str = ""             # 全部平台预览里的简称（缺省用 label）


@dataclass(frozen=True)
class CommunityMeta:
    key: str                    # 内部标识，写进数据库
    name: str                   # 界面显示名
    package: str                # 模拟器里的 App 包名；PC 工具类平台留空
    currency: str               # 社区货币名
    home: str = ""              # 社区主页（文档用）
    auth: str = "stoken"        # 凭证有效性判定依据：stoken / token
    import_fields: tuple[ImportField, ...] = ()   # 手动导入需要的字段（按显示顺序）
    tasks: tuple[TaskOption, ...] = ()            # 任务页勾选项
    task_hint: str = ""         # 任务页该板块底部的说明文字
    boards: tuple[tuple[str, str], ...] = ()      # 签到板块下拉选项（空=无）
    default_gids: tuple[str, ...] = ()            # 板块选「全部」时的默认顺序
    extract_tip: str = ""       # 「从模拟器添加」的提示文案（package 为空时用不到）
    has_roles: bool = True      # 总览是否显示「绑定角色」卡片（PC 工具没有）
    auto_award: bool = False    # 任务完成后是否即时到账（没有「待领取」环节）

    @property
    def title(self) -> str:
        return f"{self.name}"

    @property
    def is_device_app(self) -> bool:
        """模拟器类平台（可从模拟器自动提取凭证）。"""
        return bool(self.package)


MIHOYO = CommunityMeta(
    key="mihoyo", name="米游社", package="com.mihoyo.hyperion",
    currency="米游币", home="https://www.miyoushe.com", auth="stoken",
    import_fields=(
        ImportField("uid", "UID", "米游社 UID（必填）", required=True),
        ImportField("stoken", "stoken", "v2_ 开头"),
        ImportField("mid", "mid", "例如 0cudangi86_mhy"),
        ImportField("cookie", "Cookie", "ltuid=...;cookie_token_v2=..."),
    ),
    tasks=(
        TaskOption("game_sign", "游戏每日签到（原神 / 星铁 / 绝区零 / 崩3 / 未定 …）", "游戏签到"),
        TaskOption("bbs_sign", "米游社社区签到（打卡，得米游币）", "签到"),
        TaskOption("like", "点赞 5 次（接口调用成功，但不计米游币任务进度）", "点赞"),
        TaskOption("share", "分享 1 次（同上，不计任务进度）", "分享"),
        TaskOption("claim", "自动领取已完成任务奖励", "领奖"),
    ),
    task_hint=("说明：游戏签到与社区打卡由服务端直接记账，稳定可用。\n"
               "点赞 / 分享 接口调用会成功，但米游社只按 App 内的真实操作给米游币任务计进度，"
               "不会推进「完成5次点赞 / 分享帖子」的任务条。\n"
               "浏览 / 评论 / 发帖 同理，需要驱动模拟器内 App 的真实界面，暂未开放。"),
    boards=(("2", "原神"), ("6", "崩坏：星穹铁道"), ("8", "绝区零"),
            ("1", "崩坏3"), ("4", "未定事件簿"), ("3", "崩坏学园2")),
    default_gids=("6", "1", "4", "2", "8", "3"),
    extract_tip=("将从模拟器自动读取：\n"
                 "  · Web 凭证（登录态 Cookie）\n"
                 "  · App 会话凭证 stoken（扫描运行时内存）\n\n"
                 "过程中请保持米游社在前台、不要关闭模拟器。约需 10–40 秒。"),
)
KURO = CommunityMeta(
    key="kuro", name="库街区", package="com.kurogame.kjq",
    currency="库洛币", home="https://www.kurobbs.com", auth="token",
    auto_award=True,           # 任务完成即时到账
    import_fields=(
        ImportField("uid", "UID", "账号 userId（留空则自动从 token 解析）"),
        ImportField("token", "token", "App 本地 JWT，eyJ 开头", required=True),
    ),
    tasks=(
        TaskOption("bbs_sign", "库街区社区签到（+30 库洛币）", "签到"),
        TaskOption("game_sign", "游戏签到（鸣潮 / 战双，按绑定角色）", "游戏签到"),
        TaskOption("browse", "浏览 3 篇帖子（+20 库洛币）", "浏览"),
        TaskOption("like", "点赞 5 次（+20 库洛币）", "点赞"),
        TaskOption("share", "分享 1 次帖子（+10 库洛币）", "分享"),
    ),
    task_hint=("说明：库街区的四项社区任务全部由服务端按接口调用记账，"
               "纯协议即可拿满每日 80 库洛币，无需驱动模拟器界面。\n"
               "任务完成即时到账，没有「待领取」这一步。"),
    extract_tip=("将从模拟器自动读取库街区的登录 token（存在 App 本地数据里），"
                 "并解析出账号 UID、校验有效性。\n\n约需 5–15 秒，无需保持 App 在前台。"),
)

# Trae 是 PC 端工具，不走模拟器；凭证从抓包工具手动导入
TRAE = CommunityMeta(
    key="trae", name="Trae", package="",
    currency="积分", home="https://www.trae.cn", auth="token",
    has_roles=False,           # PC 工具没有游戏角色
    auto_award=True,           # 签到即领取
    import_fields=(
        ImportField("token", "token",
                    "留空自动读本机 Trae 客户端；也可粘贴抓包里 Authorization 的值"),
    ),
    tasks=(
        TaskOption("checkin", "每日签到领取积分", "签到"),
    ),
    task_hint=("说明：Trae 是 PC 端工具，不走模拟器。客户端登录后 token 和设备号会自动\n"
               "从本机读取（手动导入里 token 留空点「导入」即可）；读不到时再粘贴\n"
               "抓包工具里 Authorization 请求头的值。\n"
               "注意：签到校验本机 Trae 客户端注册的设备号，本机需装有并登录过 Trae；\n"
               "同一个设备号一天只能给一个账号签到，多账号请各自在登录过的机器上导入。"),
)

QODER = CommunityMeta(
    key="qoder", name="Qoder", package="",
    currency="Credits", home="https://qoder.cn", auth="token",
    has_roles=False, auto_award=True,
    import_fields=(
        ImportField("token", "token",
                    "留空自动读本机 Qoder 客户端（dt- 开头）；也可粘贴抓包里 Bearer 后面那段"),
    ),
    tasks=(
        TaskOption("checkin", "每日领取 100 Credits（10:00 刷新）", "签到"),
    ),
    task_hint=("说明：Qoder 的每日奖励是「活动」形式，每天 10:00（UTC+8）滚动一轮，\n"
               "每轮 100 Credits，领取后 30 天有效。\n"
               "国内版（openapi.qoder.com.cn）和国际版（openapi.qoder.sh）是两套服务，\n"
               "token 不通用；导入时会自动识别该 token 属于哪个版本，不用你选。"),
)

WORKBUDDY = CommunityMeta(
    key="workbuddy", name="WorkBuddy", package="",
    currency="积分", home="https://www.workbuddy.cn", auth="token",
    has_roles=False, auto_award=True,
    import_fields=(
        ImportField("token", "token",
                    "留空自动读本机 WorkBuddy 客户端；也可整段粘贴 cURL 或 Bearer 后面那段"),
        ImportField("uid", "X-User-Id",
                    "留空自动解析（JWT / 本机客户端 / 粘贴的 cURL 里的请求头）"),
    ),
    tasks=(
        TaskOption("checkin", "每日签到领取积分", "签到"),
    ),
    task_hint=("说明：WorkBuddy 是 PC 端工具，不走模拟器。客户端登录后 token 会自动\n"
               "从本机进程读取（手动导入里 token 留空点「导入」即可），uid 也会自动带上；\n"
               "读不到时再走网页版 F12：请求右键 Copy as cURL 整段粘贴。"),
)

ALL: tuple[CommunityMeta, ...] = (MIHOYO, KURO, TRAE, QODER, WORKBUDDY)
BY_KEY: dict[str, CommunityMeta] = {c.key: c for c in ALL}
DEFAULT = MIHOYO.key


def get(key: str | None) -> CommunityMeta:
    return BY_KEY.get(key or DEFAULT, MIHOYO)


def provider_module(key: str):
    """按社区 key 动态取 provider 模块（打包由 spec 整包收集兜底）。"""
    import importlib
    return importlib.import_module(f"communities.{key or DEFAULT}.provider")


def provider_for(cred, *args, **kwargs):
    """按凭证所属社区返回对应的 provider 实例（约定模块里有 Provider）。"""
    return provider_module(cred.community).Provider(cred, *args, **kwargs)


def prepare_import(cred) -> None:
    """手动导入的社区级校验与补全（如从 token 解析 UID）。

    失败抛 ValueError，信息可直接展示给用户。
    """
    mod = provider_module(cred.community)
    fn = getattr(mod, "prepare_import", None)
    if fn:
        fn(cred)
