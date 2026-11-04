"""抓包流量分析工具（调试用）。

用途：米游社接口变更时，自己抓一次包确认请求形态。

用法：
    # 1. 抓包（在模拟器里操作 App，流量会写到 flows.mitm）
    python -m mitmproxy.tools.dump -p 8899 --set confdir=.mitm -w flows.mitm

    # 2. 分析
    python tools/flowdump.py flows.mitm --host miyoushe
    python tools/flowdump.py flows.mitm --url signIn --full
"""
from __future__ import annotations

import argparse
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("flow_file", help="mitmproxy 的 .mitm 流量文件")
    ap.add_argument("--host", default="", help="只显示 host 含该关键字的请求")
    ap.add_argument("--url", default="", help="只显示 url 含该关键字的请求")
    ap.add_argument("--full", action="store_true", help="打印完整请求头与响应")
    ap.add_argument("--limit", type=int, default=80)
    args = ap.parse_args()

    try:
        from mitmproxy import io
        from mitmproxy.http import HTTPFlow
    except ImportError:
        print("需要先安装 mitmproxy：python -m pip install mitmproxy", file=sys.stderr)
        return 1

    shown = 0
    with open(args.flow_file, "rb") as f:
        for flow in io.FlowReader(f).stream():
            if not isinstance(flow, HTTPFlow):
                continue
            url = flow.request.pretty_url
            if args.host and args.host not in flow.request.host:
                continue
            if args.url and args.url not in url:
                continue
            status = flow.response.status_code if flow.response else "-"
            print(f"\n{'=' * 88}\n{flow.request.method} {url}  -> {status}")
            if args.full:
                for k, v in flow.request.headers.items():
                    print(f"  {k}: {v[:200]}")
                if flow.request.content:
                    print("  body:", flow.request.get_text()[:400])
                if flow.response:
                    print("  resp:", flow.response.get_text()[:600])
            shown += 1
            if shown >= args.limit:
                break
    print(f"\n共显示 {shown} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
