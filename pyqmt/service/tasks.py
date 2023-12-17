import datetime
import logging
import os
from functools import partial
from typing import List, Optional, Union

import cfg4py
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from arrow import Arrow
from coretypes import FrameType

from pyqmt.core.journal import bars_cache_status, save_bars_cache_status
from pyqmt.core.xtwrapper import cache_bars

Frame = Union[datetime.date, datetime.datetime]

import arrow
from filelock import FileLock
from xtquant.xtdata import (
    download_history_data2,
    download_sector_data,
    get_stock_list_in_sector,
)

from pyqmt.config import get_config_dir
from pyqmt.core import date2str, handle_xt_error, str2date, str2time, time2str
from pyqmt.core.constants import DATE_FORMAT, TIME_FORMAT

logger = logging.getLogger(__name__)
cfg = cfg4py.get_instance()

def schedule_after(after, job_func, args):
    def listener(after, job_func, args, event):
        if event.job_id != after.id:
            return

        if event.exception:
            logger.warning("任务%s执行失败，任务%s终止启动", after.name, job_func.__name__)
            return

        # 增加任务，立即执行
        cfg.sched.add_job(job_func, args=args)

    my_listener = partial(listener, after, job_func, args)
    cfg.sched.add_listener(my_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)

def do_sync_forward(symbols: List[str], frame_type: FrameType):
    """向未来同步

    epoch --> start --> end |-- >now
    """
    status = bars_cache_status(frame_type)

    now = arrow.now().shift(days=-1)
    end = status["end"]

    span = -365 if frame_type == FrameType.DAY else -10

    if end is None:
        job_start = now.shift(days=span)
    else:
        job_start = end

    # 如果是同步分钟线，强制从0931到1500
    if frame_type == FrameType.MIN1:
        job_start = job_start.floor("minute").replace(hour=9).replace(minute=30)
        now = now.floor("hour").replace(hour=15)

    result = cache_bars(symbols, frame_type, job_start, now)
    if result is not None:
        logger.info("cache_bars returns %s", result)

    start = arrow.get(status["start"] or job_start)
    save_bars_cache_status(start, now, frame_type)
    logger.info("done with %s forward sync: %s~%s", frame_type.value, start, end)


def do_sync_backward(symbols: List[str], frame_type: FrameType):
    """向过去方向同步

    epoch <--| start <--end <-- Now
    """
    status = bars_cache_status(frame_type)

    epoch = arrow.get(status["epoch"])
    start = status["start"]

    if start is None:
        logger.info("wait until first sync finish, before forward sync start")
        return

    if start <= epoch.date():
        logger.info("backward sync already done: %s~%s", start, epoch)
        return

    assert start < arrow.now().date()

    logger.info("start 1d backward sync: %s~%s", epoch, start)

    # convert date to Arrow
    cursor = arrow.get(start)

    if frame_type == FrameType.DAY:
        fmt = DATE_FORMAT
        span = -365
    else:
        cursor = start.floor("hour").replace(hour=15)
        fmt = TIME_FORMAT
        span = -10

    while cursor > epoch:
        batch_start = cursor.shift(days=span)
        if batch_start < epoch:
            batch_start = epoch

        if frame_type == FrameType.MIN1:
            batch_start = batch_start.replace(hour=9).replace(minute=30)

        logger.info(
            "syncing from %s to %s, %s symbols in total",
            batch_start,
            cursor,
            len(symbols),
        )

        download_history_data2(
            symbols, frame_type.value, batch_start.format(fmt), cursor.format(fmt)
        )
        save_bars_cache_status(batch_start, arrow.get(status["end"]), frame_type)
        cursor = start

    start = bars_cache_status(FrameType.DAY, "start")
    end = bars_cache_status(FrameType.DAY, "end")
    logger.info("done with 1d backward sync: %s~%s", start, end)


def create_sync_jobs():
    """从sync.json中读取数据，创建任务"""
    # stocks = get_stock_list_in_sector('沪深A股')
    # TODO: revert this back
    stocks = ["000317.SZ"]
    logger.info(
        "Got %s stocks to sync. !!!Note!!! some of them will not be synced due to time earlier than their IPO date",
        len(stocks),
    )

    # 先启动往未来的同步，这样往过去的同步才会有锚点
    job = cfg.sched.add_job(
        do_sync_forward, args=(stocks, FrameType.DAY), name="sync_forward_1d"
    )
    schedule_after(cfg.sched, job, do_sync_backward, args=(stocks, FrameType.DAY))

    job = cfg.sched.add_job(
        do_sync_forward, args=(stocks, FrameType.MIN1), name="sync_forward_1m"
    )
    schedule_after(cfg.sched, job, do_sync_backward, args=(stocks, FrameType.MIN1))

    # TODO: 再启动定时任务，每天凌晨进行同步


def save_day_bars(dt: datetime.date):
    """保存`dt`日的行情数据"""
