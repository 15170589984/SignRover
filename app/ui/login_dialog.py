"""「登录账号」对话框：统一入口，按平台选择自动获取 / 手动添加。

设计要点：
- 顶部平台下拉，列出全部 5 个平台。
- 两个模式：
  · 自动获取：米游社 / 库街区 走模拟器抽取；Trae / Qoder / WorkBuddy 自动读取
    本机已登录的桌面客户端（Electron 登录态 / 进程内存 token），无需手动粘贴。
  · 手动添加：粘贴 token / 鉴权串 / Cookie / 整段 cURL，程序自动识别并补全。
- 同一平台支持多个账号：保存时按 (community, uid) 判重——
  · 同 uid 已存在 → 视为同一账号，询问是否覆盖更新凭证；
  · 不同 uid → 新增为「该平台第 N 个账号」，互不影响、可在总览页切换。
"""
from __future__ import annotations

import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QTabWidget, QVBoxLayout)

from app.ui.theme import GREEN, RED, TEXT_MUTED
from app.ui.widgets import field_label, hint, muted, page_header
from app.workers import ExtractWorker, PrepareWorker
from core.communities import ALL, get as community_of
from core.models import Credential
from core.storage import Storage


# 手动添加里每类字段对应的输入框构造器；新平台在注册表加 import_fields 即可，这里不用动。
BUILDERS = {
    "uid": lambda: (QLineEdit(), None),
    "token": lambda: (QLineEdit(), None),
    "stoken": lambda: (QLineEdit(), None),
    "mid": lambda: (QLineEdit(), None),
    "cookie": lambda: (QLineEdit(), dict),     # a=1;b=2 解析成 Credential.web_cookies
}


class LoginDialog(QDialog):
    saved = Signal(object)        # 成功保存的账号（已带 aid）

    def __init__(self, parent, storage: Storage):
        super().__init__(parent)
        self.storage = storage
        self.resolved: Credential | None = None     # 自动获取成功后的凭证
        self._worker = None
        self._busy = False
        self._editors: dict[str, QLineEdit] = {}
        self._parsers: dict[str, object] = {}
        self._order: list[str] = []
        self._e_nick = None

        self.setWindowTitle("登录账号")
        self.setMinimumWidth(640)
        self.setMinimumHeight(420)
        self._build()

    # ---------------- 布局 ----------------
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)
        root.addWidget(page_header("登录账号",
                                  "选择平台后，可自动获取或手动粘贴凭证；同一平台可登录多个账号，在「总览」页切换"))

        # 平台选择
        bar = QHBoxLayout()
        bar.setSpacing(10)
        bar.addWidget(field_label("平台"))
        self.c_platform = QComboBox()
        for c in ALL:
            self.c_platform.addItem(c.name, c.key)
        self.c_platform.setMinimumWidth(220)
        self.c_platform.currentIndexChanged.connect(self._on_platform)
        bar.addWidget(self.c_platform)
        bar.addStretch(1)
        root.addLayout(bar)

        self.tabs = QTabWidget()
        # 两个页签的保存条件是独立的：自动页要求先获取成功，手动页随时可保存。
        # 不接这个信号的话，切到「手动添加」时按钮还停在上一个页签的禁用状态，
        # 用户会以为手动导入坏了（v1.3.1 手动导入「没反应」的另一半原因）。
        self.tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self.tabs, 1)

        # ---- 自动获取 ----
        self.auto_page = QFrame()
        a = QVBoxLayout(self.auto_page)
        a.setContentsMargins(0, 10, 0, 0)
        a.setSpacing(12)
        self.auto_hint = hint("")
        a.addWidget(self.auto_hint)
        self.btn_fetch = QPushButton("立即获取登录凭证")
        self.btn_fetch.setObjectName("Primary")
        self.btn_fetch.setCursor(Qt.PointingHandCursor)
        self.btn_fetch.clicked.connect(self._on_fetch)
        a.addWidget(self.btn_fetch)
        self.auto_status = QLabel("")
        self.auto_status.setObjectName("Hint")
        self.auto_status.setWordWrap(True)
        self.auto_status.setMinimumHeight(54)
        a.addWidget(self.auto_status)
        a.addStretch(1)
        self.tabs.addTab(self.auto_page, "自动获取")

        # ---- 手动添加 ----
        self.manual_page = QFrame()
        m = QVBoxLayout(self.manual_page)
        m.setContentsMargins(0, 10, 0, 0)
        m.setSpacing(6)
        self.manual_form = QFormLayout()
        self.manual_form.setHorizontalSpacing(14)
        self.manual_form.setVerticalSpacing(10)
        m.addLayout(self.manual_form)
        m.addWidget(hint("可粘贴 token / 鉴权串；米游社、库街区也可直接粘贴 Cookie 或整段 cURL，"
                         "程序自动识别并补全昵称、UID。PC 工具的 token 留空时也会自动读取本机登录态。"
                         "Qoder 粘贴 token 时会自动判断是国内版还是国际版。"))
        m.addStretch(1)
        self.tabs.addTab(self.manual_page, "手动添加")

        # ---- 底部 ----
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"background:{self._border()};border:none;")
        root.addWidget(line)

        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        self.lb_tip = muted("")
        bottom.addWidget(self.lb_tip)
        bottom.addStretch(1)
        b_cancel = QPushButton("取消")
        b_cancel.clicked.connect(self.reject)
        self.btn_save = QPushButton("保存账号")
        self.btn_save.setObjectName("Primary")
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.clicked.connect(self._on_save)
        bottom.addWidget(b_cancel)
        bottom.addWidget(self.btn_save)
        root.addLayout(bottom)

        self._on_platform()     # 初始化提示与字段

    @staticmethod
    def _border() -> str:
        from app.ui.theme import BORDER
        return BORDER

    # ---------------- 平台切换 ----------------
    def _on_platform(self) -> None:
        meta = community_of(self.c_platform.currentData())
        if meta.is_device_app:
            self.auto_hint.setText(
                f"将从安卓模拟器自动读取「{meta.name}」的登录凭证。\n"
                "请先在模拟器里登录对应 App，并保持在前台（米游社还需开启 root），然后点「立即获取」。")
        else:
            self.auto_hint.setText(
                f"将自动读取本机已登录的「{meta.name}」桌面客户端，无需手动粘贴。\n"
                "请确保对应客户端已启动并登录；读不到时切换到「手动添加」粘贴 token 即可。")
        self._build_fields()
        self._reset_auto()

    def _reset_auto(self) -> None:
        self.resolved = None
        self.auto_status.setText("")
        self.auto_status.setStyleSheet("color:#98A0AE;")
        self._update_save_state()

    # ---------------- 手动字段 ----------------
    def _build_fields(self) -> None:
        """按当前平台声明的字段逐行重建（整行重建，不显隐，顺序由注册表决定）。"""
        keep = {k: w.text() for k, w in self._editors.items()}
        keep_nick = self._e_nick.text() if self._e_nick else ""
        while self.manual_form.rowCount() > 0:
            self.manual_form.removeRow(0)
        self._editors.clear()
        self._parsers.clear()
        self._order.clear()

        meta = community_of(self.c_platform.currentData())
        for f in meta.import_fields:
            builder = BUILDERS.get(f.key) or (lambda: (QLineEdit(), None))
            w, ptype = builder()
            w.setText(keep.get(f.key, ""))
            w.setPlaceholderText(f.placeholder)
            self._editors[f.key] = w
            self._parsers[f.key] = ptype
            suffix = "必填" if f.required else "可留空"
            self.manual_form.addRow(field_label(f"{f.label}（{suffix}）"), w)
            self._order.append(f.key)

        self._e_nick = QLineEdit()
        self._e_nick.setPlaceholderText("可选，如「Qoder小号」；留空用平台自动取到的昵称（多账号用它区分）")
        self._e_nick.setText(keep_nick)
        self.manual_form.addRow(field_label("备注名"), self._e_nick)

    # ---------------- 自动获取 ----------------
    def _on_fetch(self) -> None:
        if self._busy:
            return
        meta = community_of(self.c_platform.currentData())
        self._reset_auto()
        self._set_busy(True)
        self.auto_status.setText("正在获取，请稍候…")
        self.auto_status.setStyleSheet(f"color:{TEXT_MUTED};")

        if meta.is_device_app:
            w = ExtractWorker(community=meta.key)
            w.step.connect(self._on_extract_step)
            w.ok.connect(self._on_extract_ok)
            w.fail.connect(self._on_auto_fail)
            w.finished.connect(lambda: self._set_busy(False))
            self._worker = w
            w.start()
        else:
            cred = Credential(community=meta.key)
            w = PrepareWorker(meta.key, cred)
            w.step.connect(lambda s: self.auto_status.setText(s))
            w.ok.connect(self._on_prepare_ok)
            w.fail.connect(self._on_auto_fail)
            w.finished.connect(lambda: self._set_busy(False))
            self._worker = w
            w.start()

    def _on_extract_step(self, s: str) -> None:
        self.auto_status.setText(s)

    def _on_extract_ok(self, cred) -> None:
        self.resolved = cred
        self.auto_status.setText(
            f"已获取：{cred.community_name} · {cred.display_name}（UID {cred.uid}）\n"
            "点右下角「保存账号」写入；同一平台可继续添加其它账号。")
        self.auto_status.setStyleSheet(f"color:{GREEN};")
        self._update_save_state()

    def _on_prepare_ok(self, cred) -> None:
        self.resolved = cred
        self.auto_status.setText(
            f"已读取本机登录态：{cred.community_name} · {cred.display_name}（UID {cred.uid}）\n"
            "点右下角「保存账号」写入；同一平台可继续添加其它账号。")
        self.auto_status.setStyleSheet(f"color:{GREEN};")
        self._update_save_state()

    def _on_auto_fail(self, msg: str) -> None:
        self.resolved = None
        self.auto_status.setText("获取失败：" + msg + "\n\n可切到「手动添加」粘贴 token / cURL。")
        self.auto_status.setStyleSheet(f"color:{RED};")
        self._update_save_state()

    # ---------------- 保存 ----------------
    def _on_save(self) -> None:
        if self._busy:
            return
        if self.tabs.currentWidget() is self.auto_page:
            if not self.resolved:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.information(self, "提示", "请先点「立即获取」读取登录凭证，或切到「手动添加」粘贴。")
                return
            self._commit(self.resolved)
            return

        # 手动添加：读字段 → 解析 → prepare_import → 提交
        cred = self._read_manual()
        if cred is None:
            return
        self._set_busy(True)
        self.lb_tip.setText("正在校验凭证…")
        w = PrepareWorker(cred.community, cred)
        w.step.connect(lambda s: self.lb_tip.setText(s))
        w.ok.connect(lambda _c: self._commit(_c))
        w.fail.connect(self._on_manual_fail)
        w.finished.connect(lambda: self._set_busy(False))
        self._worker = w
        w.start()

    def _on_manual_fail(self, msg: str) -> None:
        self.lb_tip.setText("")
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(self, "凭证无效", msg)

    def _read_manual(self) -> Credential | None:
        """从手动字段构造 Credential；必填缺失返回 None（已提示）。"""
        meta = community_of(self.c_platform.currentData())
        spec = {f.key: f for f in meta.import_fields}
        cred = Credential(community=meta.key)
        for key in self._order:
            if key not in spec:
                continue
            text = self._editors[key].text().strip()
            if self._parsers[key] is dict:       # Cookie 串解析成 dict
                cookies: dict[str, str] = {}
                for part in text.split(";"):
                    if "=" in part:
                        k, v = part.split("=", 1)
                        cookies[k.strip()] = v.strip()
                cred.web_cookies = cookies
            elif hasattr(cred, key):
                setattr(cred, key, text)
            else:
                cred.extra[key] = text
        for f in meta.import_fields:              # 通用必填校验
            value = getattr(cred, f.key, "") or cred.extra.get(f.key, "")
            if f.required and not value:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "参数不足", f"{meta.name}的「{f.label}」必填")
                return None
        if self._e_nick.text().strip():          # 备注名优先于平台自动取的昵称
            cred.nickname = self._e_nick.text().strip()
        return cred

    def _commit(self, cred: Credential) -> None:
        """落库：同 UID 只能覆盖；不同 UID 让用户选「新增」还是「替换已有账号」。

        这里是「一个平台多个账号」的关键——以前同平台已有账号时只走覆盖，
        导致第二个账号永远存不进去。
        """
        from PySide6.QtWidgets import QInputDialog, QMessageBox

        self.lb_tip.setText("")
        all_of_platform = [a for a in self.storage.list_accounts()
                           if a.community == cred.community]
        existing = self.storage.get_account(cred.community, cred.uid) if cred.uid else None
        if existing and existing.aid == cred.aid:      # 编辑自己，不算冲突
            existing = None
        same_uid = existing is not None
        if existing is None and cred.token:
            # 同一个 token 就是同一个账号：早期版本可能把 uid 存成了 token 指纹
            # （比如 Qoder 域名认错时），再导入一次要就地修正，不能多出一条废账号
            same = [a for a in all_of_platform
                    if a.aid != cred.aid and (a.token or "").strip() == cred.token.strip()]
            if same:
                existing = same[0]
        others = [a for a in all_of_platform if not existing or a.aid != existing.aid]

        if existing:
            why = "同一 UID" if same_uid else "同一 token"
            r = QMessageBox.question(
                self, "确认覆盖",
                f"{cred.community_name} 里已有这个账号（{why}）：{existing.display_name}\n\n"
                "同一账号不能存两份，是否用这次的凭证覆盖更新它？"
                + ("" if same_uid else "\n（旧记录里的 UID 会一并修正）"),
                QMessageBox.Yes | QMessageBox.No)
            if r != QMessageBox.Yes:
                return
            cred.aid = existing.aid
        elif others:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Question)
            box.setWindowTitle(f"登录 {cred.community_name}")
            names = "、".join(a.display_name for a in others)
            box.setText(
                f"{cred.community_name} 下已有账号：{names}\n\n"
                f"「新增保存」把 {cred.display_name} 作为该平台第 {len(others) + 1} 个账号，"
                "两个账号都能用；\n「替换已有」会删掉一个旧账号换成这次登录的。")
            b_new = box.addButton("新增保存", QMessageBox.AcceptRole)
            b_rep = box.addButton("替换已有账号", QMessageBox.DestructiveRole)
            b_cancel = box.addButton("取消", QMessageBox.RejectRole)
            box.setDefaultButton(b_new)
            box.exec()
            clicked = box.clickedButton()
            if clicked is b_cancel or clicked is None:
                return
            if clicked is b_rep:
                labels = [f"{a.display_name}（{a.uid}）" for a in others]
                pick, ok = QInputDialog.getItem(
                    self, "替换哪个账号", "要替换掉哪个账号？", labels, 0, False)
                if not ok:
                    return
                self.storage.delete_account(others[labels.index(pick)].aid, cred.community)
            else:
                cred.aid = 0        # 明确新增一行，不复用任何已有 aid

        before = len(all_of_platform)
        aid = self.storage.save_account(cred)
        cred.aid = aid

        if existing:
            tail = "已覆盖更新原有凭证"
        else:
            tail = f"这是「{cred.community_name}」的第 {before + 1} 个账号，可在总览页切换"
        QMessageBox.information(
            self, "已保存",
            f"{cred.community_name} 账号已保存：{cred.display_name}\n{tail}")
        self.saved.emit(cred)
        self.accept()

    # ---------------- 状态 ----------------
    def _on_tab_changed(self, _index: int) -> None:
        """切换页签后重算保存按钮，否则手动页会继承自动页的禁用状态。

        构造过程中 addTab 也会触发一次，此时底部控件还没建好，要跳过。
        """
        if getattr(self, "btn_save", None) is None:
            return
        self.lb_tip.setText("")
        self._update_save_state()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.btn_fetch.setEnabled(not busy)
        self.c_platform.setEnabled(not busy)
        if busy:
            self.btn_save.setEnabled(False)
        else:
            # 重新计算：自动模式要看是否已拿到凭证，手动模式直接可保存
            self._update_save_state()

    def _update_save_state(self) -> None:
        # 自动获取模式：必须已成功获取才能保存
        if self.tabs.currentWidget() is self.auto_page:
            self.btn_save.setEnabled(bool(self.resolved) and not self._busy)
            self.lb_tip.setText("自动获取成功后可保存" if self.resolved else "")
        else:
            self.btn_save.setEnabled(not self._busy)
            self.lb_tip.setText("")

    def closeEvent(self, event) -> None:        # noqa: N802
        if self._worker and self._worker.isRunning():
            self._worker.requestInterruption()
        super().closeEvent(event)
