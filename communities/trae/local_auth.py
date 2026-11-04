"""读取本机 Trae 客户端注册的真实设备号。

Trae 的签到接口会校验 `x-device-id`：必须是客户端在服务端真实注册过的
设备号。自己随机编一个，状态接口能查、领取必回 9074「当前参与用户太多」
——这句提示是幌子，跟人多不多没关系。

设备号是明文的，就写在客户端本地 storage.json 的**键名**里：
    %APPDATA%\\Trae CN\\User\\globalStorage\\storage.json
    iCubeAuthInfo://icube-dc:3629940323160202

注意：一个设备号一天只能给一个账号签到（同机多账号会互相顶掉），
多账号请各自在登录了对应账号的机器上导入。
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

_DIRS = ("Trae CN", "TRAE SOLO CN")
_KEY_RE = re.compile(r"^iCubeAuthInfo://icube-dc:(\d{10,20})$")


def read_client_device_id() -> str:
    """返回本机 Trae 客户端注册的设备号；读不到返回空串。"""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return ""
    for d in _DIRS:
        p = Path(appdata) / d / "User" / "globalStorage" / "storage.json"
        if not p.is_file():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        for k in data:
            m = _KEY_RE.match(str(k))
            if m:
                return m.group(1)
    return ""
