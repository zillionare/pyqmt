"""Main module."""

import logging
import sqlite3

import cfg4py
from apscheduler.schedulers.background import BackgroundScheduler
from blacksheep import Application, get

from pyqmt.config import get_config_dir
from pyqmt.dal.cache import RedisCache
from pyqmt.dal.ch import ClickHouse
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

    # init chores database connection
    cfg.chores_db = sqlite3.connect(cfg.chores_db_path, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)  # type: ignore
    cfg.chores_db.row_factory = sqlite3.Row

    # init haystore client
    cfg.hay_store = ClickHouse() # type: ignore
    cfg.hay_store.connect()
    sched.add_job(tasks.create_sync_jobs, args=(sched,))

    # redis
    cfg.cache = RedisCache() # type: ignore

    sched.start()


@app.after_start
async def after_start(app: Application) -> None:
    pass


@app.on_stop
async def on_stop(app: Application) -> None:
    cfg = cfg4py.get_instance()
    cfg.chores_db.close()
