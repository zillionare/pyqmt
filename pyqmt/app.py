"""Main module."""

import logging
import os
import sqlite3

import arrow
import cfg4py
from apscheduler.schedulers.background import BackgroundScheduler
from blacksheep import Application, get

from pyqmt.config import endpoint, get_config_dir
from pyqmt.handlers import data
from pyqmt.service import tasks

logger = logging.getLogger(__name__)

app = Application()
sched = BackgroundScheduler(timezone="Asia/Shanghai")


@get("/status")
async def status():
    return "OK"


@app.on_start
async def before_start(app: Application) -> None:
    cfg = cfg4py.init(get_config_dir())

    # init sqlite connection
    cfg.sqlite = sqlite3.connect(cfg.sqlite_path, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)  # type: ignore
    cfg.sqlite.row_factory = sqlite3.Row

    sched.add_job(tasks.create_sync_jobs, args=(sched,))

    sched.start()


@app.after_start
async def after_start(app: Application) -> None:
    pass


@app.on_stop
async def on_stop(app: Application) -> None:
    cfg = cfg4py.get_instance()
    cfg.sqlite.close()
