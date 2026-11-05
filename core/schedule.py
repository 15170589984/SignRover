"""定时执行的纯逻辑（不碰界面，方便单测）。

规则：
- 到点后触发一次；触发过就把日期记进 last_run，同一天不会重复跑。
- 工作日模式只在北京时间周一~周五触发，周末顺延到下一个工作日。
- 程序没开的时候到点当然不会跑：下次启动时若今天还没跑过、且时间已过，
  会补跑一次（last_run 存在配置里，重启也不会重复）。
"""
from __future__ import annotations

from datetime import datetime, timedelta


def _hhmm(sched: dict) -> tuple[int, int]:
    try:
        hh, mm = str(sched.get("time") or "08:00").split(":")[:2]
        return int(hh), int(mm)
    except (ValueError, AttributeError):
        return 8, 0


def target_today(now: datetime, sched: dict) -> datetime | None:
    """今天（或下一个工作日）的计划执行时刻；工作日模式下周末返回 None。"""
    hh, mm = _hhmm(sched)
    if sched.get("days") == "weekday" and now.weekday() >= 5:
        return None
    return now.replace(hour=hh, minute=mm, second=0, microsecond=0)


def should_fire(now: datetime, sched: dict) -> bool:
    """此刻是否该自动执行。"""
    if not sched.get("enabled"):
        return False
    today = now.strftime("%Y-%m-%d")
    if sched.get("last_run") == today:
        return False                       # 今天已经跑过
    if sched.get("suppressed") == today:
        return False                       # 勾选时今天的点已过，被有意跳过
    t = target_today(now, sched)
    return t is not None and now >= t


def next_run(now: datetime, sched: dict) -> datetime | None:
    """下一次计划执行时刻（用于界面提示）。"""
    if not sched.get("enabled"):
        return None
    hh, mm = _hhmm(sched)
    weekday_only = sched.get("days") == "weekday"
    ran_today = sched.get("last_run") == now.strftime("%Y-%m-%d") or \
        sched.get("suppressed") == now.strftime("%Y-%m-%d")
    for day in range(0, 8):
        d = now + timedelta(days=day)
        if weekday_only and d.weekday() >= 5:
            continue
        cand = d.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if cand < now:
            continue
        if day == 0 and ran_today:
            continue                        # 今天这次已经跑掉了
        return cand
    return None


def next_workday(now: datetime) -> datetime:
    d = now
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d
