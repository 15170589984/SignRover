"""定时执行的纯逻辑（不碰界面，方便单测）。

去重模型：按「时刻槽」而不是按「天」。
- last_run 记录的是最近一次触发对应的完整时刻「YYYY-MM-DD HH:MM」；
- 同一个时刻只触发一次（20 秒巡检不会重复跑）；
- 用户把时间从 14:55 改成 15:40，15:40 就是新槽，到点必跑
  （这正是「设置几点就几点执行」的预期）；
- 启用/改配置时如果设置的时刻已过且该槽没跑过 → 立即补跑
  （对齐 Windows 任务计划 StartWhenAvailable / systemd Persistent）；
- 工作日模式只在北京时间周一~周五触发，周末顺延到下一个工作日；
- 程序没开的时候到点当然不会跑：下次启动时该槽没跑过且已过点，会补跑。
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


def slot_of(t: datetime) -> str:
    """时刻槽的存储格式：YYYY-MM-DD HH:MM。"""
    return t.strftime("%Y-%m-%d %H:%M")


def should_fire(now: datetime, sched: dict) -> bool:
    """此刻是否该自动执行：到点 && 这个时刻槽没跑过。"""
    if not sched.get("enabled"):
        return False
    t = target_today(now, sched)
    if t is None or now < t:
        return False
    return sched.get("last_run") != slot_of(t)


def next_run(now: datetime, sched: dict) -> datetime | None:
    """下一次计划执行时刻（用于界面提示）。"""
    if not sched.get("enabled"):
        return None
    hh, mm = _hhmm(sched)
    weekday_only = sched.get("days") == "weekday"
    for day in range(0, 8):
        d = now + timedelta(days=day)
        if weekday_only and d.weekday() >= 5:
            continue
        cand = d.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if cand < now:
            continue
        if day == 0 and sched.get("last_run") == slot_of(cand):
            continue                        # 今天这个槽已经跑掉了
        return cand
    return None


def next_workday(now: datetime) -> datetime:
    d = now
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d
