"""界面预览脚本（仅开发用）：用临时数据库把五个页面各截一张图。

不会碰用户真实数据（临时库在系统临时目录），也不会联网。
用法：python tools/preview_ui.py [输出目录]
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# 注意：不能用 offscreen 平台——该后端没有字体库，中文会全部渲染成方块。
# 这里用真实窗口渲染后 widget.grab()，不需要屏幕截图权限。

from PySide6.QtWidgets import QApplication, QComboBox  # noqa: E402

from app.ui.theme import apply_app_style               # noqa: E402
from core.models import CoinInfo, Credential, MissionItem   # noqa: E402
from core.storage import Storage                        # noqa: E402


def build_data() -> Storage:
    tmp = Path(tempfile.mkdtemp(prefix="signrover_preview_"))
    st = Storage(tmp / "preview.db")
    accounts = [
        Credential(community="mihoyo", uid="100000001", nickname="旅行者",
                   mid="0cudangi86_mhy", stoken="v2_preview"),
        Credential(community="kuro", uid="200000002", nickname="漂泊者", token="eyJpreview"),
        Credential(community="trae", uid="300000003", nickname="Trae 测试号", token="eyJpreview"),
        Credential(community="qoder", uid="019fd104-7fb1", nickname="Qoder 测试号", token="dt-preview"),
        Credential(community="workbuddy", uid="d61cf768-06fc", nickname="WorkBuddy 测试号",
                   token="eyJpreview"),
    ]
    for c in accounts:
        st.save_account(c)
    now = int(time.time())
    keys = [("mihoyo:100000001", "米游币"), ("kuro:200000002", "库洛币")]
    kinds = [("bbs_sign", "社区签到", 30), ("game_sign", "原神", 0), ("browse", "帖子浏览", 20),
             ("like", "点赞 5 次", 20), ("share", "分享帖子", 10), ("claim", "领取任务奖励", 10)]
    for i in range(48):
        acc, cur = keys[i % 2]
        kind, target, pts = kinds[i % len(kinds)]
        status = "success" if i % 7 else "skipped"
        msg = "已完成" if status == "success" else "今日已完成，跳过"
        st.add_run(acc, kind, target, status, msg, pts if status == "success" else 0, cur)
        if i % 5 == 0:
            st.add_run(acc, "game_sign", "崩坏：星穹铁道", "failed",
                       "接口返回：登录状态已失效，请重新提取凭证", 0, cur)
    st.add_coin_snapshot("mihoyo:100000001", 1280, 90)
    st.add_coin_snapshot("kuro:200000002", 640, 80)
    st.add_coin_snapshot("trae:300000003", 1958, 100)
    st.add_coin_snapshot("qoder:019fd104-7fb1", 100, 0)
    st.add_coin_snapshot("workbuddy:d61cf768-06fc", 320, 100)
    return st


class Snap:
    def __init__(self):
        self.daily = [
            MissionItem(1, "游戏每日签到", "原神 / 星铁", 0, 1, 1, True),
            MissionItem(2, "米游社社区签到", "+30 米游币", 30, 1, 1, True),
            MissionItem(3, "浏览 3 篇帖子", "+10 米游币", 10, 3, 2, False),
            MissionItem(4, "点赞 5 次", "+10 米游币", 10, 5, 5, False),
            MissionItem(5, "分享 1 次帖子", "+10 米游币", 10, 1, 0, False),
        ]
        self.more = []
        self.coin = CoinInfo(total=1280, today=90, can_get=20, received=70, cap=100)
        self.roles = []
        self.signed_boards = {}


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "ui"
    out.mkdir(parents=True, exist_ok=True)

    app = QApplication([])
    apply_app_style(app)

    st = build_data()

    # 预览时不要真的去请求接口
    from app.ui import main_window as mw
    mw.MainWindow.refresh_data = lambda self: None      # type: ignore[method-assign]

    win = mw.MainWindow(st)
    win.resize(1180, 760)
    win.show()
    app.processEvents()

    def shot(name: str) -> None:
        app.processEvents()
        p = out / f"{name}.png"
        win.grab().save(str(p))
        print("saved", p)

    # 总览：塞一份假快照，避免依赖网络
    win.page_dashboard.render(Snap())
    shot("01_dashboard")

    win.go(1)
    shot("02_accounts")

    win.go(2)
    shot("03_tasks")

    # 执行中的样子（日志 + 进度条 + 停止按钮）
    for lvl, msg in (
        ("info", "开始执行 · 库街区 · 漂泊者"),
        ("success", "社区签到 完成 +30 库洛币"),
        ("success", "游戏签到 鸣潮 · 漂泊者 完成"),
        ("skip", "浏览帖子 今日已完成，跳过"),
        ("error", "接口返回：登录状态已失效，请重新提取凭证"),
    ):
        win.page_tasks.append_log(lvl, msg)
    win.page_tasks._flush_log()
    win.page_tasks.set_running(True)
    win.page_tasks.set_progress(3, 5)
    shot("03b_tasks_running")
    win.page_tasks.set_running(False)

    # 全部平台模式
    i = win.page_tasks.cb_account.findData(win.page_tasks.ALL)
    if i >= 0:
        win.page_tasks.cb_account.setCurrentIndex(i)
        app.processEvents()
        shot("06_tasks_all")

    # 手动导入对话框（临时替换 exec，截完就退出）
    from PySide6.QtWidgets import QDialog
    real_exec = QDialog.exec

    def fake_exec(dlg):
        dlg.show()
        app.processEvents()
        dlg.grab().save(str(out / "07_import_dialog.png"))
        # 切到其它社区再抓两张，验证字段显隐是注册表驱动的
        boxes = dlg.findChildren(QComboBox)
        if boxes:
            for name, idx in (("07b_import_trae", 2), ("07c_import_kuro", 1),
                              ("07d_import_qoder", 3), ("07e_import_workbuddy", 4)):
                boxes[0].setCurrentIndex(idx)
                app.processEvents()
                dlg.grab().save(str(out / (name + ".png")))
        dlg.close()
        return QDialog.DialogCode.Rejected

    QDialog.exec = fake_exec                     # type: ignore[method-assign]
    win.page_accounts.add_manual()
    QDialog.exec = real_exec                     # type: ignore[method-assign]
    print("saved", out / "07_import_dialog.png")

    win.go(3)
    win.page_logs.reload(force=True)
    shot("04_logs")

    win.go(4)
    shot("05_settings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
