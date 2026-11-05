# SignRover

游戏社区签到 / 日常自动化助手（桌面版）。当前支持 **米游社**、**库街区** 两个游戏社区，以及 **Trae**、**Qoder**、**WorkBuddy** 三个 PC 工具的每日签到。界面完全由社区注册表驱动，新增平台不用改界面代码。

## 已实现

### 库街区（库洛游戏社区：鸣潮 / 战双帕弥什）

| 功能 | 状态 | 说明 |
|---|---|---|
| 社区签到 | ✅ 可用 | `user/signIn`，+30 库洛币 |
| 游戏签到 | ✅ 可用 | 鸣潮 / 战双，按社区绑定的默认角色签 |
| 浏览 3 篇帖子 | ✅ 可用 | `forum/getPostDetail`，+20 |
| 点赞 5 次 | ✅ 可用 | `forum/like`，已赞过的先取消再赞，+20 |
| 分享 1 次 | ✅ 可用 | `encourage/level/shareTask`，+10 |
| 任务进度 / 库洛币 | ✅ 可用 | 当前余额、今日已得、每日上限 |
| 一键提取凭证 | ✅ 可用 | 读 App 本地 MMKV 里的 JWT，payload 自带 userId |

> **库街区的四项社区任务全部由服务端按接口调用记账**，纯协议即可拿满每日 80 库洛币，
> 不需要驱动模拟器界面。这点和米游社完全不同。

### 米游社

| 功能 | 状态 | 说明 |
|---|---|---|
| 游戏每日签到 | ✅ 可用 | 原神 / 星穹铁道 / 绝区零 / 崩坏3 / 未定事件簿 / 崩坏学园2，按已绑定角色逐个签 |
| 社区签到（打卡） | ✅ 可用 | 已破 DS 签名，走协议直连，得 30 米游币 |
| 任务进度查询 | ✅ 可用 | 打卡、浏览、点赞、分享、绑定角色、改签名 |
| 米游币查询 | ✅ 可用 | 当前余额、今日已得、可领取、已领 |
| 自动领取奖励 | ✅ 可用 | 已完成未领取的任务自动领取 |
| 一键提取凭证 | ✅ 可用 | adb 读 WebView cookie + 扫运行内存取 stoken + 自动校验 |
| 点赞 / 分享 | ◑ 接口可用 | 请求成功，但米游社不给米游币任务计进度（见下） |
| 浏览 / 评论 / 发帖 | ✗ 未开放 | 必须驱动 App 真实界面，`device/ui_agent.py` 已打好基础 |

### Trae（AI IDE 每日签到）

| 功能 | 状态 | 说明 |
|---|---|---|
| 每日签到 | ✅ 可用 | `POST /api/v1/checkin`，`{code:0}` 即到账 |
| 积分余额 / 今日已得 | ✅ 可用 | 余额按 `total_amount - consumed_amount`，今日按 status 的 `credits` |
| 活动奖励 | ✅ 可用 | 活动页 `work_credits`（当前 200/期） |
| 用户昵称 | ✅ 自动 | 导入 / 刷新时调 `cloudide/api/v3/trae/GetUserInfo`（失败退到 `icube/api/v1/user`，再退到 JWT 里的字段），拿到后写回账号 |
| 凭证导入 | ✅ 自动 | 账号页「登录账号」→ 自动获取，读本机 Trae 客户端登录态；读不到再贴请求头 `Authorization` 的值 |

> Trae 是桌面 IDE 不是手机 App，没有模拟器可读，所以走「登录账号」里的自动获取。
> 请求头里的 `x-app-version` / `package-type` / `x-device-id` 客户端自己补齐，
> 用户不用管；签到接口 GET 被拒时自动降级为 POST。

### Qoder（AI 编程 IDE 每日领取）

| 功能 | 状态 | 说明 |
|---|---|---|
| 每日领取 100 Credits | ✅ 可用 | 活动制：`me/campaigns` 找 `CLAIM_BENEFIT` 那轮，`POST …/claim` 领取 |
| 余额 / 今日获得 | ✅ 可用 | 余额 = `userQuota.remaining + addOnQuota.remaining` |
| 凭证 | ✅ 自动 | token 留空即读本机客户端登录态（`%APPDATA%\com.qodercn.app.stable` 国内版 / `com.qoder.app.stable` 国际版，DPAPI + AES-256-GCM 解 `auth.v1.dat`）；也可手动粘贴 |
| 双域名 | ✅ 自动 | 国内 `openapi.qoder.com.cn`、国际 `openapi.qoder.sh` 是两套服务、token 不通用；导入时依次探测并记住该账号所属域名 |

> Qoder 的奖励是「活动」形式，每天 10:00（UTC+8）滚动一轮，领到的 Credits 30 天有效。
> 活动窗口 `startAt/endAt` 是**秒级**时间戳，按毫秒判断会永远认为窗口已关闭。
> 领取接口上游幂等：重复领返回 `replayed: true`，不会多发，重试安全。

### WorkBuddy（腾讯 AI 办公工作台）

| 功能 | 状态 | 说明 |
|---|---|---|
| 每日签到 | ✅ 可用 | `POST /v2/billing/meter/daily-checkin`，成功 `{"credit": 100}` |
| 签到状态 | ✅ 可用 | `POST /v2/billing/meter/checkin-activity-status` 的 `today_checked_in` |
| 积分余额 | ✅ 可用 | `POST /billing/meter/get-user-resource` 资源包聚合 |
| 凭证 | ✅ 自动 | 优先读本机 WorkBuddy 客户端登录态（自动获取）；读不到再手动粘贴（`Authorization: Bearer` + `X-User-Id`） |

> 桌面端 `accessToken` 从 5.6.2 起在本地是 `$wbEncrypted` 加密信封，程序**不去破解**它，
> 改为网页版 F12 抓一次（和 Trae 一样）。签到接口幂等：今日已签返回 `code 10001`。

### 通用

| 功能 | 状态 |
|---|---|
| 多社区 / 多账号 | ✅ 同一平台可登录多个账号（互相独立、各自签到），表格双击或右上角下拉切换当前账号；保存时同 token 就地修正、同账号可选替换或新增 |
| 全部平台一键执行 | ✅ 任务页选「全部平台」按账号顺序跑，单个账号失效不影响其它 |
| 每步到账数量 | ✅ runs 表记 points + currency，日志与明细都显示 +N 币（按任务进度差值算，不虚报） |
| 执行明细 | ✅ 分页表格（每页 20 条），按账号 / 时间 / 结果 / 关键词筛选，可导出 CSV |
| 任务勾选记忆 | ✅ 上次勾了哪些任务会记住，下次自动恢复 |
| 执行中可停止 | ✅ 开始执行后按钮直接变「停止」，每步之间检查中断，不用等整轮跑完 |
| 数据维护 | ✅ 设置页可一键清理 90 天前的执行记录 |
| 定时执行 | ✅ 任务页可设「每天 / 仅工作日 + HH:MM + 全部平台或单个账号」，到点自动跑；同日不重复，跨天重启会补跑 |
| 开机自启 | ✅ 设置页一个勾选框，写 HKCU 的 Run 项（免管理员权限），取消即删 |
| 设置-关于 | ✅ 版本号 + 联网检查更新（读 GitHub Releases，可直接打开安装包下载）、用户协议 / 隐私条款 / 开源软件声明 / 更新日志弹窗、帮助文档与项目主页入口 |

### 「今日已获」的口径

米游社 `getUserMissionsState` 里的 `today_total_points` 是**每日可获得上限（固定 50）**，
不是已获得。早期版本直接拿它当「今日已获」，导致没做任务也显示 50、做完也不变。
现在按 `已领取 + 已完成待领取` 计算，上限单独放在卡片副标题里。库街区用
`getTaskProcess.currentDailyGold`，本身就是今日已得，没有问题。

### 米游社的互动任务为什么不计进度

米游社的「浏览 3 个帖子 / 完成 5 次点赞 / 分享帖子」是**按 App 内的真实行为埋点**判定的。
实测：读 3 个帖子详情、连点 5 次赞、调分享接口，`retcode` 全为 0，但任务进度仍然是 0。
所以这几项只能通过驱动模拟器里的 App 界面完成，纯接口调用走不通。

## 运行

```bash
pip install -r requirements.txt
python app/main.py
```

端到端自检（对每个社区依次：提取凭证 → 跑完整任务链）：

```bash
python tools/selftest.py           # 全部社区
python tools/selftest.py kuro      # 只跑库街区
python tools/selftest.py mihoyo    # 只跑米游社
```

打包 exe（用 `SignRover.spec`，已带上图标与排除项）：

```bash
python -m PyInstaller --noconfirm SignRover.spec
```

> 产物在 `dist/SignRover/`（exe + `_internal`）。重新打包前要先让开旧目录
> （`mv dist/SignRover dist/_old`），否则 COLLECT 阶段会被挡住。
> `device.ui_agent` 目前还没有调用方，spec 里用 `hiddenimports` 显式带上了。

### 构建 Windows 安装包

前置：NSIS 3.x（`makensis` 在 PATH，或装在 `C:\Program Files (x86)\NSIS`）。

```bash
# 1) 图标（仓库已带 tools/icon.ico，改了设计才需要重生成）
python tools/make_icon.py

# 2) 打 exe
python -m PyInstaller --noconfirm SignRover.spec

# 3) 编译安装包（PROJ 必须传绝对路径）
"C:/Program Files (x86)/NSIS/makensis.exe" /DPROJ="D:/Liujiang/PythonProject/signrover" packaging/installer.nsi
```

产物：`dist/社区签到助手_v1.3.7_安装包.exe`（约 40 MB）。

安装包行为：

| 项 | 说明 |
|---|---|
| 界面 / 文件名 | 简体中文向导与中文安装包名（`社区签到助手_v<版本>_安装包.exe`） |
| 显示名 | 社区签到助手（开始菜单、桌面、控制面板一致） |
| 默认目录 | `D:\Games\SignRover`（**英文目录**，免 UAC 用户级安装；没有 D 盘时退回 `%LOCALAPPDATA%\Programs\SignRover`） |
| 自选目录 | 向导第二页可直接改路径；`/D=<目录>` 时以命令行指定为准 |
| 覆盖安装 | 自动读卸载注册表的 `InstallLocation`，发现旧安装就原地升级，不会被拽回默认盘 |
| 安装内容 | `SignRover.exe`、`_internal\`、`bin\`（自带 adb）、`使用说明.txt`、`uninstall.exe` |
| 旧版迁移 | 安装前自动调用旧版（中文目录 / Program Files）的卸载器，避免两份并存 |
| 快捷方式 | 桌面 + 开始菜单（含「使用说明」「卸载」） |
| 注册表 | 写 64 位视图（`SetRegView 64`）到 HKCU，控制面板可卸载 |
| 数据 | 账号与记录留在 `%USERPROFILE%\.signrover`，卸载默认保留 |
| 静默安装 | `安装包.exe /S /D=D:\某目录`（`/D` 须为最后一个参数、不加引号） |

> `.nsi` 脚本与 `使用说明.txt` 必须存成 **UTF-8 with BOM**，否则 makensis
> 会按系统 ACP 解析，中文全变乱码（`Bad text encoding`）。

## 凭证说明

### 库街区

只有一个 JWT（`eyJ...` 开头），**明文**存在 App 的 MMKV 文件里：

```
/data/data/com.kurogame.kjq/files/mmkv/user_data
```

并且 JWT 的 payload 直接带 `userId`：

```json
{"created":1793523407855,"userId":15416721}
```

所以不需要像其它脚本那样手动填 UID —— 提取时自动解出来。校验方式是调一次 `user/mineV2`，
返回 `code: 200` 才算有效。

> token 绑定设备，换设备登录会刷新旧 token，届时重新提取一次即可。
> 读 `/data/data` 需要 root：程序会自动执行 `adb root` 提权（adb 服务重启后会退回 shell 用户）。

### 米游社

米游社有两套登录态：

1. **Web 凭证**（`ltuid` / `cookie_token_v2` / `ltoken_v2` 等）—— 明文存在模拟器的 WebView cookie 库里，root 下直接读，用于游戏签到与角色查询。
2. **App 凭证**（`stuid` + `stoken` + `mid`）—— 加密存在 `porte_sdk_token_PRODUCT.xml`，但运行时明文驻留内存；root 下扫 `/proc/<pid>/mem` 可取，用于任务、米游币、社区打卡。

在「登录账号」里对米游社点「自动获取」，会一次性把两套都拿到：

1. 读 `app_webview/Default/Cookies` 拿 Web 凭证
2. 扫 App 进程内存，正则 `v2_[A-Za-z0-9_.=-]{100,240}` 抓候选 stoken
3. 用 `querySignInStatus` 逐个校验，取第一个真的能登录的

> 扫内存时脚本必须以 **LF** 换行推送到设备，Windows 下写成 CRLF 会让 `/system/bin/sh` 解析失败（这个坑踩过）。
> 如果 App 是被程序刚拉起的，内存里还没加载登录态，会等几秒并退回一次页面后重扫。

## 技术要点

### 库街区

- 单一域名 `https://api.kurobbs.com`，全部 `POST` + `application/x-www-form-urlencoded`
- 鉴权：请求头 `token: <JWT>`，另有 `devCode` / `distinct_id` / `channelId` / `version` 等客户端标识
- 返回 `{code, msg, data}`：`200` 成功，`220` token 失效，`522` 帖子已删除，`1551` 今日已签到，`1511` 游戏今日已签到
- 关键接口：

  | 用途 | 路径 |
  |---|---|
  | 账号信息 | `user/mineV2` |
  | 每日任务进度 | `encourage/level/getTaskProcess`（`gameId=0`） |
  | 绑定角色 | `user/role/findUserDefaultRole`（`queryUserId`） |
  | 帖子列表 | `forum/list`（`forumId=10` 今州茶馆最新） |
  | 浏览帖子 | `forum/getPostDetail` |
  | 点赞 / 取消 | `forum/like`（`operateType` 1 赞 / 2 取消） |
  | 分享上报 | `encourage/level/shareTask` |
  | 社区签到 | `user/signIn`（`gameId=2`，`geeTestData` 留空即可） |
  | 游戏签到信息 | `encourage/signIn/initSignInV2`（用 web 形态 UA） |
  | 游戏签到 | `encourage/signIn/v2`（同上） |

- 游戏 gameId：`2` = 战双帕弥什，`3` = 鸣潮；分版 forumId：`10` 鸣潮·今州茶馆、`9` 鸣潮·推荐、`2` 战双·推荐
- 点赞前若帖子已赞，先 `operateType=2` 取消再点，否则不加进度

### 米游社

- 域名迁移：社区侧 `bbs-api.miyoushe.com`，App 侧 `api-takumi.miyoushe.com`，游戏签到 `api-takumi.mihoyo.com`（绝区零是 `act-nap-api.mihoyo.com`）
- **DS 签名**：
  - DS1（`x-rpc-client_type: 5`）：`md5("salt=&t=&r=")`，r 是 6 位字母数字，盐随客户端版本变
  - DS2（`x-rpc-client_type: 2`）：`md5("salt=&t=&r=&b=&q=")`，r 是 6 位数字，query 需按 key 升序并逐项 URL 编码
  - DS2 的盐 `t0qEgfub6cvueAPgR5m9aQWWVciEer7v` 跨版本稳定 —— 社区打卡、点赞、分享全靠它
- 游戏签到只要 Cookie + `x-rpc-signgame` 头，不需要 DS；崩3/未定/崩2 不发送该头
- 各游戏 `act_id` 与 `signgame`（`communities/mihoyo/boards.py`）：

  | 游戏 | signgame | act_id |
  |---|---|---|
  | 原神 | hk4e | e202311201442471 |
  | 星穹铁道 | hkrpg | e202304121516551 |
  | 绝区零 | zzz | e202406242138391 |
  | 崩坏3 | bh3 | e202306201626331 |
  | 未定事件簿 | nxx | e202202251749321 |
  | 崩坏学园2 | bh2 | e202203291431091 |

- 帖子流 `/post/api/getForumPostList`：`forum_id` 用 gid，但原神(2)/绝区零(8) 常返回空列表，需跳过
- 点赞 `/post/api/post/upvote`，分享 `/post/api/sharePost`，评论 `/post/api/releaseReply`，发帖 `/post/api/releasePost/v2`
  （评论/发帖另有内容风控校验，参数待补，目前一律 `-10001`）
- 写操作接口密集请求会触发 HTTP 403，间隔建议 ≥ 2 秒

## 目录

```
app/            界面与后台线程（按 community 分派 provider）
  ui/runs_model.py  执行明细的表格模型（虚拟化渲染，几千行也不卡）
core/           模型、存储、社区注册表、DS 签名、设置、时间口径
communities/    社区接入层：mihoyo/ kuro/ trae/ qoder/ workbuddy/
device/         模拟器交互（adb 读凭证、界面自动化）
tools/          自检脚本、流量分析工具、图标与安装向导位图生成
packaging/      安装包脚本（NSIS）与随包的使用说明
bin/            随包分发的 adb
```

### 界面性能上的两个坑

1. **`QHeaderView.ResizeToContents` 不要全列开**。它会在每次插入单元格后重算列宽，
   配合 QTableWidget 逐格 setItem 是 O(n²)，几百行就能明显卡住。改用固定列宽 +
   最后一列 Stretch，表格换成 `QTableView + QAbstractTableModel`，只渲染可见行。
2. **后台线程必须收干净再退出**。窗口销毁时若 `QThread` 还在跑，Qt 会 fail-fast
   退出（0xC0000409，用户看到「程序已停止工作」）。`closeEvent` 里 requestInterruption
   → wait(3s) → terminate 兜底。

### 新增一个社区

界面（下拉框、导入字段、任务勾选、状态文案）全部由 `core/communities.py` 的注册表生成，
新增平台按下面三步走，**不需要动任何界面代码**：

1. 在 `core/communities.py` 里登记 `CommunityMeta`：

   | 字段 | 作用 |
   |---|---|
   | `key` / `name` / `pkg` / `currency` | 内部标识、界面显示名、模拟器包名、货币名 |
   | `import_fields` | 手动添加要填哪些项，`ImportField(key, label, required, placeholder)`；界面只显示必填项 + 该平台相关项 |
   | `tasks` | 任务页的勾选项，`TaskOption(key, label)`，顺序即界面顺序 |
   | `boards` / `default_gids` | 分板块的社区（如米游社）才有，用于板块勾选 |
   | `extract_tip` | 「自动获取」时的提示文案 |
   | `auto_award` | 任务完成即时到账（无「待领取」步骤）的平台置 `True` |

2. 在 `communities/<key>/` 下写 `client.py` + `provider.py`，provider 需提供
   `snapshot()` 和 `run_<task>()`（任务 key 与注册表 `tasks` 对应），返回 `list[TaskResult]`；
   并在模块末尾按约定导出 `Provider = XxxProvider`、`prepare_import(cred)`（校验导入字段）、
   `build_steps(options)`（把勾选项展开成执行步骤）。
3. `import_fields` 里如果出现全新的字段类型（现有 uid / token / stoken / mid / cookie），
   在 `app/ui/main_window.py` 的 `BUILDERS` 里补一个控件构造器即可，其余自动生效。

`provider_for(cred)` 按 `cred.community` 动态 import 对应模块，所以打包时
`SignRover.spec` 必须整包收集 `communities`（已用 `collect_submodules` 自动处理，
漏了会在安装后启动报 `ModuleNotFoundError`）。

