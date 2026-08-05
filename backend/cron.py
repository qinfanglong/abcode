"""ABcode 定时任务 - 基于 SQLite 的简单定时调度"""
import json
import threading
import time
import datetime
from pathlib import Path

from db import DB_PATH, get_conn

# 任务状态常量
STATUS = {"idle": "等待", "running": "运行中", "error": "错误"}


def init_cron():
    conn = get_conn()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS cron_jobs (
        id TEXT PRIMARY KEY,
        name TEXT,
        prompt TEXT,
        interval_min INTEGER DEFAULT 0,   -- 0=不使用固定间隔
        schedule_at TEXT DEFAULT '',       -- 'HH:MM' 每日定时
        provider_id TEXT DEFAULT '',
        model TEXT DEFAULT '',
        conv_id TEXT DEFAULT '',           -- 结果写入的会话，空=新建
        enabled INTEGER DEFAULT 1,
        last_run REAL DEFAULT 0,
        last_result TEXT DEFAULT '',
        created_at REAL
    )""")
    conn.commit()
    conn.close()


def _new_id(prefix):
    return f"{prefix}{int(time.time()*1000)}"


def create_job(data):
    jid = _new_id("j")
    conn = get_conn()
    conn.execute("""INSERT INTO cron_jobs
        (id,name,prompt,interval_min,schedule_at,provider_id,model,conv_id,enabled,created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (jid, data.get("name", "定时任务"), data.get("prompt", ""),
         int(data.get("interval_min", 0)), data.get("schedule_at", ""),
         data.get("provider_id", ""), data.get("model", ""), data.get("conv_id", ""),
         1 if data.get("enabled", True) else 0, time.time()))
    conn.commit()
    conn.close()
    return jid


def list_jobs():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM cron_jobs ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_job(jid, **kw):
    kw = {k: v for k, v in kw.items() if v is not None}
    if not kw:
        return
    conn = get_conn()
    sets = ",".join(f"{k}=?" for k in kw)
    conn.execute(f"UPDATE cron_jobs SET {sets} WHERE id=?", (*kw.values(), jid))
    conn.commit()
    conn.close()


def delete_job(jid):
    conn = get_conn()
    conn.execute("DELETE FROM cron_jobs WHERE id=?", (jid,))
    conn.commit()
    conn.close()


def _job_due(job):
    """判断任务是否到期"""
    now = time.time()
    if not job["enabled"]:
        return False
    # 固定间隔
    if job["interval_min"] > 0:
        return (now - job["last_run"]) >= job["interval_min"] * 60
    # 每日定时 HH:MM
    if job["schedule_at"]:
        t = datetime.datetime.now().strftime("%H:%M")
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        key = f"{today_str} {job['schedule_at']}"
        ts = time.mktime(time.strptime(key, "%Y-%m-%d %H:%M"))
        if job["last_run"] < ts <= now:
            return True
    return False


class CronScheduler(threading.Thread):
    """后台调度线程"""

    def __init__(self, run_callback):
        super().__init__(daemon=True)
        self.run_callback = run_callback
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        while not self._stop.is_set():
            try:
                conn = get_conn()
                jobs = conn.execute("SELECT * FROM cron_jobs").fetchall()
                conn.close()
                for job in jobs:
                    job = dict(job)
                    if _job_due(job):
                        # 标记运行中
                        update_job(job["id"], last_run=time.time())
                        try:
                            result = self.run_callback(job)
                            update_job(job["id"], last_result=str(result)[:2000])
                        except Exception as e:
                            update_job(job["id"], last_result=f"错误: {e}")
            except Exception:
                pass
            time.sleep(20)


def start_scheduler(run_callback):
    sched = CronScheduler(run_callback)
    sched.start()
    return sched
