"""应用入口。"""
from __future__ import annotations

import sys
from pathlib import Path

# 允许 python app/main.py 直接运行
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.ui.theme import apply_app_style
from core.storage import Storage


def _resource_root() -> Path:
    """兼容源码运行与 PyInstaller 打包后的资源目录。"""
    meipass = getattr(sys, "_MEIPASS", None)
    return Path(meipass) if meipass else ROOT


def _setup_tls() -> None:
    """打包后让 OpenSSL 用随包的 certifi 证书。

    onedir 里 Python 找不到系统证书路径，httpx 的默认 verify 会直接报
    CERTIFICATE_VERIFY_FAILED。这里把证书位置显式写进环境变量，
    `ssl.create_default_context()` 就会按它加载。
    """
    try:
        import certifi
        cafile = certifi.where()
    except Exception:                    # noqa: BLE001
        return
    if not Path(cafile).is_file():
        return
    import os
    os.environ.setdefault("SSL_CERT_FILE", cafile)
    os.environ.setdefault("SSL_CERT_DIR", str(Path(cafile).parent))
    os.environ.setdefault("REQUESTS_CA_BUNDLE", cafile)


_setup_tls()


def _selftest() -> int:
    """打包自检：确认动态导入的 provider 都被收进包里。

    provider 是按社区名在运行时 import 的，PyInstaller 静态分析扫不到，
    漏收时只有在界面上添加账号才会暴露。打包后用
    `SignRover.exe --selftest` 跑一遍即可验证。
    """
    from core.communities import ALL, provider_for
    from core.models import Credential

    failed = 0
    lines: list[str] = []
    for meta in ALL:
        cred = Credential(community=meta.key, uid="selftest", token="dummy",
                          stoken="v2_dummy", mid="dummy")
        try:
            p = provider_for(cred)
            p.close()
            lines.append(f"[OK]   {meta.key:8s} {type(p).__name__}")
        except (ModuleNotFoundError, SyntaxError) as e:
            failed += 1
            lines.append(f"[FAIL] {meta.key:8s} 加载失败：{type(e).__name__}: {e}")
        except Exception as e:                       # noqa: BLE001
            # 构造阶段的凭证校验失败不算打包问题
            lines.append(f"[ok]   {meta.key:8s} 已加载（{type(e).__name__}: {e}）")
    lines.append("SELFTEST " + ("FAILED" if failed else "PASSED"))
    # 打包后是窗口程序，没有控制台，结果同时落盘
    try:
        import tempfile
        out = Path(tempfile.gettempdir()) / "signrover_selftest.txt"
        out.write_text("\n".join(lines), encoding="utf-8")
        lines.append(f"(写入 {out})")
    except OSError:
        pass
    print("\n".join(lines))
    return 1 if failed else 0


def _uitest() -> int:
    """界面冒烟：用临时库把主窗口建起来再退出，验证打包后 UI 模块齐全。

    比 --selftest 更进一步——它会真正实例化所有页面，能抓到只在
    界面代码里才触发的导入 / 属性错误。
    """
    import tempfile

    from app.ui.main_window import MainWindow
    from core.storage import Storage

    tmp = Path(tempfile.mkdtemp(prefix="signrover_uitest_"))
    st = Storage(tmp / "ui.db")
    try:
        win = MainWindow(st)
        win.resize(1180, 760)
        win.show()
        for i in range(5):                     # 依次切一遍每个页面
            win.go(i)
            QApplication.processEvents()
        win.hide()
        msg = "UITEST PASSED"
        code = 0
    except Exception as e:                     # noqa: BLE001
        msg = f"UITEST FAILED: {type(e).__name__}: {e}"
        code = 1
    finally:
        try:
            st.close()
        except Exception:                      # noqa: BLE001
            pass
    try:
        out = Path(tempfile.gettempdir()) / "signrover_uitest.txt"
        out.write_text(msg, encoding="utf-8")
    except OSError:
        pass
    print(msg)
    return code


def _probe(platform: str) -> int:
    """接口自检：`SignRover.exe --probe qoder` 把原始响应写到临时文件。

    窗口程序没有控制台，结果落盘便于排查；token 只显示掩码，不写明文。
    """
    import json
    import tempfile

    lines: list[str] = []

    def add(msg: str) -> None:
        lines.append(msg)
        print(msg)

    try:
        if platform == "tls":
            import os
            import ssl
            try:
                import certifi
                cafile = certifi.where()
            except Exception as e:                # noqa: BLE001
                cafile = f"(导入失败 {e})"
            add(f"certifi.where() = {cafile}")
            add(f"  文件存在 = {Path(str(cafile)).is_file()}")
            add(f"SSL_CERT_FILE = {os.environ.get('SSL_CERT_FILE')}")
            add(f"SSL_CERT_DIR = {os.environ.get('SSL_CERT_DIR')}")
            add(f"HTTPS_PROXY = {os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')}")
            add(f"frozen = {getattr(sys, 'frozen', False)} MEIPASS = {getattr(sys, '_MEIPASS', '')}")
            ctx = ssl.create_default_context()
            add(f"默认信任证书数 = {len(ctx.get_ca_certs())}")
            if Path(str(cafile)).is_file():
                ctx.load_verify_locations(cafile=str(cafile))
                add(f"加载 cacert.pem 后信任证书数 = {len(ctx.get_ca_certs())}")
            import socket
            for host in ("openapi.qoder.com.cn", "www.workbuddy.cn", "api.trae.cn"):
                try:
                    with socket.create_connection((host, 443), 6) as raw:
                        with ctx.wrap_socket(raw, server_hostname=host) as ss:
                            add(f"{host} 握手成功 {ss.version()}")
                except Exception as e:            # noqa: BLE001
                    add(f"{host} 握手失败 {type(e).__name__}: {e}")
            import httpx
            for verify in (str(cafile), True, False):
                try:
                    r = httpx.get("https://openapi.qoder.com.cn/sash/api/v2/me/usage",
                                  verify=verify, timeout=10)
                    add(f"httpx verify={verify!r} -> HTTP {r.status_code}")
                except Exception as e:            # noqa: BLE001
                    add(f"httpx verify={verify!r} -> {type(e).__name__}: {e}")
        elif platform == "qoder":
            from communities.qoder.client import (QoderClient, campaign_amount,
                                                  parse_usage, pick_campaign, uid_of)
            from communities.qoder.local_auth import read_desktop_token
            token, info = read_desktop_token()
            add(f"本机登录态：{'读取成功' if token else '读取失败'}")
            if info.get("error"):
                add(f"  原因：{info['error']}")
            if token:
                add(f"  token={token[:6]}…（{len(token)} 位）过期={info.get('expiresAt')}")
            if not token:
                add("没有读到登录态：先登录一次 Qoder 客户端，或手动粘贴 token")
                raise SystemExit(1)
            with QoderClient(token) as c:
                ru = c.usage()
                add(f"usage -> HTTP {ru.http_status} {ru.code} {ru.msg}")
                if ru.ok:
                    total, plan, addon = parse_usage(ru.data)
                    add(f"  余额 {total}（套餐 {plan} + 加购 {addon}）uid {uid_of(ru.data)}")
                rc = c.campaigns()
                add(f"campaigns -> HTTP {rc.http_status} {rc.code} {rc.msg}")
                c0 = pick_campaign(rc.data)
                if c0:
                    add(f"  当轮 {c0.get('campaignKey')} 奖励 {campaign_amount(c0)} "
                        f"状态 {c0.get('claimStatus')} 窗口 {c0.get('startAt')}→{c0.get('endAt')}")
                add("原始 usage：" + json.dumps(ru.data, ensure_ascii=False)[:600])
        elif platform == "workbuddy":
            import os

            from communities.workbuddy.client import WorkBuddyClient
            from communities.workbuddy.local_auth import read_account
            acc = read_account()
            add(f"本机账号信息：uid={acc.get('uid') or '(无)'} 域名={acc.get('domain') or '(无)'}")
            token = os.environ.get("SIGNROVER_WB_TOKEN", "").strip()
            if not token:
                # 没有 token 时只做可达性校验：路径正确的话未鉴权应返回 401/403
                with WorkBuddyClient("", acc.get("uid", "")) as c:
                    for name, fn in (("checkin-status", c.checkin_status),
                                     ("resource", c.resource)):
                        r = fn()
                        add(f"{name}（无凭证）-> HTTP {r.http_status} code={r.code} "
                            f"{'路径正确' if r.token_invalid else '响应异常'} {r.raw[:120]}")
                add("要看真实数据：设置环境变量 SIGNROVER_WB_TOKEN 后再跑一次")
                raise SystemExit(0)
            with WorkBuddyClient(token, acc.get("uid", "")) as c:
                rs = c.checkin_status()
                add(f"checkin-status -> HTTP {rs.http_status} code={rs.code} {rs.msg}")
                add("  原始：" + json.dumps(rs.data, ensure_ascii=False)[:500])
                rr = c.resource()
                add(f"resource -> HTTP {rr.http_status} code={rr.code} {rr.msg}")
                add("  原始：" + json.dumps(rr.data, ensure_ascii=False)[:500])
        else:
            add(f"不支持的平台：{platform}（支持 qoder / workbuddy / tls）")
            raise SystemExit(2)
    except SystemExit:
        raise
    except Exception as e:                      # noqa: BLE001
        add(f"失败：{type(e).__name__}: {e}")
        raise SystemExit(1)
    finally:
        try:
            out = Path(tempfile.gettempdir()) / "signrover_probe.txt"
            out.write_text("\n".join(lines), encoding="utf-8")
            print(f"(写入 {out})")
        except OSError:
            pass
    return 0


def main() -> int:
    # --version 自证版本：安装包升级后核验程序体是不是真的换新了
    if "--version" in sys.argv or "-V" in sys.argv:
        from core.version import VERSION
        print(f"SignRover {VERSION}")
        try:
            import tempfile
            out = Path(tempfile.gettempdir()) / "signrover_version.txt"
            out.write_text(VERSION, encoding="utf-8")
        except OSError:
            pass
        return 0
    if "--selftest" in sys.argv:
        return _selftest()
    if "--probe" in sys.argv:
        i = sys.argv.index("--probe")
        return _probe(sys.argv[i + 1] if i + 1 < len(sys.argv) else "")

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("社区签到助手")
    app.setApplicationDisplayName("社区签到助手")
    apply_app_style(app)
    if "--uitest" in sys.argv:
        return _uitest()
    # 关窗后由 MainWindow.closeEvent 负责结束进程：
    # 如果交给「最后一个窗口关闭就退出」，Qt 会在后台线程还活着时销毁它们并崩溃
    app.setQuitOnLastWindowClosed(False)

    ico = _resource_root() / "icon.ico"
    if ico.exists():
        app.setWindowIcon(QIcon(str(ico)))

    storage = Storage()
    from app.ui.main_window import MainWindow
    win = MainWindow(storage)
    win.show()
    code = app.exec()
    storage.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
