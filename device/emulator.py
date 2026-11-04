"""通过 adb 从模拟器内 App 提取登录凭证。

米游社（com.mihoyo.hyperion）两条链路：
1. Web 凭证（ltuid / cookie_token_v2 ...）—— 明文存在 WebView 的 Cookies 库里，直接读
2. App 凭证（stoken）—— 加密存在本地，但 App 运行时常驻内存，root 下扫 /proc/<pid>/mem 可取

库街区（com.kurogame.kjq）一条链路：
- JWT token 明文存在 MMKV 文件里（files/mmkv/user_data），且 payload 自带 userId

不需要代理、不需要证书、不需要 hook。
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.models import Credential

PKG = "com.mihoyo.hyperion"
COOKIE_DB = f"/data/data/{PKG}/app_webview/Default/Cookies"
LOGIN_XML = f"/data/data/{PKG}/shared_prefs/mihoyo_login.xml"
DEVICE_XML = f"/data/data/{PKG}/shared_prefs/pre_device.xml.xml"

# 库街区
KURO_PKG = "com.kurogame.kjq"
KURO_MMKV = f"/data/data/{KURO_PKG}/files/mmkv"
KURO_MMKV_FILES = ("user_data", "SP_NAME", "spUtils")

# JWT：库街区的 token 就是标准三段式 JWT
JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")

KEEP = (
    "ltoken", "ltuid", "cookie_token", "account_id", "ltmid",
    "ltoken_v2", "ltuid_v2", "cookie_token_v2", "account_id_v2", "ltmid_v2",
    "account_mid_v2", "DEVICEFP", "DEVICEFP_SEED_ID", "DEVICEFP_SEED_TIME",
    "_MHYUUID", "mi18nLang",
)

# 在设备上执行：遍历可读内存段，抓取 v2_ 开头的长 token
# 注意：脚本必须以 LF 换行推送，否则 /system/bin/sh 解析会失败
MEMSCAN = """#!/system/bin/sh
PID=$(pidof PKG_NAME)
if [ -z "$PID" ]; then echo NO_PID; exit 1; fi
OUT=/data/local/tmp/signrover_tok.txt
TMP=/data/local/tmp/signrover_tok.raw
rm -f $OUT $TMP
touch $TMP
awk '$2 ~ /^r/ {print $1}' /proc/$PID/maps | while read r; do
  s=${r%-*}
  e=${r#*-}
  si=$((0x$s))
  ei=$((0x$e))
  n=$(( (ei - si) / 4096 ))
  if [ $n -le 0 ]; then continue; fi
  if [ $n -gt 8192 ]; then n=8192; fi
  dd if=/proc/$PID/mem bs=4096 skip=$((si / 4096)) count=$n 2>/dev/null \\
    | grep -a -o -E 'v2_[A-Za-z0-9_.=-]{100,240}' >> $TMP
done
sort -u $TMP > $OUT
rm -f $TMP
wc -l < $OUT
"""


class AdbError(RuntimeError):
    pass


class Emulator:
    def __init__(self, serial: str | None = None, adb: str | None = None):
        self.serial = serial or ""
        self.adb = adb or self._find_adb()

    @staticmethod
    def _app_dirs() -> list[Path]:
        """可能要放 adb 的目录：exe 所在目录、打包资源目录、源码根目录。"""
        dirs: list[Path] = []
        if getattr(sys, "frozen", False):
            dirs.append(Path(sys.executable).resolve().parent)
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            dirs.append(Path(meipass))
        dirs.append(Path(__file__).resolve().parent.parent)
        return dirs

    @classmethod
    def _find_adb(cls) -> str:
        # 1) 用户在设置里指定的路径
        try:
            from core.settings import settings
            custom = settings().adb
        except Exception:                                   # noqa: BLE001
            custom = ""
        if custom and Path(custom).exists():
            return custom

        # 2) 随程序分发的 adb（安装目录下的 bin/）
        for d in cls._app_dirs():
            for rel in ("bin/adb.exe", "bin/adb", "adb.exe"):
                p = d / rel
                if p.exists():
                    return str(p)

        # 3) 系统 PATH
        p = shutil.which("adb")
        if p:
            return p

        # 4) 常见 SDK / 模拟器自带
        cands: list[str] = []
        for key in ("ANDROID_HOME", "ANDROID_SDK_ROOT", "ANDROID_SDK"):
            base = os.environ.get(key)
            if base:
                cands.append(str(Path(base) / "platform-tools" / "adb.exe"))
        cands += [
            "C:/Program Files/Netease/MuMuPlayer-12.0/shell/sdk/adb.exe",
            "C:/Program Files/Netease/MuMuPlayer-12.0/shell/adb.exe",
            "C:/Program Files/MuMuPlayer 12/shell/sdk/adb.exe",
            "D:/Program Files/MuMuPlayer 12/shell/sdk/adb.exe",
            "C:/Program Files/MuMuPlayer-12.0/shell/sdk/adb.exe",
            "C:/LDPlayer/LDPlayer9/adb.exe",
            "D:/LDPlayer/LDPlayer9/adb.exe",
            "C:/Program Files/Nox/bin/adb.exe",
            "D:/Program Files/Nox/bin/adb.exe",
            "C:/Program Files/BlueStacks_nxt/HD-Adb.exe",
        ]
        for cand in cands:
            if Path(cand).exists():
                return cand
        raise AdbError(
            "未找到 adb。请确认模拟器已安装并开启 ADB 调试，"
            "或在「设置」页手动填写 adb.exe 的完整路径。")

    def _base(self) -> list[str]:
        return [self.adb] + (["-s", self.serial] if self.serial else [])

    def _run(self, *args: str, timeout: int = 25) -> str:
        p = subprocess.run(self._base() + list(args), capture_output=True, timeout=timeout)
        return (p.stdout or p.stderr).decode("utf-8", "replace")

    def ensure_device(self) -> str:
        out = self._run("devices")
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                self.serial = parts[0]
                return parts[0]
        raise AdbError("没有已连接的模拟器，请先启动 mumu 并开启 adb 调试")

    def packages(self) -> list[str]:
        return [l.split(":", 1)[1].strip()
                for l in self._run("shell", "pm", "list", "packages").splitlines()
                if l.startswith("package:")]

    def is_installed(self, pkg: str = PKG) -> bool:
        return pkg in self.packages()

    def app_version(self, pkg: str = PKG) -> str:
        m = re.search(r"versionName=(\S+)", self._run("shell", "dumpsys", "package", pkg))
        return m.group(1) if m else ""

    def has_root(self) -> bool:
        return "uid=0" in self._run("shell", "id")

    def ensure_root(self) -> bool:
        """需要读 /data/data 时先提权：adb 重启后会自动退回 shell 用户。"""
        if self.has_root():
            return True
        self._run("root")
        time.sleep(2.5)
        return self.has_root()

    def _cat(self, remote: str) -> bytes:
        p = subprocess.run(self._base() + ["exec-out", f"cat {remote}"],
                           capture_output=True, timeout=40)
        return p.stdout

    def read_xml_prefs(self, remote: str) -> dict[str, str]:
        raw = self._cat(remote).decode("utf-8", "replace")
        return dict(re.findall(r'name="([^"]+)"[^>]*>([^<]*)<', raw))

    def ensure_running(self) -> bool:
        """确保 App 进程在跑；返回是否由本次调用拉起。"""
        out = self._run("shell", "pidof", PKG).strip()
        if out:
            return False
        self._run("shell", "am", "start", "-n",
                  f"{PKG}/.main.HyperionMainActivity")
        time.sleep(5)
        return True

    # ---------- Web 凭证 ----------
    def _read_cookies(self) -> dict[str, str]:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "Cookies"
            db.write_bytes(self._cat(COOKIE_DB))
            if db.stat().st_size == 0:
                raise AdbError("读取 cookie 库失败，请确认模拟器已开 root（mumu 设置→其他→root 权限）")
            con = sqlite3.connect(str(db))
            try:
                rows = con.execute("select host_key,name,value from cookies").fetchall()
            except sqlite3.DatabaseError as e:
                raise AdbError(f"cookie 库解析失败：{e}") from e
            finally:
                con.close()
        out: dict[str, str] = {}
        for _host, name, value in sorted(rows, key=lambda r: (r[0] != ".mihoyo.com", r[0])):
            if name in KEEP and value:
                out.setdefault(name, value)
        return out

    # ---------- stoken（内存扫描） ----------
    REMOTE_SCAN = "/data/local/tmp/signrover_scan.sh"
    REMOTE_OUT = "/data/local/tmp/signrover_tok.txt"

    def scan_stoken(self) -> list[str]:
        """扫描 App 进程内存，返回候选 stoken（需再验证有效性）。"""
        if not self.ensure_root():
            raise AdbError("读取 stoken 需要 root，请在 mumu 设置里开启 root 权限")
        started = self.ensure_running()

        toks = self._memscan_once()
        if not toks:
            # App 刚被拉起时内存里还没有登录态，等几秒再扫一次
            time.sleep(7 if started else 3)
            self._run("shell", "input", "keyevent", "4")   # 退回上一层，触发一次页面加载
            time.sleep(2)
            toks = self._memscan_once()
        return toks

    def _memscan_once(self) -> list[str]:
        with tempfile.TemporaryDirectory() as td:
            script = Path(td) / "scan.sh"
            # newline="\n" 必须显式指定，否则 Windows 会写成 CRLF 导致设备端 sh 解析失败
            script.write_text(MEMSCAN.replace("PKG_NAME", PKG), encoding="utf-8", newline="\n")
            p = subprocess.run(
                self._base() + ["push", str(script), self.REMOTE_SCAN],
                capture_output=True, timeout=30,
            )
            if p.returncode != 0:
                raise AdbError("推送扫描脚本失败：" + p.stderr.decode("utf-8", "replace").strip())

        # chmod 与执行串在一条 shell 里，和手工验证通过的流程保持一致
        out = self._run("shell", f"chmod 755 {self.REMOTE_SCAN} && sh {self.REMOTE_SCAN}", timeout=240)
        if "NO_PID" in out:
            return []

        raw = self._cat(self.REMOTE_OUT).decode("utf-8", "replace")
        toks = [l.strip() for l in raw.splitlines() if l.strip().startswith("v2_")]
        # 去重保序
        seen: set[str] = set()
        uniq = [t for t in toks if not (t in seen or seen.add(t))]
        # 优先长度 128 且以 CAE= 结尾的（米游社 v2 token 的典型形态）
        uniq.sort(key=lambda t: (not (len(t) == 128 and t.endswith("CAE=")), -len(t)))
        return uniq

    # ---------- 组合 ----------
    def extract_credential(self, with_stoken: bool = False, max_verify: int = 6) -> Credential:
        self.ensure_device()
        if not self.is_installed():
            raise AdbError(f"模拟器内未安装米游社（{PKG}）")

        cookies = self._read_cookies()
        login = self.read_xml_prefs(LOGIN_XML)
        uid = login.get("account_uid", "") or cookies.get("ltuid", "")

        cred = Credential(uid=uid, web_cookies=cookies)
        import html as _html
        local = _html.unescape(login.get("local_user_info", ""))
        m = re.search(r'"nickname":"([^"]*)"', local)
        cred.nickname = m.group(1) if m else ""
        cred.mid = cookies.get("ltmid_v2", "") or cookies.get("account_mid_v2", "")
        cred.device_fp = cookies.get("DEVICEFP", "")
        cred.device_id = cookies.get("_MHYUUID", "")
        ver = self.app_version()
        if ver:
            cred.app_version = ver

        if with_stoken:
            cands = self.scan_stoken()
            self._stoken_candidates = cands
            cred.stoken = ""
            # 逐个验证，取第一个真正能登录的；都失败则退回第一个候选
            import time
            for i, t in enumerate(cands[:max_verify]):
                if i:
                    time.sleep(1.5)  # 避免密集请求触发风控
                if self.verify_stoken(t, cred.uid, cred.mid):
                    cred.stoken = t
                    break
            if not cred.stoken and cands:
                cred.stoken = cands[0]
        return cred

    def verify_stoken(self, stoken: str, uid: str, mid: str) -> bool:
        """用只读接口验证 stoken 是否有效。"""
        import httpx
        try:
            r = httpx.get(
                "https://bbs-api.miyoushe.com/apihub/sapi/querySignInStatus",
                params={"gids": "2"},
                headers={
                    "Cookie": f"stuid={uid};stoken={stoken};mid={mid};",
                    "User-Agent": "okhttp/4.9.3",
                    "x-rpc-app_version": "2.117.0",
                    "x-rpc-client_type": "2",
                    "x-rpc-app_id": "bll8iq97cem8",
                    "x-rpc-verify_key": "bll8iq97cem8",
                },
                timeout=12,
            )
            return r.json().get("retcode") == 0
        except Exception:
            return False


    # ---------- 库街区 ----------
    def kuro_tokens(self) -> list[str]:
        """从 MMKV 文件里提取所有 JWT 候选（库街区 token 是明文的）。"""
        if not self.ensure_root():
            raise AdbError("读取 token 需要 root，请在 mumu 设置里开启 root 权限")
        toks: list[str] = []
        for name in KURO_MMKV_FILES:
            blob = self._cat(f"{KURO_MMKV}/{name}")
            if not blob:
                continue
            for m in JWT_RE.findall(blob.decode("utf-8", "replace")):
                if m not in toks:
                    toks.append(m)
        return toks

    def verify_kuro_token(self, token: str) -> dict | None:
        """调 mineV2 验证 token；有效则返回账号信息。"""
        from communities.kuro.client import KuroClient
        from communities.kuro.provider import decode_uid
        try:
            with KuroClient(token, decode_uid(token), min_interval=1.0) as c:
                r = c.mine()
                if r.ok and isinstance(r.data, dict):
                    return r.data.get("mine", {}) or {}
        except Exception:                    # noqa: BLE001
            return None
        return None

    def extract_kuro_credential(self, max_verify: int = 5) -> Credential:
        """一键提取库街区凭证：MMKV 取 JWT → 解 userId → 接口验活。"""
        self.ensure_device()
        if not self.is_installed(KURO_PKG):
            raise AdbError(f"模拟器内未安装库街区（{KURO_PKG}）")
        cands = self.kuro_tokens()
        if not cands:
            raise AdbError(
                "未在库街区本地数据里找到 token。\n请先在模拟器里打开库街区并完成登录，然后重试。")

        from communities.kuro.provider import decode_uid
        for i, tok in enumerate(cands[:max_verify]):
            if i:
                time.sleep(1.5)              # 避免密集请求触发风控
            mine = self.verify_kuro_token(tok)
            if not mine:
                continue
            cred = Credential(
                community="kuro",
                uid=decode_uid(tok),
                token=tok,
                nickname=mine.get("userName", "") or "",
            )
            ver = self.app_version(KURO_PKG)
            if ver:
                cred.app_version = ver
            cred.extra = {"user_id": cred.uid, "gold": mine.get("goldNum", 0)}
            return cred
        raise AdbError("找到的 token 全部校验失败，请在模拟器里重新登录库街区后再试。")


if __name__ == "__main__":
    e = Emulator()
    print("设备:", e.ensure_device(), "| 版本:", e.app_version(), "| root:", e.has_root())
    c = e.extract_credential()
    print("Web 凭证:", c.masked(), "| cookie 数:", len(c.web_cookies), "| mid:", c.mid)
    print("扫描 stoken…")
    for t in e.scan_stoken()[:3]:
        print(f"  len={len(t)} {t[:12]}… 有效={e.verify_stoken(t, c.uid, c.mid)}")
