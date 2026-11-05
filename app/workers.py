"""后台任务线程：按账号所属社区分派到对应的 provider。"""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from core.communities import KURO, get as community_of
from core.models import Credential, TaskStatus
from core.settings import settings
from core.storage import Storage


class ReleaseInfoWorker(QThread):
    """给「项目主页」按钮用：拿最新 Release 的安装包直链，点一下就开始下载。"""
    info = Signal(str, str)      # (版本号, 下载地址)
    fail = Signal(str)

    def __init__(self, repo_url: str, parent=None):
        super().__init__(parent)
        self.repo_url = repo_url.rstrip("/")

    def run(self) -> None:
        try:
            tag, url, _html = fetch_latest_release(self.repo_url)
            self.info.emit(tag, url)
        except Exception as e:                       # noqa: BLE001
            self.fail.emit(f"{type(e).__name__}: {e}")


def fetch_latest_release(repo_url: str) -> tuple[str, str, str]:
    """读 GitHub 最新 Release，返回 (版本号, 下载地址, 发布页地址)。

    下载地址优先取安装包附件（.exe，其次 .msi/.zip），没有附件就退回发布页。
    """
    import httpx
    api = repo_url.replace("https://github.com",
                           "https://api.github.com/repos") + "/releases/latest"
    r = httpx.get(api, timeout=8,
                  headers={"Accept": "application/vnd.github+json",
                           "User-Agent": "SignRover-UpdateCheck"})
    if r.status_code == 404:
        raise RuntimeError("还没有发布任何 Release")
    r.raise_for_status()
    data = r.json()
    tag = (data.get("tag_name") or "").lstrip("vV")
    if not tag:
        raise RuntimeError("Release 数据格式异常")
    html = data.get("html_url") or f"{repo_url}/releases/latest"
    assets = data.get("assets") or []
    url = ""
    for suffix in (".exe", ".msi", ".zip"):
        for a in assets:
            name = str(a.get("name") or "").lower()
            if name.endswith(suffix) and a.get("browser_download_url"):
                url = a["browser_download_url"]
                break
        if url:
            break
    return tag, (url or html), html


def _version_tuple(v: str) -> tuple[int, ...]:
    parts = []
    for seg in v.split("."):
        digits = "".join(ch for ch in seg if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


class RefreshWorker(QThread):
    """拉取账号数据（任务进度 + 社区货币 + 角色）。"""
    ok = Signal(object)          # AccountSnapshot / KuroSnapshot
    fail = Signal(str)

    def __init__(self, cred: Credential, storage: Storage | None = None, parent=None):
        super().__init__(parent)
        self.cred = cred
        self.storage = storage

    def run(self) -> None:
        from core.communities import provider_for
        try:
            with provider_for(self.cred, self.storage) as p:
                snap = p.snapshot()
            # snapshot 里可能补全了昵称，回写一次
            if self.storage:
                self.storage.save_account(self.cred)
            self.ok.emit(snap)
        except Exception as e:                      # noqa: BLE001
            self.fail.emit(f"{type(e).__name__}: {e}")


class ExtractWorker(QThread):
    """从模拟器一键提取凭证。

    米游社：Web cookie + stoken（扫运行时内存）
    库街区：MMKV 里的 JWT，payload 自带 userId
    """
    ok = Signal(object)          # Credential
    fail = Signal(str)
    step = Signal(str)           # 进度文案

    def __init__(self, community: str = "mihoyo", serial: str | None = None,
                 max_verify: int = 6, parent=None):
        super().__init__(parent)
        self.community = community
        self.serial = serial
        self.max_verify = max_verify

    def run(self) -> None:
        from device.emulator import AdbError, Emulator
        try:
            e = Emulator(self.serial, adb=settings().adb or None)
            self.step.emit("检查设备连接…")
            e.ensure_device()
            if self.community == KURO.key:
                self._extract_kuro(e)
            else:
                self._extract_mihoyo(e)
        except AdbError as ex:
            self.fail.emit(str(ex))
        except Exception as ex:                      # noqa: BLE001
            self.fail.emit(f"{type(ex).__name__}: {ex}")

    def _extract_kuro(self, e) -> None:
        from device.emulator import KURO_PKG, AdbError
        if not e.is_installed(KURO_PKG):
            raise AdbError("模拟器内未安装库街区")
        self.step.emit("读取本地登录数据…")
        cands = e.kuro_tokens()
        if not cands:
            raise AdbError(
                "未在库街区本地数据里找到 token。\n请先在模拟器里打开库街区并完成登录，然后重试。")
        self.step.emit(f"校验 token（共 {len(cands)} 个候选）…")
        from core.communities import provider_for
        from communities.kuro.provider import decode_uid
        for i, tok in enumerate(cands[: self.max_verify]):
            if i:
                self.msleep(1200)
            mine = e.verify_kuro_token(tok)
            if not mine:
                continue
            from core.models import Credential
            cred = Credential(community=self.community, uid=decode_uid(tok), token=tok,
                              nickname=mine.get("userName", "") or "")
            ver = e.app_version(KURO_PKG)
            if ver:
                cred.app_version = ver
            cred.extra = {"user_id": cred.uid, "gold": mine.get("goldNum", 0)}
            self.ok.emit(cred)
            return
        raise AdbError("找到的 token 全部校验失败，请在模拟器里重新登录库街区后再试。")


class PrepareWorker(QThread):
    """跑 prepare_import：对 PC 工具平台自动读本机登录态，对所有平台做校验 / 补全。

    手动导入或「自动获取」拿到原始输入后，都交给它来统一解析 token、补全
    uid / 昵称、必要时联网校验有效性。成功 emit 补全后的 cred，失败 emit 文案。
    """

    ok = Signal(object)            # Credential（已补全）
    fail = Signal(str)             # 错误文案
    step = Signal(str)             # 进度文案

    def __init__(self, community: str, cred: Credential, parent=None):
        super().__init__(parent)
        self.community = community
        self.cred = cred

    def run(self) -> None:
        from core.communities import prepare_import
        try:
            self.step.emit("正在解析并校验凭证…")
            prepare_import(self.cred)
            self.ok.emit(self.cred)
        except ValueError as e:
            self.fail.emit(str(e))
        except Exception as e:                       # noqa: BLE001
            self.fail.emit(f"{type(e).__name__}: {e}")

    def _extract_mihoyo(self, e) -> None:
        from device.emulator import AdbError
        if not e.is_installed():
            raise AdbError("模拟器内未安装米游社")
        if not e.ensure_root():
            raise AdbError("读取 stoken 需要 root，请在 mumu 设置里开启 root 权限")
        self.step.emit("读取 Web 凭证…")
        cred = e.extract_credential(with_stoken=False)
        cred.community = self.community
        self.step.emit("扫描 App 内存获取 stoken（约 10–30 秒）…")
        cands = e.scan_stoken()
        if not cands:
            raise AdbError("未在内存中扫到 stoken。\n请确认米游社已登录并处于前台，然后重试。")
        self.step.emit(f"校验会话有效性（共 {len(cands)} 个候选）…")
        cred.stoken = ""
        for i, t in enumerate(cands[: self.max_verify]):
            if i:
                self.msleep(1500)
            if e.verify_stoken(t, cred.uid, cred.mid):
                cred.stoken = t
                break
        if not cred.stoken:
            raise AdbError("扫到的 token 全部校验失败。\n请在模拟器里重新登录米游社后再试。")
        self.ok.emit(cred)


def _log_line(r) -> tuple[str, str]:
    """把一条执行结果翻成日志：成功/跳过/失败，成功时带上到账数量。"""
    if r.status is TaskStatus.SUCCESS:
        gain = f"   +{r.points} {r.currency}" if r.points else ""
        return "success", f"✓ {r.target}：{r.message}{gain}"
    if r.status is TaskStatus.SKIPPED:
        return "skip", f"· {r.target}：{r.message}"
    return "error", f"✗ {r.target}：{r.message}"


class RunWorker(QThread):
    """执行勾选的任务。"""
    log = Signal(str, str)       # level: info/success/error/skip, message
    progress = Signal(int, int)  # done, total
    done = Signal(int, int)      # success, failed

    def __init__(self, cred: Credential, options: dict, storage: Storage | None = None, parent=None):
        super().__init__(parent)
        self.cred = cred
        self.options = options
        self.storage = storage

    def run(self) -> None:
        from core.communities import provider_for
        success = failed = 0
        try:
            with provider_for(self.cred, self.storage) as p:
                steps = p.build_steps(self.options)
                total = len(steps)
                for i, (name, fn) in enumerate(steps, 1):
                    if self.isInterruptionRequested():
                        self.log.emit("skip", "已停止，后面的任务没有执行")
                        break
                    self.log.emit("info", f"▶ 开始{name}")
                    self.progress.emit(i - 1, total)
                    try:
                        results = fn()
                    except Exception as e:                       # noqa: BLE001
                        self.log.emit("error", f"{name}异常：{type(e).__name__}: {e}")
                        failed += 1
                        continue
                    for r in results:
                        level, text = _log_line(r)
                        if r.status is TaskStatus.SUCCESS:
                            success += 1
                        elif r.status is not TaskStatus.SKIPPED:
                            failed += 1
                        self.log.emit(level, text)
                    self.progress.emit(i, total)
                self.log.emit("info", f"完成：成功 {success} 项，失败 {failed} 项")
        except Exception as e:                                   # noqa: BLE001
            self.log.emit("error", f"执行中断：{type(e).__name__}: {e}")
        finally:
            self.done.emit(success, failed)


class BatchRunWorker(QThread):
    """全部平台：按账号顺序依次跑，每个账号用自己的凭证和默认任务集。"""
    log = Signal(str, str)
    progress = Signal(int, int)
    done = Signal(int, int)      # success, failed

    def __init__(self, jobs: list[tuple[Credential, dict]], storage: Storage | None = None,
                 parent=None):
        super().__init__(parent)
        self.jobs = jobs
        self.storage = storage

    def run(self) -> None:
        from core.communities import provider_for
        success = failed = 0
        n = max(len(self.jobs), 1)
        stopped = False
        for idx, (cred, options) in enumerate(self.jobs, 1):
            if self.isInterruptionRequested():
                stopped = True
                break
            head = f"{cred.community_name} · {cred.display_name}"
            self.log.emit("info", f"━━━ [{idx}/{n}] {head} ━━━")
            try:
                with provider_for(cred, self.storage) as p:
                    steps = p.build_steps(options)
                    total = max(len(steps), 1)
                    for i, (name, fn) in enumerate(steps, 1):
                        if self.isInterruptionRequested():
                            stopped = True
                            break
                        self.log.emit("info", f"▶ 开始{name}")
                        self.progress.emit((idx - 1) * 100 + int((i - 1) / total * 100), n * 100)
                        try:
                            results = fn()
                        except Exception as e:                   # noqa: BLE001
                            self.log.emit("error", f"{name}异常：{type(e).__name__}: {e}")
                            failed += 1
                            continue
                        for r in results:
                            level, text = _log_line(r)
                            if r.status is TaskStatus.SUCCESS:
                                success += 1
                            elif r.status is not TaskStatus.SKIPPED:
                                failed += 1
                            self.log.emit(level, text)
            except Exception as e:                               # noqa: BLE001
                failed += 1
                self.log.emit("error", f"{head} 无法执行：{type(e).__name__}: {e}")
            if stopped:
                break
            self.progress.emit(idx * 100, n * 100)
        if stopped:
            self.log.emit("skip", "已停止，剩余账号没有执行")
        self.log.emit("info", f"全部完成：成功 {success} 项，失败 {failed} 项")
        self.done.emit(success, failed)