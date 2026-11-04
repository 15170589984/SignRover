"""本地存储：账号、执行记录、米游币快照。"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from core.models import Credential

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    aid         INTEGER PRIMARY KEY AUTOINCREMENT,
    community   TEXT NOT NULL DEFAULT 'mihoyo',
    uid         TEXT NOT NULL DEFAULT '',
    nickname    TEXT DEFAULT '',
    mid         TEXT DEFAULT '',
    stoken      TEXT DEFAULT '',
    token       TEXT DEFAULT '',
    web_cookies TEXT DEFAULT '{}',
    extra       TEXT DEFAULT '{}',
    device_id   TEXT DEFAULT '',
    device_fp   TEXT DEFAULT '',
    device_name TEXT DEFAULT '',
    device_model TEXT DEFAULT '',
    created_at  INTEGER DEFAULT 0,
    updated_at  INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    account_uid TEXT NOT NULL,
    kind        TEXT NOT NULL,
    target      TEXT DEFAULT '',
    status      TEXT NOT NULL,
    message     TEXT DEFAULT '',
    points      INTEGER DEFAULT 0,
    currency    TEXT DEFAULT '',
    created_at  INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_runs_time ON runs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_acc_time ON runs(account_uid, created_at DESC);
CREATE TABLE IF NOT EXISTS coin_snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    account_uid TEXT NOT NULL,
    total       INTEGER DEFAULT 0,
    today       INTEGER DEFAULT 0,
    created_at  INTEGER DEFAULT 0
);
"""

# 旧版（单社区）账号表结构 → 新版多社区结构的迁移。
# 这里直接建带 aid 多账号主键的新表，免得后面再跑一次 aid 升级。
MIGRATE_V1 = """
ALTER TABLE accounts RENAME TO accounts_v1;
CREATE TABLE accounts (
    aid         INTEGER PRIMARY KEY AUTOINCREMENT,
    community   TEXT NOT NULL DEFAULT 'mihoyo',
    uid         TEXT NOT NULL DEFAULT '',
    nickname    TEXT DEFAULT '',
    mid         TEXT DEFAULT '',
    stoken      TEXT DEFAULT '',
    token       TEXT DEFAULT '',
    web_cookies TEXT DEFAULT '{}',
    extra       TEXT DEFAULT '{}',
    device_id   TEXT DEFAULT '',
    device_fp   TEXT DEFAULT '',
    device_name TEXT DEFAULT '',
    device_model TEXT DEFAULT '',
    created_at  INTEGER DEFAULT 0,
    updated_at  INTEGER DEFAULT 0
);
INSERT INTO accounts(community,uid,nickname,mid,stoken,token,web_cookies,extra,device_id,device_fp,
                     device_name,device_model,created_at,updated_at)
    SELECT 'mihoyo',uid,nickname,mid,stoken,'',web_cookies,'{}',device_id,device_fp,
           device_name,device_model,created_at,updated_at
    FROM accounts_v1;
DROP TABLE accounts_v1;
"""


class Storage:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or Path.home() / ".signrover" / "signrover.db")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._con = sqlite3.connect(str(self.path), check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        with self._lock:
            self._migrate()
            self._con.executescript(SCHEMA)
            self._con.commit()

    def _migrate(self) -> None:
        mapping: dict[str, str] = {}     # 旧 key "community:uid" → 新 key "community:aid"
        migrated = False

        # 1) 极老版本（单社区、accounts 没有 community 列）→ 补 community（MIGRATE_V1 已带 aid）
        row = self._con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='accounts'").fetchone()
        if row:
            cols = [r[1] for r in self._con.execute("PRAGMA table_info(accounts)").fetchall()]
            if "community" not in cols:
                self._con.executescript(MIGRATE_V1)
                self._con.commit()
                migrated = True

        # 2) 没有 aid 列 → 升级为多账号结构（aid 自增主键）
        row = self._con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='accounts'").fetchone()
        if row:
            cols = [r[1] for r in self._con.execute("PRAGMA table_info(accounts)").fetchall()]
            if "aid" not in cols:
                self._con.execute("ALTER TABLE accounts RENAME TO accounts_legacy")
                self._con.execute(
                    """CREATE TABLE accounts (
                        aid INTEGER PRIMARY KEY AUTOINCREMENT,
                        community TEXT NOT NULL DEFAULT 'mihoyo',
                        uid TEXT NOT NULL DEFAULT '',
                        nickname TEXT DEFAULT '',
                        mid TEXT DEFAULT '',
                        stoken TEXT DEFAULT '',
                        token TEXT DEFAULT '',
                        web_cookies TEXT DEFAULT '{}',
                        extra TEXT DEFAULT '{}',
                        device_id TEXT DEFAULT '',
                        device_fp TEXT DEFAULT '',
                        device_name TEXT DEFAULT '',
                        device_model TEXT DEFAULT '',
                        created_at INTEGER DEFAULT 0,
                        updated_at INTEGER DEFAULT 0
                    )""")
                self._con.execute(
                    """INSERT INTO accounts(community,uid,nickname,mid,stoken,token,
                           web_cookies,extra,device_id,device_fp,device_name,device_model,
                           created_at,updated_at)
                       SELECT community,uid,nickname,mid,stoken,token,web_cookies,extra,
                              device_id,device_fp,device_name,device_model,created_at,updated_at
                       FROM accounts_legacy""")
                self._con.execute("DROP TABLE accounts_legacy")
                self._con.commit()
                migrated = True

        if migrated:
            def _has(table: str) -> bool:
                return self._con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (table,)).fetchone() is not None

            # 极老版本可能还没有 runs / coin_snapshots 表（SCHEMA 在这之后才建）
            has_runs, has_coin = _has("runs"), _has("coin_snapshots")
            # 账号主键从 uid 换成 aid，所有挂在旧 key 上的历史数据都要跟着搬家，
            # 否则换账号后余额、执行记录会整体"失联"显示为空。
            for r in self._con.execute(
                    "SELECT aid, community, uid FROM accounts").fetchall():
                mapping[f"{r['community']}:{r['uid']}"] = f"{r['community']}:{r['aid']}"
            for old_key, new_key in mapping.items():
                if has_runs:
                    self._con.execute("UPDATE runs SET account_uid=? WHERE account_uid=?",
                                      (new_key, old_key))
                if has_coin:
                    self._con.execute(
                        "UPDATE coin_snapshots SET account_uid=? WHERE account_uid=?",
                        (new_key, old_key))
            # 更早的米游社单社区版本直接存 uid（没有社区前缀），补一轮
            for r in self._con.execute(
                    "SELECT aid, uid FROM accounts WHERE community='mihoyo'").fetchall():
                new_key = f"mihoyo:{r['aid']}"
                if has_runs:
                    self._con.execute(
                        "UPDATE runs SET account_uid=? WHERE account_uid=?"
                        " AND account_uid NOT LIKE '%:%'", (new_key, r["uid"]))
                if has_coin:
                    self._con.execute(
                        "UPDATE coin_snapshots SET account_uid=? "
                        "WHERE account_uid=? AND account_uid NOT LIKE '%:%'",
                        (new_key, r["uid"]))
            self._con.commit()

        # 3) 老库的 runs 没有 currency 列，补上（旧记录留空，展示时按账号所属平台推断）
        r2 = self._con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='runs'").fetchone()
        if r2:
            rcols = [r[1] for r in self._con.execute("PRAGMA table_info(runs)").fetchall()]
            if "currency" not in rcols:
                self._con.execute("ALTER TABLE runs ADD COLUMN currency TEXT DEFAULT ''")
                self._con.commit()

    def close(self) -> None:
        with self._lock:
            self._con.close()

    # ---------- 账号 ----------
    def save_account(self, c: Credential) -> int:
        """保存账号，返回其 aid。

        c.aid 有值且库里存在 → 就地更新（编辑 / 覆盖同一账号）；
        c.aid 为空 → 新插入一行（即使同一平台已有其它账号，也能并存）。
        """
        now = int(time.time())
        web = json.dumps(c.web_cookies, ensure_ascii=False)
        ex = json.dumps(c.extra, ensure_ascii=False)
        with self._lock:
            if c.aid:
                self._con.execute(
                    """UPDATE accounts SET community=?,uid=?,nickname=?,mid=?,stoken=?,token=?,
                           web_cookies=?,extra=?,device_id=?,device_fp=?,device_name=?,
                           device_model=?,updated_at=?
                       WHERE aid=?""",
                    (c.community, c.uid, c.nickname, c.mid, c.stoken, c.token, web, ex,
                     c.device_id, c.device_fp, c.device_name, c.device_model, now, c.aid))
                self._con.commit()
                return c.aid
            self._con.execute(
                """INSERT INTO accounts(community,uid,nickname,mid,stoken,token,web_cookies,extra,
                       device_id,device_fp,device_name,device_model,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (c.community, c.uid, c.nickname, c.mid, c.stoken, c.token, web, ex,
                 c.device_id, c.device_fp, c.device_name, c.device_model, now, now))
            self._con.commit()
            return self._con.execute("SELECT last_insert_rowid()").fetchone()[0]

    def list_accounts(self) -> list[Credential]:
        with self._lock:
            rows = self._con.execute(
                "SELECT * FROM accounts ORDER BY community, created_at").fetchall()
        return [self._cred_from_row(r) for r in rows]

    def get_account(self, community: str, uid: str) -> Credential | None:
        """按 (community, uid) 取一个账号（用于判断「同一账号已存在」）。"""
        with self._lock:
            r = self._con.execute(
                "SELECT * FROM accounts WHERE community=? AND uid=? LIMIT 1",
                (community, uid)).fetchone()
        return self._cred_from_row(r) if r else None

    def get_account_by_aid(self, aid: int) -> Credential | None:
        """按 aid 精确取一个账号（删除 / 切换用）。"""
        with self._lock:
            r = self._con.execute(
                "SELECT * FROM accounts WHERE aid=?", (aid,)).fetchone()
        return self._cred_from_row(r) if r else None

    @staticmethod
    def _cred_from_row(r) -> Credential:
        return Credential(
            aid=int(r["aid"] or 0),
            uid=r["uid"], nickname=r["nickname"], mid=r["mid"], stoken=r["stoken"],
            token=r["token"] or "",
            web_cookies=json.loads(r["web_cookies"] or "{}"),
            extra=json.loads((r["extra"] if "extra" in r.keys() else "{}") or "{}"),
            community=r["community"] or "mihoyo",
            device_id=r["device_id"], device_fp=r["device_fp"],
            device_name=r["device_name"] or "Xiaomi 2201123C",
            device_model=r["device_model"] or "2201123C",
        )

    def delete_account(self, aid: int, community: str | None = None) -> None:
        """按 aid 删除账号（community 仅作二次校验，避免误删）。"""
        with self._lock:
            if community is None:
                self._con.execute("DELETE FROM accounts WHERE aid=?", (aid,))
            else:
                self._con.execute(
                    "DELETE FROM accounts WHERE aid=? AND community=?", (aid, community))
            self._con.commit()

    # ---------- 执行记录 ----------
    def add_run(self, account_uid: str, kind: str, target: str, status: str,
                message: str = "", points: int = 0, currency: str = "") -> int:
        with self._lock:
            cur = self._con.execute(
                "INSERT INTO runs(account_uid,kind,target,status,message,points,currency,created_at)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (account_uid, kind, target, status, message, int(points), currency, int(time.time())),
            )
            self._con.commit()
            return cur.lastrowid

    def set_run_points(self, run_id: int, points: int) -> None:
        """任务跑完才知道这一步实际进了多少币，回填到已插入的记录上。"""
        if not run_id:
            return
        with self._lock:
            self._con.execute("UPDATE runs SET points=? WHERE id=?", (int(points), int(run_id)))
            self._con.commit()

    def list_runs(self, account_uid: str | None = None, limit: int = 200) -> list[dict]:
        q = "SELECT * FROM runs"
        args: tuple = ()
        if account_uid:
            q += " WHERE account_uid=?"
            args = (account_uid,)
        q += " ORDER BY id DESC LIMIT ?"
        with self._lock:
            rows = self._con.execute(q, args + (limit,)).fetchall()
        return [dict(r) for r in rows]

    def query_runs(self, account_uid: str | None = None,
                   start_ts: int | None = None, end_ts: int | None = None,
                   statuses: list[str] | None = None, keyword: str = "",
                   limit: int = 20, offset: int = 0) -> tuple[list[dict], int, int]:
        """按条件查执行记录，返回 (当前页数据, 命中总数, 命中记录的货币合计)。

        全部条件都可空，但界面不应该不传账号/时间——不带条件等于全表扫。
        """
        where: list[str] = []
        args: list = []
        if account_uid:
            where.append("account_uid=?")
            args.append(account_uid)
        if start_ts is not None:
            where.append("created_at>=?")
            args.append(int(start_ts))
        if end_ts is not None:
            where.append("created_at<?")
            args.append(int(end_ts))
        if statuses:
            where.append("status IN (%s)" % ",".join("?" * len(statuses)))
            args.extend(statuses)
        kw = (keyword or "").strip()
        if kw:
            where.append("(target LIKE ? OR message LIKE ? OR kind LIKE ?)")
            like = f"%{kw}%"
            args.extend([like, like, like])

        clause = (" WHERE " + " AND ".join(where)) if where else ""
        sql_args = list(args)
        with self._lock:
            total, earned = self._con.execute(
                "SELECT COUNT(*), COALESCE(SUM(points),0) FROM runs" + clause,
                sql_args).fetchone()
            rows = self._con.execute(
                "SELECT * FROM runs" + clause +
                " ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
                sql_args + [max(1, int(limit)), max(0, int(offset))]).fetchall()
        return [dict(r) for r in rows], int(total), int(earned or 0)

    def runs_today(self, account_uid: str | None = None) -> list[dict]:
        from core.timeutil import day_start
        q = "SELECT * FROM runs WHERE created_at>=?"
        args: tuple = (day_start(),)
        if account_uid:
            q += " AND account_uid=?"
            args += (account_uid,)
        q += " ORDER BY id DESC"
        with self._lock:
            rows = self._con.execute(q, args).fetchall()
        return [dict(r) for r in rows]

    # ---------- 数据维护 ----------
    def runs_count(self) -> int:
        with self._lock:
            return int(self._con.execute("SELECT COUNT(*) FROM runs").fetchone()[0])

    def db_size(self) -> int:
        try:
            return int(self.path.stat().st_size)
        except OSError:
            return 0

    def purge_runs(self, before_ts: int) -> int:
        """删除指定时间点之前的执行记录，返回删除条数。"""
        with self._lock:
            cur = self._con.execute("DELETE FROM runs WHERE created_at<?", (int(before_ts),))
            self._con.commit()
            deleted = cur.rowcount or 0
            if deleted:
                # 删完把空间还回去，不然库文件只涨不缩
                try:
                    self._con.execute("VACUUM")
                except sqlite3.OperationalError:
                    pass
        return int(deleted)

    # ---------- 米游币 ----------
    def add_coin_snapshot(self, account_uid: str, total: int, today: int) -> None:
        with self._lock:
            self._con.execute(
                "INSERT INTO coin_snapshots(account_uid,total,today,created_at) VALUES(?,?,?,?)",
                (account_uid, total, today, int(time.time())),
            )
            self._con.commit()

    def latest_coin(self, account_uid: str) -> dict | None:
        with self._lock:
            row = self._con.execute(
                "SELECT * FROM coin_snapshots WHERE account_uid=? ORDER BY id DESC LIMIT 1",
                (account_uid,),
            ).fetchone()
        return dict(row) if row else None

    def coin_history(self, account_uid: str, limit: int = 60) -> list[dict]:
        with self._lock:
            rows = self._con.execute(
                "SELECT * FROM coin_snapshots WHERE account_uid=? ORDER BY id DESC LIMIT ?",
                (account_uid, limit),
            ).fetchall()
        return [dict(r) for r in rows]
