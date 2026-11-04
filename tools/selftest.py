"""端到端自检：对每个社区「一键提取凭证 → 跑完整任务链 → 打印结果」。

用法：
    python tools/selftest.py            # 跑全部已装社区
    python tools/selftest.py kuro       # 只跑库街区
    python tools/selftest.py mihoyo     # 只跑米游社
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QCoreApplication, QTimer

from app.workers import ExtractWorker, RunWorker
from core.communities import ALL
from core.storage import Storage

OPTS = {
    "mihoyo": {
        "community": "mihoyo",
        "game_sign": True, "bbs_sign": True, "like": True, "share": True, "claim": True,
        "gids": ["6", "1", "4", "2", "8", "3"],
    },
    "kuro": {
        "community": "kuro",
        "bbs_sign": True, "game_sign": True, "browse": True, "like": True, "share": True,
    },
}


def main() -> None:
    only = sys.argv[1:] or [c.key for c in ALL]
    queue = [c for c in ALL if c.key in only]
    if not queue:
        print("没有匹配的社区，可选：" + ", ".join(c.key for c in ALL), flush=True)
        return

    app = QCoreApplication(sys.argv)
    storage = Storage()
    totals = {"success": 0, "failed": 0}

    def run_next() -> None:
        if not queue:
            print(f"\n===== 全部完成：成功 {totals['success']}，失败 {totals['failed']} =====", flush=True)
            app.quit()
            return
        meta = queue.pop(0)
        print(f"\n===== {meta.name}（{meta.key}）=====", flush=True)
        ex = ExtractWorker(community=meta.key)
        ex.step.connect(lambda s: print(f"[提取] {s}", flush=True))

        def on_cred(cred, meta=meta):
            storage.save_account(cred)
            mark = cred.token[:10] if meta.auth == "token" else cred.stoken[:10]
            print(f"[提取] OK {cred.masked()} 凭证={mark}…（已存库）", flush=True)
            w = RunWorker(cred, OPTS[meta.key], storage)
            w.log.connect(lambda lv, m: print(f"  [{lv}] {m}", flush=True))

            def finish(s, f):
                totals["success"] += s
                totals["failed"] += f
                print(f">> {meta.name}：成功 {s} 项，失败 {f} 项", flush=True)
                run_next()

            w.done.connect(finish)
            w.start()
            app._w = w

        def on_fail(msg, meta=meta):
            print(f"[提取] FAIL {meta.name}：{msg}", flush=True)
            totals["failed"] += 1
            run_next()

        ex.ok.connect(on_cred)
        ex.fail.connect(on_fail)
        ex.start()
        app._ex = ex

    run_next()
    QTimer.singleShot(900_000, app.quit)
    app.exec()


if __name__ == "__main__":
    main()
