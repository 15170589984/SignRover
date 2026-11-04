"""接口校准小工具：把某个平台的原始响应打出来，方便对字段。

用法：
    python tools/probe_platform.py qoder                 # 自动读本机 Qoder 登录态
    python tools/probe_platform.py qoder <token>
    python tools/probe_platform.py workbuddy <token> [uid]

只读，不会签到（workbuddy 除外时也只调状态查询）。输出里 token 一律脱敏。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def mask(tok: str) -> str:
    tok = tok or ""
    return f"{tok[:6]}…{tok[-4:]}（{len(tok)} 位）" if len(tok) > 12 else "(空/过短)"


def pretty(title: str, body) -> None:
    print(f"\n===== {title} =====")
    if isinstance(body, (dict, list)):
        print(json.dumps(body, ensure_ascii=False, indent=2)[:4000])
    else:
        print(str(body)[:2000])


def probe_qoder(token: str) -> int:
    from communities.qoder.client import (QoderClient, campaign_amount, parse_usage,
                                          pick_campaign, uid_of)
    if not token:
        from communities.qoder.local_auth import read_desktop_token
        token, info = read_desktop_token()
        print("本机登录态:", "读取成功" if token else "读取失败")
        if info:
            print("  过期时间:", info.get("expiresAt"))
    print("token:", mask(token))
    if not token:
        return 1
    with QoderClient(token) as c:
        ru = c.usage()
        print(f"usage -> HTTP {ru.http_status} {ru.code} {ru.msg}")
        pretty("usage.data", ru.data)
        if ru.ok:
            total, plan, addon = parse_usage(ru.data)
            print(f"解析：余额 {total}（套餐 {plan} + 加购 {addon}），uid {uid_of(ru.data)}")
        rc = c.campaigns()
        print(f"\ncampaigns -> HTTP {rc.http_status} {rc.code} {rc.msg}")
        c0 = pick_campaign(rc.data)
        pretty("当轮活动", c0)
        if c0:
            print("解析：奖励", campaign_amount(c0), "状态", c0.get("claimStatus"),
                  "窗口", c0.get("startAt"), "→", c0.get("endAt"))
    return 0


def probe_workbuddy(token: str, uid: str) -> int:
    from communities.workbuddy.client import (WorkBuddyClient, parse_resource,
                                              parse_status, uid_from_jwt)
    if not uid:
        uid = uid_from_jwt(token)
        if not uid:
            from communities.workbuddy.local_auth import read_account
            uid = read_account().get("uid", "")
    print("token:", mask(token), "| uid:", uid or "(空)")
    if not token:
        return 1
    with WorkBuddyClient(token, uid) as c:
        rs = c.checkin_status()
        print(f"\ncheckin-activity-status -> HTTP {rs.http_status} code={rs.code} {rs.msg}")
        pretty("status.data", rs.data)
        if rs.ok or rs.already:
            print("解析：今日已签", parse_status(rs.data))
        rr = c.resource()
        print(f"\nget-user-resource -> HTTP {rr.http_status} code={rr.code} {rr.msg}")
        pretty("resource.data", rr.data)
        if rr.ok:
            print("解析：可用积分", parse_resource(rr.data))
    return 0


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    what = args[0].lower()
    token = args[1] if len(args) > 1 else ""
    if what == "qoder":
        return probe_qoder(token)
    if what in ("workbuddy", "wb"):
        return probe_workbuddy(token, args[2] if len(args) > 2 else "")
    print("未知平台：", what)
    return 2


if __name__ == "__main__":
    sys.exit(main())
