"""主窗口：左侧导航 + 五个页面。"""
from __future__ import annotations

import html
import json
import re
import os
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog,
                               QFormLayout, QFrame, QHBoxLayout, QHeaderView, QInputDialog,
                               QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar,
                               QPushButton, QSpinBox, QStackedWidget, QTableView, QTableWidget,
                               QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)

from app.ui.theme import GOLD, GREEN, PRIMARY, RED, TEXT, TEXT_MUTED, TEXT_SUB
from app.ui.widgets import (Card, StatCard, dot, field_label, ghost_button, hint,
                            muted, page_header, pager_button, search_box, title)
from app.workers import RefreshWorker, RunWorker
from communities.mihoyo.boards import BOARDS, SIGNABLE
from core.models import Credential, TaskStatus
from core.storage import Storage
from core.version import VERSION as APP_VERSION

NAV = [("dashboard", "总览"), ("accounts", "账号"), ("tasks", "任务"),
       ("logs", "执行明细"), ("settings", "设置")]


class MainWindow(QMainWindow):
    def __init__(self, storage: Storage):
        super().__init__()
        self.storage = storage
        self.accounts: list[Credential] = storage.list_accounts()
        self.current: Credential | None = self.accounts[0] if self.accounts else None
        self._worker = None
        self._refresh_worker = None
        self._refresh_pending = False
        self._closing = False

        self.setWindowTitle("社区签到助手")
        self.resize(1180, 760)
        self._build()
        self._load_accounts()
        if self.current:
            QTimer.singleShot(300, self.refresh_data)

    # ---------------- 布局 ----------------
    def _build(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._sidebar())

        self.stack = QStackedWidget()
        self.page_dashboard = DashboardPage(self)
        self.page_accounts = AccountsPage(self)
        self.page_tasks = TasksPage(self)
        self.page_logs = LogsPage(self)
        self.page_settings = SettingsPage(self)
        for p in (self.page_dashboard, self.page_accounts, self.page_tasks,
                  self.page_logs, self.page_settings):
            p.setObjectName("Page")
            self.stack.addWidget(p)
        outer.addWidget(self.stack, 1)

        self.statusBar().showMessage("就绪")

    def _sidebar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("Sidebar")
        bar.setFixedWidth(204)
        lay = QVBoxLayout(bar)
        lay.setContentsMargins(0, 0, 0, 12)
        lay.setSpacing(0)

        # 品牌区：色块 logo + 名称 + 副标题
        head = QWidget()
        h = QHBoxLayout(head)
        h.setContentsMargins(16, 18, 16, 16)
        h.setSpacing(10)
        logo = QLabel("签")
        logo.setObjectName("Logo")
        logo.setFixedSize(30, 30)
        logo.setAlignment(Qt.AlignCenter)
        h.addWidget(logo)
        names = QVBoxLayout()
        names.setContentsMargins(0, 0, 0, 0)
        names.setSpacing(1)
        brand = QLabel("社区签到助手")
        brand.setObjectName("Brand")
        sub = QLabel("每日自动任务")
        sub.setObjectName("BrandSub")
        names.addWidget(brand)
        names.addWidget(sub)
        h.addLayout(names)
        h.addStretch(1)
        lay.addWidget(head)

        sec = QLabel("功能")
        sec.setObjectName("NavSection")
        lay.addWidget(sec)
        lay.addSpacing(4)

        self.nav_buttons: list[QPushButton] = []
        for i, (key, label) in enumerate(NAV):
            b = QPushButton(label)
            b.setObjectName("Nav")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, idx=i: self.go(idx))
            lay.addWidget(b)
            self.nav_buttons.append(b)
        self.nav_buttons[0].setChecked(True)
        lay.addStretch(1)

        foot = QLabel(f"v{APP_VERSION} · 本地运行")
        foot.setObjectName("SideFoot")
        foot.setAlignment(Qt.AlignCenter)
        lay.addWidget(foot)
        return bar

    def go(self, idx: int) -> None:
        self.stack.setCurrentIndex(idx)
        for i, b in enumerate(self.nav_buttons):
            b.setChecked(i == idx)
        if idx == 3:
            self.page_logs.ensure_loaded()

    # ---------------- 账号 ----------------
    def _load_accounts(self) -> None:
        self.accounts = self.storage.list_accounts()
        if self.accounts:
            keys = [a.key for a in self.accounts]
            if not self.current or self.current.key not in keys:
                self.current = self.accounts[0]
        else:
            self.current = None
        self.page_dashboard.set_accounts(self.accounts, self.current)
        self.page_accounts.reload(self.accounts)
        self.page_tasks.set_accounts(self.accounts, self.current)
        self.page_logs.refresh_accounts(self.accounts, self.current)
        self.page_dashboard.render_empty() if not self.current else None

    def switch_account(self, key: str) -> None:
        for a in self.accounts:
            if a.key == key:
                self.current = a
                break
        # 先把界面切到骨架屏：即使上一轮刷新还在跑，也不能让旧账号的
        # 余额和任务在新账号下多挂几秒。
        self.page_dashboard.set_loading(True)
        self.page_tasks.set_account(self.current)
        if self.current:
            self.page_dashboard.apply_currency(self.current.currency)
        self.page_logs.invalidate()      # 明细页「当前账号」那一项要跟着变
        self.refresh_data()

    # ---------------- 数据刷新 ----------------
    def refresh_data(self) -> None:
        if self._closing:
            return
        if not self.current:
            self.statusBar().showMessage("还没有账号，请先到「账号」页添加")
            return
        if self._refresh_worker and self._refresh_worker.isRunning():
            # 正在拉取时又要刷新（比如刚执行完任务），等这一轮结束再补一次，
            # 否则「今日已获」会停在执行前的旧数字上。
            self._refresh_pending = True
            return
        self._refresh_pending = False
        self.statusBar().showMessage("正在拉取账号数据…")
        self.page_dashboard.set_loading(True)
        w = RefreshWorker(self.current, self.storage)
        w.ok.connect(self._on_snapshot)
        w.fail.connect(self._on_refresh_fail)
        self._refresh_worker = w
        w.start()

    def _after_refresh(self) -> None:
        """一轮刷新收尾：若期间又请求过刷新，补跑一次。"""
        if self._closing:
            return
        if self._refresh_pending:
            self._refresh_pending = False
            QTimer.singleShot(120, self.refresh_data)

    def _on_snapshot(self, snap) -> None:
        # 切换账号后上一轮刷新可能才返回：这份数据属于旧账号，画上去就是串号。
        w = self._refresh_worker
        if (w is not None and self.current
                and getattr(getattr(w, "cred", None), "key", "") != self.current.key):
            self._after_refresh()
            return
        self.page_dashboard.set_loading(False)
        self.page_dashboard.render(snap)
        if self.current:
            self.current.nickname = self.current.nickname or ""
        self.accounts = self.storage.list_accounts()
        for a in self.accounts:
            if self.current and a.key == self.current.key:
                self.current = a
                break
        self.page_accounts.reload(self.accounts)
        cur = self.current.currency if self.current else "积分"
        self.statusBar().showMessage(
            f"已更新 · {cur} {snap.coin.total} · 今日 +{snap.coin.today}")
        self._after_refresh()

    def _on_refresh_fail(self, msg: str) -> None:
        w = self._refresh_worker
        if (w is not None and self.current
                and getattr(getattr(w, "cred", None), "key", "") != self.current.key):
            self._after_refresh()       # 旧账号的失败，与当前账号无关
            return
        self.page_dashboard.set_loading(False)
        self.statusBar().showMessage(f"拉取失败：{msg}")
        self._after_refresh()
        QMessageBox.warning(self, "拉取失败", msg)

    # ---------------- 执行 ----------------
    def run_tasks(self, options: dict) -> None:
        if not self.current:
            QMessageBox.information(self, "提示", "请先添加账号")
            return
        if self._worker and self._worker.isRunning():
            QMessageBox.information(self, "提示", "任务正在执行中")
            return
        self.page_tasks.clear_log()
        self.page_tasks.set_running(True)
        w = RunWorker(self.current, options, self.storage)
        w.log.connect(self.page_tasks.append_log)
        w.progress.connect(self.page_tasks.set_progress)
        w.done.connect(self._on_run_done)
        self._worker = w
        w.start()

    def _on_run_done(self, success: int, failed: int) -> None:
        self.page_tasks.set_running(False)
        self.statusBar().showMessage(f"执行完成：成功 {success}，失败 {failed}")
        self.page_logs.invalidate()      # 有新记录才需要重查，不进页面就不查
        QTimer.singleShot(800, self.refresh_data)

    def run_all_tasks(self, jobs: list[tuple[Credential, dict]]) -> None:
        """全部平台：按账号顺序依次执行。"""
        if not jobs:
            QMessageBox.information(self, "提示", "没有可执行的账号")
            return
        if self._worker and self._worker.isRunning():
            QMessageBox.information(self, "提示", "任务正在执行中")
            return
        self.page_tasks.clear_log()
        self.page_tasks.set_running(True)
        from app.workers import BatchRunWorker
        w = BatchRunWorker(jobs, self.storage)
        w.log.connect(self.page_tasks.append_log)
        w.progress.connect(self.page_tasks.set_progress)
        w.done.connect(self._on_run_done)
        self._worker = w
        w.start()

    def stop_tasks(self) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.requestInterruption()
            self.page_tasks.btn_stop.setEnabled(False)
            self.page_tasks.btn_stop.setText("停止中…")
            self.page_tasks.append_log("skip", "已请求停止，等当前步骤跑完就收尾")
            self.statusBar().showMessage("正在停止…")

    # ---------------- 退出 ----------------
    def closeEvent(self, event) -> None:      # noqa: N802
        """关窗口先收后台线程，再退进程。

        两个坑都踩过：
        1. 线程还在跑就销毁窗口，Qt 直接 fail-fast（0xC0000409），用户看到「程序已停止工作」；
        2. 线程卡在 httpx 的网络读里时，QThread.terminate() 会把解释器锁死，进程反而关不掉。
        所以这里只「请求中断」，然后短暂宽限再硬退进程——写库都是即时提交的，
        不会丢账号和签到状态。
        """
        self._closing = True
        for attr in ("_refresh_worker", "_worker"):
            w = getattr(self, attr, None)
            try:
                if w is not None and w.isRunning():
                    w.requestInterruption()
            except RuntimeError:
                pass
        super().closeEvent(event)
        QTimer.singleShot(400, lambda: os._exit(0))


# ==================== 页面 ====================
class TaskRowWidget(QWidget):
    """总览里的单条任务行。

    复用同一批控件、每次只改文字：每次刷新都销毁重建会连带触发整块布局
    重算，总览刷新时的顿挫感主要来自这里。
    """

    def __init__(self):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 7, 2, 7)
        lay.setSpacing(9)
        self.mark = dot(TEXT_MUTED)
        lay.addWidget(self.mark)
        self.name = QLabel("-")
        self.name.setMinimumWidth(170)
        lay.addWidget(self.name)
        self.prog = QLabel("")
        self.prog.setObjectName("Hint")
        self.prog.setMinimumWidth(48)
        lay.addWidget(self.prog)
        lay.addStretch(1)
        self.tag = QLabel("")
        lay.addWidget(self.tag)

    def set_data(self, m, currency: str, auto_award: bool) -> None:
        done = bool(m.done)
        self.mark.setStyleSheet(
            f"background:{GREEN if done else TEXT_MUTED};border-radius:4px;")
        self.name.setText(m.name)
        self.name.setStyleSheet(f"color:{TEXT if done else '#3A4252'};")
        self.prog.setText(m.progress or "")
        if m.is_get_award:
            text, color, weight = ("已完成" if auto_award else "已领取"), TEXT_MUTED, "400"
        elif done:
            text = "已完成" if auto_award else f"待领取 +{m.points}"
            color, weight = (TEXT_SUB, "400") if auto_award else (PRIMARY, "600")
        else:
            text, color, weight = f"+{m.points} {currency}", GOLD, "500"
        self.tag.setText(text)
        self.tag.setStyleSheet(f"color:{color};font-weight:{weight};font-size:12.5px;")


class DashboardPage(QWidget):
    def __init__(self, win: MainWindow):
        super().__init__()
        self.win = win
        self._rows: list[TaskRowWidget] = []
        self._roles: list[QLabel] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(14)

        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(page_header("总览", "数据来自平台接口，可随时重新拉取"))
        head.addStretch(1)
        self.account_box = QComboBox()
        # 固定宽度：切换账号时列表长短不一，宽度跟着跳很难看
        self.account_box.setFixedWidth(250)
        self.account_box.currentIndexChanged.connect(self._on_account_change)
        head.addWidget(self.account_box)
        btn_refresh = ghost_button("刷新")
        btn_refresh.clicked.connect(self.win.refresh_data)
        head.addWidget(btn_refresh)
        btn_run = QPushButton("一键执行")
        btn_run.setObjectName("Primary")
        btn_run.setCursor(Qt.PointingHandCursor)
        btn_run.clicked.connect(lambda: self.win.go(2))
        head.addWidget(btn_run)
        lay.addLayout(head)

        stats = QHBoxLayout()
        stats.setSpacing(12)
        self.card_coin = StatCard("当前货币", "-", "账号余额", GOLD)
        self.card_today = StatCard("今日已获", "-", "今日入账", GREEN)
        self.card_can = StatCard("可领取", "-", "已完成未领取", PRIMARY)
        self.card_task = StatCard("任务完成", "-", "每日任务进度", None)
        for c in (self.card_coin, self.card_today, self.card_can, self.card_task):
            c.setMinimumHeight(94)
            stats.addWidget(c, 1)

        self.task_card = Card(padding=18, spacing=4)
        self.task_card_title = title("每日任务")
        self.task_card.body().addWidget(self.task_card_title)
        self.task_card.body().addSpacing(2)
        self.task_list_box = QVBoxLayout()
        self.task_list_box.setSpacing(0)
        self.task_card.body().addLayout(self.task_list_box)

        self.roles_card = Card(padding=18, spacing=6)
        self.roles_card.body().addWidget(title("绑定角色"))
        self.roles_box = QVBoxLayout()
        self.roles_box.setSpacing(4)
        self.roles_card.body().addLayout(self.roles_box)

        # 内容区 + 骨架屏做成可切换的两页：切换账号拉数据期间显示骨架，
        # 不能让上一份账号的数据还挂在界面上造成误读。
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(14)
        cl.addLayout(stats)
        cl.addWidget(self.task_card)
        cl.addWidget(self.roles_card)
        cl.addStretch(1)
        self._skeleton = self._build_skeleton()
        self.stack = QStackedWidget()
        self.stack.addWidget(content)          # index 0：真实数据
        self.stack.addWidget(self._skeleton)   # index 1：骨架屏
        lay.addWidget(self.stack, 1)

        self.empty_hint = muted("还没有账号。到「账号」页点击「登录账号」即可添加。")
        self.empty_hint.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.empty_hint)
        self.empty_hint.hide()

        # 骨架屏的呼吸动画：让灰条明暗交替，明确传达「在加载」
        self._skel_phase = 0
        self._skel_timer = QTimer(self)
        self._skel_timer.setInterval(600)
        self._skel_timer.timeout.connect(self._pulse_skeleton)

    def _build_skeleton(self) -> QWidget:
        """与真实内容同构的灰色占位：4 张统计卡 + 任务条 + 角色条。"""
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(14)
        self._skel_bars: list[QFrame] = []

        def bar(parent_box, h: int, w: int | None = None) -> None:
            f = QFrame()
            f.setFixedHeight(h)
            if w:
                f.setFixedWidth(w)
            f.setStyleSheet("background:#EDF0F5;border:none;border-radius:5px;")
            self._skel_bars.append(f)
            parent_box.addWidget(f)

        stats = QHBoxLayout()
        stats.setSpacing(12)
        for _ in range(4):
            card = QFrame()
            card.setObjectName("StatCard")
            card.setFixedHeight(94)
            inner = QVBoxLayout(card)
            inner.setContentsMargins(16, 14, 16, 14)
            inner.setSpacing(8)
            bar(inner, 11, 64)
            bar(inner, 24, 96)
            stats.addWidget(card, 1)
        v.addLayout(stats)

        task_card = Card(padding=18, spacing=14)
        task_card.body().addWidget(title("每日任务"))
        for _ in range(4):
            bar(task_card.body(), 28)
        v.addWidget(task_card)

        roles_card = Card(padding=18, spacing=10)
        roles_card.body().addWidget(title("绑定角色"))
        bar(roles_card.body(), 18, 330)
        roles_card.body().addStretch(1)
        v.addWidget(roles_card)
        v.addStretch(1)
        page.hide()
        return page

    def _pulse_skeleton(self) -> None:
        self._skel_phase = 1 - self._skel_phase
        color = "#E4E8F0" if self._skel_phase else "#F0F2F7"
        style = f"background:{color};border:none;border-radius:5px;"
        for b in self._skel_bars:
            b.setStyleSheet(style)

    def set_accounts(self, accounts: list[Credential], current: Credential | None) -> None:
        self.account_box.blockSignals(True)
        self.account_box.clear()
        for a in accounts:
            # 与任务页下拉保持一致：只显示「平台 · 昵称」，UID 太长放不下也没人看
            self.account_box.addItem(f"{a.community_name} · {a.display_name}", a.key)
        if current:
            i = self.account_box.findData(current.key)
            if i >= 0:
                self.account_box.setCurrentIndex(i)
            # 先把标题换成该社区的货币名，避免刷新完成前显示成别的社区
            self.apply_currency(current.currency)
        self.account_box.blockSignals(False)

    def apply_currency(self, cur: str) -> None:
        self.card_coin.set_title(f"当前{cur}")
        self.task_card_title.setText(f"{cur}每日任务")

    def _on_account_change(self, _i: int) -> None:
        key = self.account_box.currentData()
        if key:
            self.win.switch_account(key)

    @property
    def currency(self) -> str:
        return self.win.current.currency if self.win.current else "积分"

    def render_empty(self) -> None:
        self._skel_timer.stop()
        self.stack.setCurrentIndex(0)
        self.empty_hint.show()

    def set_loading(self, loading: bool) -> None:
        """加载中切到骨架屏，收尾切回数据页。"""
        if loading:
            self.empty_hint.hide()
            self.stack.setCurrentWidget(self._skeleton)
            self._skel_timer.start()
        else:
            self._skel_timer.stop()
            self.stack.setCurrentIndex(0)

    def render(self, snap) -> None:
        from core.communities import get as community_of
        self.set_loading(False)
        self.empty_hint.hide()
        coin = snap.coin
        cur = self.currency
        self.apply_currency(cur)
        meta = community_of(self.win.current.community) if self.win.current else community_of(None)
        self.roles_card.setVisible(meta.has_roles)
        self.card_coin.set_value(str(coin.total), f"{meta.currency}余额")
        cap = int(getattr(coin, "cap", 0) or 0)
        self.card_today.set_value(
            f"+{coin.today}", f"今日入账 · 上限 {cap}" if cap else "今日入账")
        self.card_can.set_value(str(coin.can_get), "已完成未领取" if not self.auto_award
                                else "今日还可获得")
        all_tasks = snap.daily + snap.more
        finished = sum(1 for m in all_tasks if m.done)
        self.card_task.set_value(f"{finished}/{len(all_tasks)}", "每日任务进度")

        # 任务行复用：不够补、多了藏，不销毁重建
        while len(self._rows) < len(all_tasks):
            w = TaskRowWidget()
            self._rows.append(w)
            self.task_list_box.addWidget(w)
        for i, m in enumerate(all_tasks):
            w = self._rows[i]
            w.set_data(m, cur, self.auto_award)
            w.show()
        for w in self._rows[len(all_tasks):]:
            w.hide()

        need = max(1, len(snap.roles))
        while len(self._roles) < need:
            lb = muted("")
            self._roles.append(lb)
            self.roles_box.addWidget(lb)
        if snap.roles:
            for i, r in enumerate(snap.roles):
                detail = (getattr(r, "detail", "")
                          or f"{getattr(r, 'region', '')} · {r.game_uid}")
                self._roles[i].setText(
                    f"{r.game_name} · {r.nickname} · Lv.{r.level} · {detail}")
                self._roles[i].show()
            for lb in self._roles[len(snap.roles):]:
                lb.hide()
        else:
            self._roles[0].setText("未读取到角色（游戏签到需要用角色信息）")
            self._roles[0].show()
            for lb in self._roles[1:]:
                lb.hide()

    @property
    def auto_award(self) -> bool:
        """该平台任务完成是否即时到账（注册表 auto_award）。"""
        from core.communities import get as community_of
        return bool(self.win.current and community_of(self.win.current.community).auto_award)


class AccountsPage(QWidget):
    def __init__(self, win: MainWindow):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(14)

        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(page_header("账号", "凭证只保存在本机，可登录多个账号、随时切换"))
        head.addStretch(1)
        b_del = QPushButton("删除")
        b_del.setObjectName("Danger")
        b_del.clicked.connect(self.remove)
        head.addWidget(b_del)
        b_login = QPushButton("登录账号")
        b_login.setObjectName("Primary")
        b_login.setCursor(Qt.PointingHandCursor)
        b_login.clicked.connect(self.login_action)
        head.addWidget(b_login)
        lay.addLayout(head)

        table_card = Card(padding=0, spacing=0)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["平台", "昵称", "UID", "余额", "最近更新", "状态"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.horizontalHeader().setHighlightSections(False)
        self.table.cellDoubleClicked.connect(self._on_row_double)
        table_card.body().addWidget(self.table)
        lay.addWidget(table_card, 1)

        lay.addWidget(hint(
            "点「登录账号」选平台，可「自动获取」或「手动添加」：\n"
            "· 米游社 / 库街区：自动从安卓模拟器读取登录凭证\n"
            "· Trae / Qoder / WorkBuddy：自动读取本机已登录的桌面客户端（无需手动粘贴）\n"
            "同一平台可登录多个账号，在「总览」页右上角下拉切换；双击本表任意一行也可切换。"))

    def reload(self, accounts: list[Credential]) -> None:
        from core.communities import get as community_of
        from PySide6.QtGui import QColor
        self.table.setRowCount(len(accounts))
        cur_key = self.win.current.key if self.win.current else ""
        for i, a in enumerate(accounts):
            coin = self.win.storage.latest_coin(a.key)
            ok = bool(a.token) if community_of(a.community).auth == "token" else bool(a.stoken)
            nick = a.display_name
            if a.key == cur_key:
                nick = "● " + nick        # 标记当前账号
            values = [
                a.community_name, nick, a.uid,
                f"{coin['total']} {a.currency}" if coin else "-",
                datetime.fromtimestamp(coin["created_at"]).strftime("%m-%d %H:%M") if coin else "-",
                "已授权" if ok else "凭证缺失",
            ]
            for j, v in enumerate(values):
                item = QTableWidgetItem(v)
                if j == 0:
                    item.setData(Qt.UserRole, (a.aid, a.community))   # 删除 / 切换用
                if j == 5:
                    item.setForeground(QColor(GREEN if ok else RED))
                self.table.setItem(i, j, item)

    def login_action(self) -> None:
        """打开「登录账号」对话框，统一处理自动获取 / 手动添加 / 多账号。"""
        from app.ui.login_dialog import LoginDialog
        dlg = LoginDialog(self, self.win.storage)
        dlg.saved.connect(self._on_account_saved)
        dlg.exec()

    def _on_account_saved(self, cred) -> None:
        """对话框保存成功后：切到该账号并刷新。"""
        self.win.current = cred
        self.win._load_accounts()
        self.win.refresh_data()

    def _on_row_double(self, row: int) -> None:
        """双击任意一行：切换为当前账号。"""
        item = self.table.item(row, 0)
        if not item:
            return
        ref = item.data(Qt.UserRole)
        if not isinstance(ref, (tuple, list)) or len(ref) < 2:
            return
        aid, community = ref[0], ref[1]
        acc = self.win.storage.get_account_by_aid(aid)
        if acc:
            self.win.switch_account(acc.key)
            self.win.statusBar().showMessage(
                f"已切换到 {acc.community_name} · {acc.display_name}")

    def remove(self) -> None:
        r = self.table.currentRow()
        if r < 0:
            return
        item = self.table.item(r, 0)
        ref = item.data(Qt.UserRole) if item else None
        if not isinstance(ref, (tuple, list)) or len(ref) < 2:
            return
        aid, community = ref[0], ref[1]
        nick_item = self.table.item(r, 1)
        label = (f"{item.text()} · {nick_item.text()}"
                 if item and nick_item else (item.text() if item else community))
        if QMessageBox.question(self, "确认",
                                f"删除 {label} 账号？") == QMessageBox.Yes:
            self.win.storage.delete_account(aid, community)
            # 删的是当前账号就清空，否则保留当前
            if self.win.current and self.win.current.aid == aid:
                self.win.current = None
            self.win._load_accounts()


class TasksPage(QWidget):
    ALL = "__all__"          # 下拉里的「全部平台」

    def __init__(self, win: MainWindow):
        super().__init__()
        self.win = win
        self.community = "mihoyo"
        self.accounts: list[Credential] = []
        self._filling = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(14)

        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(page_header("任务", "选择账号与任务，点右侧开始执行"))
        head.addStretch(1)
        head.addWidget(field_label("平台账号"))
        self.cb_account = QComboBox()
        # 固定宽度：与总览页一致，账号名长短不一时宽度不能跟着跳
        self.cb_account.setFixedWidth(250)
        self.cb_account.currentIndexChanged.connect(self._on_pick)
        head.addWidget(self.cb_account)
        self.lb_who = muted("")
        head.addWidget(self.lb_who)
        head.addSpacing(6)
        self.btn_run = QPushButton("开始执行")
        self.btn_run.setObjectName("Primary")
        self.btn_run.setCursor(Qt.PointingHandCursor)
        self.btn_run.clicked.connect(self.start)
        head.addWidget(self.btn_run)
        self.btn_stop = QPushButton("停止")
        self.btn_stop.clicked.connect(self.win.stop_tasks)
        self.btn_stop.hide()
        head.addWidget(self.btn_stop)
        lay.addLayout(head)

        card = Card(padding=18, spacing=10)
        card.body().addWidget(title("选择要执行的任务"))

        # ---- 各平台任务勾选面板：由注册表 tasks 驱动，新增平台零改动 ----
        from core.communities import ALL as COMMUNITIES
        self._task_cbs: dict[str, list[tuple[str, QCheckBox]]] = {}
        self._boxes: dict[str, QWidget] = {}
        self._board_boxes: dict[str, QComboBox] = {}
        for meta in COMMUNITIES:
            if not meta.tasks:
                continue
            box = QWidget()
            v = QVBoxLayout(box)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(9)
            cbs: list[tuple[str, QCheckBox]] = []
            for t in meta.tasks:
                cb = QCheckBox(t.label)
                cb.setChecked(True)
                v.addWidget(cb)
                cbs.append((t.key, cb))
            if meta.boards:                      # 有分板块的社区加一个板块下拉
                combo = QComboBox()
                combo.addItem("全部板块", "")
                for gid, name in meta.boards:
                    combo.addItem(name, gid)
                r1 = QHBoxLayout()
                r1.setSpacing(8)
                r1.addWidget(field_label("签到 / 互动板块"))
                r1.addWidget(combo)
                r1.addStretch(1)
                v.addLayout(r1)
                self._board_boxes[meta.key] = combo
            if meta.task_hint:
                v.addWidget(hint(meta.task_hint))
            card.body().addWidget(box)
            box.hide()
            self._boxes[meta.key] = box
            self._task_cbs[meta.key] = cbs

        # ---- 全部平台 ----
        self.box_all = QWidget()
        al = QVBoxLayout(self.box_all)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(9)
        al.addWidget(hint("将按下面的顺序依次执行每个账号，每个平台使用该平台自己的任务勾选。"))
        self.all_list = QVBoxLayout()
        self.all_list.setSpacing(6)
        al.addLayout(self.all_list)
        al.addWidget(hint("某个账号凭证失效时只会跳过它，不影响其它平台继续执行。"))
        card.body().addWidget(self.box_all)
        self.box_all.hide()

        lay.addWidget(card)

        # ---- 执行日志 ----
        log_card = Card(padding=0, spacing=0)
        log_head = QWidget()
        lh = QHBoxLayout(log_head)
        lh.setContentsMargins(18, 14, 18, 0)
        lh.setSpacing(8)
        lh.addWidget(title("执行日志"))
        lh.addStretch(1)
        self.lb_progress = muted("")
        lh.addWidget(self.lb_progress)
        log_card.body().addWidget(log_head)

        prog_wrap = QWidget()
        pw = QHBoxLayout(prog_wrap)
        pw.setContentsMargins(18, 10, 18, 4)
        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        pw.addWidget(self.progress)
        log_card.body().addWidget(prog_wrap)

        self.log_box = QTextEdit()
        self.log_box.setObjectName("Log")
        self.log_box.setReadOnly(True)
        self.log_box.setPlaceholderText("执行时这里会实时打印每一步的结果。")
        # 长时间挂着跑，日志会一直涨，超过上限自动丢最老的
        self.log_box.document().setMaximumBlockCount(2000)
        log_card.body().addWidget(self.log_box, 1)
        lay.addWidget(log_card, 1)

        self.prog_wrap = prog_wrap
        self.prog_wrap.hide()

        # 日志批量刷新：攒一波再插进文本框，避免每行都重排一次
        self._log_buf: list[str] = []
        self._log_timer = QTimer(self)
        self._log_timer.setSingleShot(True)
        self._log_timer.setInterval(90)
        self._log_timer.timeout.connect(self._flush_log)

        for cb in self.findChildren(QCheckBox):
            cb.toggled.connect(lambda _c: self._update_picked_label())

        self._restore_checks()

    # ---------- 勾选状态记忆 ----------
    def _check_map(self, community: str) -> list[tuple[str, QCheckBox]]:
        return self._task_cbs.get(community, [])

    def _restore_checks(self) -> None:
        from core.settings import settings
        saved = settings().data.get("tasks")
        if not isinstance(saved, dict):
            return
        for community, cbs in self._task_cbs.items():
            picked = saved.get(community)
            if not isinstance(picked, list):
                continue
            for key, cb in cbs:
                cb.setChecked(key in picked)

    def _save_checks(self) -> None:
        from core.communities import get as community_of
        from core.settings import settings
        s = settings()
        tasks = s.data.get("tasks")
        if not isinstance(tasks, dict):
            tasks = {}
        community = (self.community if self.community in self._task_cbs
                     else community_of(self.community).key)
        if community in self._task_cbs:
            tasks[community] = [k for k, cb in self._task_cbs[community] if cb.isChecked()]
        s.data["tasks"] = tasks
        try:
            s.save()
        except OSError:
            pass

    # ---------- 按当前账号切换面板 ----------
    def set_accounts(self, accounts: list[Credential], current: Credential | None) -> None:
        """账号列表变化时同步下拉；「全部平台」固定排在最上面第一个。"""
        self.accounts = list(accounts)
        keep = self.cb_account.currentData() if self.cb_account.count() else None
        self._filling = True
        self.cb_account.clear()
        if len(accounts) > 1:
            self.cb_account.addItem("全部平台（依次执行）", self.ALL)
        for a in accounts:
            self.cb_account.addItem(f"{a.community_name} · {a.display_name}", a.key)
        target = keep if keep and self.cb_account.findData(keep) >= 0 else (
            current.key if current else self.ALL)
        idx = self.cb_account.findData(target) if target else -1
        self.cb_account.setCurrentIndex(idx if idx >= 0 else 0)
        self._filling = False
        if current:
            self.community = (current.community or "mihoyo")
        self._apply_view(current)

    def set_account(self, cred) -> None:
        if cred:
            self.community = (cred.community or "mihoyo")
        self._apply_view(cred)

    def _all_mode(self) -> bool:
        return self.cb_account.currentData() == self.ALL

    def _apply_view(self, cred=None) -> None:
        all_mode = self._all_mode()
        self.box_all.setVisible(all_mode)
        for key, box in self._boxes.items():
            box.setVisible(not all_mode and self.community == key)
        if all_mode:
            self._render_all()
        self._update_picked_label()

    def _update_picked_label(self) -> None:
        """右上角提示：当前一共勾了几项要执行的任务。"""
        if self._all_mode():
            self.lb_who.setText(f"共 {len(self.accounts)} 个账号")
        else:
            self.lb_who.setText(f"已勾选 {len(self._picked(self.community))} 项")

    def _render_all(self) -> None:
        from core.communities import get as community_of
        while self.all_list.count():
            it = self.all_list.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for i, a in enumerate(self.accounts, 1):
            picked = set(self._picked(a.community))
            names = [t.short or t.label for t in community_of(a.community).tasks
                     if t.key in picked]
            self.all_list.addWidget(muted(
                f"{i}. {a.community_name} · {a.display_name} — "
                + ("、".join(names) if names else "未勾选任何任务")))

    def _on_pick(self, _i: int) -> None:
        if self._filling:
            return
        key = self.cb_account.currentData()
        if key == self.ALL:
            self._apply_view()
            return
        self.win.switch_account(key)

    def _picked(self, community: str) -> list[str]:
        return [k for k, cb in self._check_map(community) if cb.isChecked()]

    def _options_for(self, community: str) -> dict:
        from core.communities import get as community_of
        meta = community_of(community)
        options: dict = {"community": community}
        for key, cb in self._task_cbs.get(community, []):
            options[key] = cb.isChecked()
        if meta.boards and community in self._board_boxes:
            gid = self._board_boxes[community].currentData() or ""
            # 板块选「全部」时用注册表里的默认顺序（稳定的板块排前面）
            options["gids"] = [gid] if gid else list(meta.default_gids)
        return options

    def start(self) -> None:
        self._save_checks()
        if self._all_mode():
            jobs = [(a, self._options_for(a.community)) for a in self.accounts]
            self.win.run_all_tasks(jobs)
            return
        self.win.run_tasks(self._options_for(self.community))

    def clear_log(self) -> None:
        self._log_buf.clear()
        self._log_timer.stop()
        self.log_box.clear()
        self.progress.setValue(0)
        self.lb_progress.setText("")

    def append_log(self, level: str, msg: str) -> None:
        # 配色与「明细」页（runs_model）一致：成功绿 / 失败红 / 跳过灰 / 积分金。
        # 正文与时间戳都比常规 muted 再深一档——日志区字小、还是等宽字体，
        # 之前 #4C5464 / #8A93A6 在浅底上整体发灰，用户反馈看不清。
        color = {
            "success": "#0B8A43",
            "error": "#C62830",
            "skip": "#6E7686",
            "info": "#242B38",
        }.get(level, "#242B38")
        ts = datetime.now().strftime("%H:%M:%S")
        # 接口返回的错误里常带 < > &，不转义会被当成富文本吃掉
        safe = html.escape(str(msg))
        # 「+数字 货币」用金色高亮，让积分一眼可见（与明细页点数同色）
        safe = re.sub(r"(\+[\d,]+[ \u4e00-\u9fffA-Za-z]*)",
                     r"<span style='color:#9A6A12;font-weight:600'>\1</span>", safe)
        self._log_buf.append(
            f"<span style='color:#78808F'>[{ts}]</span>&nbsp;&nbsp;"
            f"<span style='color:{color}'>{safe}</span>")
        # 每行都 append 会触发一次富文本重排，跑几十步时界面就发涩；
        # 攒一小批一次性插进去，滚动和点击都跟手
        if len(self._log_buf) >= 40:
            self._flush_log()
        else:
            self._log_timer.start()

    def _flush_log(self) -> None:
        self._log_timer.stop()
        if not self._log_buf:
            return
        lines, self._log_buf = self._log_buf, []
        from PySide6.QtGui import QTextCursor
        cur = self.log_box.textCursor()
        cur.movePosition(QTextCursor.End)
        self.log_box.setTextCursor(cur)
        self.log_box.insertHtml("<br>".join(lines) + "<br>")

    def set_progress(self, done: int, total: int) -> None:
        self.progress.setMaximum(max(total, 1))
        self.progress.setValue(done)
        self.lb_progress.setText(f"{done} / {max(total, 1)}")

    def set_running(self, running: bool) -> None:
        self.btn_run.setVisible(not running)
        self.btn_stop.setVisible(running)
        self.btn_stop.setEnabled(running)
        self.btn_stop.setText("停止" if running else "停止中…")
        self.prog_wrap.setVisible(running)
        if not running:
            self.lb_progress.setText("")
            self._flush_log()        # 收尾把缓冲区里剩下的几行补上


class LogsPage(QWidget):
    """执行明细：筛选 + 分页表格，默认只查「当前账号 + 今天」。"""

    FOLLOW = "__follow__"          # 账号下拉：跟随顶部当前账号
    SPANS = ((1, "今天"), (3, "近 3 天"), (7, "近 7 天"), (30, "近 30 天"), (0, "全部时间"))
    PAGE_SIZE = 20

    def __init__(self, win: MainWindow):
        super().__init__()
        self.win = win
        self._dirty = True
        self._filling = False
        self._page = 1
        self._pages = 1
        self._total = 0

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(page_header("执行明细", "每一步操作的实际到账都会记录在这里"))
        head.addStretch(1)
        b = ghost_button("刷新")
        b.clicked.connect(lambda: self.reload(force=True))
        head.addWidget(b)
        self.btn_export = QPushButton("导出 CSV")
        self.btn_export.clicked.connect(self.export_csv)
        head.addWidget(self.btn_export)
        lay.addLayout(head)

        # ---- 筛选条 ----
        bar = Card(padding=14, spacing=0)
        filters = QHBoxLayout()
        filters.setSpacing(8)
        filters.addWidget(field_label("账号"))
        self.cb_account = QComboBox()
        self.cb_account.setMinimumWidth(190)
        filters.addWidget(self.cb_account)
        filters.addSpacing(4)
        filters.addWidget(field_label("时间"))
        self.cb_span = QComboBox()
        for days, label in self.SPANS:
            self.cb_span.addItem(label, days)
        self.cb_span.setCurrentIndex(0)
        filters.addWidget(self.cb_span)
        filters.addSpacing(4)
        filters.addWidget(field_label("结果"))
        self.cb_status = QComboBox()
        for value, label in (("", "全部"), ("success", "成功"),
                             ("failed", "失败"), ("skipped", "跳过")):
            self.cb_status.addItem(label, value)
        filters.addWidget(self.cb_status)
        filters.addSpacing(4)
        self.e_kw = search_box("搜索目标 / 说明 / 类型", 240)
        filters.addWidget(self.e_kw)
        filters.addStretch(1)
        bar.body().addLayout(filters)
        lay.addWidget(bar)

        # ---- 表格（模型驱动，只渲染可见行）----
        from app.ui.runs_model import RunsTableModel
        self.model = RunsTableModel(self)
        self.view = QTableView()
        self.view.setModel(self.model)
        self.view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.view.setAlternatingRowColors(True)
        self.view.setShowGrid(False)
        self.view.setWordWrap(False)
        self.view.setTextElideMode(Qt.ElideRight)
        self.view.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.view.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.view.verticalHeader().setVisible(False)
        self.view.verticalHeader().setDefaultSectionSize(34)
        hh = self.view.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)      # 不用 ResizeToContents，那是卡顿主因
        hh.setSectionResizeMode(6, QHeaderView.Stretch)
        hh.setHighlightSections(False)
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        for col, w in ((0, 122), (1, 150), (2, 92), (3, 150), (4, 62), (5, 108)):
            self.view.setColumnWidth(col, w)

        table_card = Card(padding=0, spacing=0)
        strip = QWidget()
        sl = QHBoxLayout(strip)
        sl.setContentsMargins(16, 12, 12, 10)
        sl.setSpacing(6)
        self.lb_stat = muted("")
        sl.addWidget(self.lb_stat)
        sl.addStretch(1)
        self.btn_first = pager_button("首页")
        self.btn_prev = pager_button("上一页")
        self.lb_page = muted("第 1 / 1 页")
        self.btn_next = pager_button("下一页")
        self.btn_last = pager_button("末页")
        for b, fn in ((self.btn_first, lambda: self.goto(1)),
                      (self.btn_prev, lambda: self.goto(self._page - 1)),
                      (self.btn_next, lambda: self.goto(self._page + 1)),
                      (self.btn_last, lambda: self.goto(self._pages))):
            b.clicked.connect(fn)
            sl.addWidget(b)
            if b is self.btn_prev:
                sl.addWidget(self.lb_page)
        sl.addSpacing(4)
        sl.addWidget(field_label("跳至"))
        self.sp_jump = QSpinBox()
        self.sp_jump.setRange(1, 1)
        self.sp_jump.setFixedWidth(76)
        self.sp_jump.setSuffix(" 页")
        self.sp_jump.editingFinished.connect(lambda: self.goto(self.sp_jump.value()))
        sl.addWidget(self.sp_jump)
        table_card.body().addWidget(strip)
        table_card.body().addWidget(self.view, 1)
        lay.addWidget(table_card, 1)

        # 关键词输入做防抖，别每敲一个字都查一次
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(320)
        self._debounce.timeout.connect(lambda: self.reload(reset_page=True))

        for w in (self.cb_account, self.cb_span, self.cb_status):
            w.currentIndexChanged.connect(self._on_filter_changed)
        self.e_kw.textChanged.connect(lambda _t: self._debounce.start())
        self._sync_pager()

    # ---------- 筛选 ----------
    def refresh_accounts(self, accounts, current) -> None:
        """主窗口账号列表变化时同步下拉，保持用户已选的那一项。"""
        keep = self.cb_account.currentData() if self.cb_account.count() else self.FOLLOW
        self._filling = True
        self.cb_account.clear()
        self.cb_account.addItem("当前账号", self.FOLLOW)
        self.cb_account.addItem("全部账号", "")
        for a in accounts:
            self.cb_account.addItem(f"{a.community_name} · {a.display_name}", a.key)
        idx = self.cb_account.findData(keep)
        self.cb_account.setCurrentIndex(idx if idx >= 0 else 0)
        self._filling = False
        # 表格里也显示昵称，比一串 UID 好认
        self.model.set_names({a.key: f"{a.community_name} · {a.display_name}"
                              for a in accounts})
        self.invalidate()

    def _on_filter_changed(self, _i: int) -> None:
        if not self._filling:
            self.reload(force=True, reset_page=True)

    def invalidate(self) -> None:
        """数据变了，下次进页面再重查，避免在别的页面上白跑查询。"""
        self._dirty = True
        if self.isVisible():
            self.reload(force=True)

    def ensure_loaded(self) -> None:
        if self._dirty:
            self.reload()

    def goto(self, page: int) -> None:
        page = max(1, min(int(page), self._pages))
        if page == self._page:
            return
        self._page = page
        self.reload(force=True)

    # ---------- 查询 ----------
    def _params(self):
        from core.timeutil import days_before
        key = self.cb_account.currentData()
        if key == self.FOLLOW:
            cred = self.win.current
            account = cred.key if cred else None
        else:
            account = key or None
        days = self.cb_span.currentData() or 0
        start = days_before(days) if days else None
        status = self.cb_status.currentData() or ""
        statuses = [status] if status else None
        return account, start, statuses, self.e_kw.text().strip()

    def reload(self, force: bool = False, reset_page: bool = False) -> None:
        import time as _t
        if not force and not self._dirty:
            return
        if reset_page:
            self._page = 1
        account, start, statuses, kw = self._params()
        t0 = _t.perf_counter()
        rows, total, _earned = self.win.storage.query_runs(
            account_uid=account, start_ts=start, statuses=statuses, keyword=kw,
            limit=self.PAGE_SIZE, offset=(self._page - 1) * self.PAGE_SIZE)
        self._total = total
        self._pages = max(1, (total + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        if self._page > self._pages:                 # 记录被清理 / 筛选变窄后回退到最后一页
            self._page = self._pages
            rows, total, _earned = self.win.storage.query_runs(
                account_uid=account, start_ts=start, statuses=statuses, keyword=kw,
                limit=self.PAGE_SIZE, offset=(self._page - 1) * self.PAGE_SIZE)
            self._total = total
        self.model.set_records(rows)
        cost = (_t.perf_counter() - t0) * 1000
        self._dirty = False

        page_earned = sum(int(r.get("points") or 0) for r in rows)
        page_currency = ""
        if rows:
            from app.ui.runs_model import RunsTableModel as _M
            curs = {_M._currency_of(r) for r in rows if int(r.get("points") or 0)}
            page_currency = curs.pop() if len(curs) == 1 else "币"
        parts = [f"共 {self._total} 条（{self.cb_span.currentText()}）"]
        if page_earned:
            parts.append(f"本页获得 +{page_earned} {page_currency}")
        parts.append(f"查询 {cost:.0f} ms")
        self.lb_stat.setText(" · ".join(parts))
        self.btn_export.setEnabled(self._total > 0)
        self._sync_pager()

    def _sync_pager(self) -> None:
        self.lb_page.setText(f"第 {self._page} / {self._pages} 页")
        self.btn_prev.setEnabled(self._page > 1)
        self.btn_first.setEnabled(self._page > 1)
        self.btn_next.setEnabled(self._page < self._pages)
        self.btn_last.setEnabled(self._page < self._pages)
        self.sp_jump.blockSignals(True)
        self.sp_jump.setRange(1, self._pages)
        self.sp_jump.setValue(self._page)
        self.sp_jump.setEnabled(self._pages > 1)
        self.sp_jump.blockSignals(False)

    # ---------- 导出 ----------
    def export_csv(self) -> None:
        import csv
        account, start, statuses, kw = self._params()
        records, total, _ = self.win.storage.query_runs(
            account_uid=account, start_ts=start, statuses=statuses, keyword=kw,
            limit=5000, offset=0)
        if not records:
            QMessageBox.information(self, "没有数据", "当前筛选条件下没有可导出的记录。")
            return
        from app.ui.runs_model import RunsTableModel as _M
        rows = [_M._flatten(r, self.model._names) for r in records]
        default = fr"执行明细_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "导出执行明细", default, "CSV 文件 (*.csv)")
        if not path:
            return
        try:
            # utf-8-sig：Excel 直接打开不乱码
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(["时间", "账号", "类型", "目标", "结果", "获得", "说明"])
                w.writerows(rows)
        except OSError as e:
            QMessageBox.warning(self, "导出失败", str(e))
            return
        tip = f"已导出 {len(rows)} 条记录：\n{path}"
        if total > len(rows):
            tip += f"\n\n（命中 {total} 条，单次导出上限 5000 条，请缩小时间范围后再导）"
        QMessageBox.information(self, "导出完成", tip)


class SettingsPage(QWidget):
    def __init__(self, win: MainWindow):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(14)
        lay.addWidget(page_header("设置", "运行环境与本地数据维护"))

        card = Card(padding=18, spacing=12)
        card.body().addWidget(title("运行环境"))
        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(12)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.e_adb = QLineEdit()
        self.e_adb.setPlaceholderText("留空自动检测（程序自带 adb，一般无需填写）")
        self.e_adb.setMaximumWidth(460)
        form.addRow(field_label("adb 路径"), self.e_adb)
        self.sp_interval = QSpinBox()
        self.sp_interval.setRange(1, 30)
        self.sp_interval.setValue(2)
        self.sp_interval.setSuffix(" 秒")
        self.sp_interval.setFixedWidth(110)
        form.addRow(field_label("请求间隔"), self.sp_interval)
        card.body().addLayout(form)
        card.body().addWidget(hint(
            "请求间隔越大越安全，米游社对高频请求有风控，建议不低于 2 秒。"
            "adb 路径留空即自动查找：优先用程序目录 bin 下自带的 adb，其次系统 PATH，"
            "再其次常见模拟器安装位置。"))
        save_row = QHBoxLayout()
        b = QPushButton("保存设置")
        b.setObjectName("Primary")
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(self._save)
        save_row.addWidget(b)
        save_row.addStretch(1)
        card.body().addLayout(save_row)
        lay.addWidget(card)

        # 回填已保存的设置
        from core.settings import settings as load_settings
        cur = load_settings()
        self.e_adb.setText(cur.adb)
        self.sp_interval.setValue(int(round(cur.interval)))

        # ---- 数据维护 ----
        card2 = Card(padding=18, spacing=12)
        card2.body().addWidget(title("数据维护"))
        self.lb_data = muted("")
        card2.body().addWidget(self.lb_data)
        row2 = QHBoxLayout()
        self.btn_clean = QPushButton("清理 90 天前的执行记录")
        self.btn_clean.clicked.connect(self._clean_runs)
        row2.addWidget(self.btn_clean)
        row2.addStretch(1)
        card2.body().addLayout(row2)
        card2.body().addWidget(hint(
            "只删执行历史，账号和签到状态不受影响。记录攒多了清理一下，"
            "数据库文件会小一些，明细页也更轻快。"))
        lay.addWidget(card2)

        lay.addStretch(1)
        self._refresh_data_info()

    def _refresh_data_info(self) -> None:
        try:
            n = self.win.storage.runs_count()
            size = self.win.storage.db_size() / 1024
        except Exception:                                   # noqa: BLE001
            return
        self.lb_data.setText(f"执行记录 {n} 条 · 数据库占用 {size:.0f} KB")
        self.btn_clean.setEnabled(n > 0)

    def _clean_runs(self) -> None:
        from core.timeutil import days_before
        before = days_before(90)
        if QMessageBox.question(
                self, "清理执行记录",
                "确定删除 90 天前的执行记录吗？\n\n只删历史明细，账号和签到进度不受影响，"
                "但删除后无法恢复。") != QMessageBox.StandardButton.Yes:
            return
        n = self.win.storage.purge_runs(before)
        self._refresh_data_info()
        self.win.page_logs.invalidate()
        QMessageBox.information(self, "清理完成", f"已删除 {n} 条记录。")

    def _save(self) -> None:
        from core.settings import settings as load_settings
        s = load_settings()
        s.adb = self.e_adb.text().strip()
        s.interval = float(self.sp_interval.value())
        if s.adb and not Path(s.adb).exists():
            QMessageBox.warning(self, "路径无效", f"没找到这个文件：\n{s.adb}\n\n请填写 adb.exe 的完整路径。")
            return
        try:
            s.save()
        except OSError as e:
            QMessageBox.warning(self, "保存失败", f"写入设置文件失败：{e}")
            return
        QMessageBox.information(self, "已保存", "设置已保存，下次执行时生效。")
