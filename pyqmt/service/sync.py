import datetime
import logging
import time
from functools import partial
from typing import Callable, List, Optional, Tuple, Union

import cfg4py
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from apscheduler.job import Job
from arrow import Arrow
from coretypes import FrameType, SecurityType
from pyqmt.core.constants import EPOCH

from pyqmt.core.timeframe import tf
from pyqmt.core.xtwrapper import (
    cache_bars,
    get_ashare_list,
    get_calendar,
    get_factor,
    get_security_info,
)
from pyqmt.dal.chores import (
    ashares_sync_status,
    bars_cache_status,
    save_bars_cache_status,
)

Frame = Union[datetime.date, datetime.datetime]

import arrow
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


def schedule_after(after: Job, job_func: Callable, args: Tuple[List[str], FrameType]):
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


def sync_bars_forward(symbols: List[str], frame_type: FrameType):
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
    logger.info("done with %s forward sync: %s~%s", frame_type.value, job_start, now)


def sync_bars_backward(symbols: List[str], frame_type: FrameType):
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

    start = arrow.get(start)
    assert start < arrow.now()

    # convert date to Arrow
    cursor = arrow.get(start)

    if frame_type == FrameType.DAY:
        span = -365
    else:
        cursor = start.floor("hour").replace(hour=15)
        span = -10

    logger.info("start %s backward sync: %s~%s", frame_type.value, epoch, cursor)

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

        cache_bars(symbols, frame_type, batch_start, cursor)
        save_bars_cache_status(batch_start, arrow.get(status["end"]), frame_type)
        cursor = batch_start.shift(days=-1)
        time.sleep(1)

    start = bars_cache_status(frame_type, "start")
    end = bars_cache_status(frame_type, "end")
    logger.info("done with %s backward sync: %s~%s", frame_type.value, start, end)


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
        sync_bars_forward, args=(stocks, FrameType.DAY), name="sync_forward_1d"
    )
    schedule_after(job, sync_bars_backward, args=(stocks, FrameType.DAY))

    job = cfg.sched.add_job(
        sync_bars_forward, args=(stocks, FrameType.MIN1), name="sync_forward_1m"
    )
    schedule_after(job, sync_bars_backward, args=(stocks, FrameType.MIN1))

    # TODO: 再启动定时任务，每天凌晨进行同步

    # 任务2： 每天早上9点，清空get_ashare_list的缓存
    cfg.sched.add_job(get_ashare_list.cache_clear, "cron", hour="9")


def sync_day_bars(dt: datetime.date):
    """保存`dt`日的行情数据"""
    pass


def sync_sector_list(force=False):
    """保存当天的板块列表

    Args:
        force: 如果dt在事务数据库中存在，则只有force为true时，才会重新转存。
    """


def sync_ashare_list(force=False):
    last_trading_day: datetime.date = tf.floor(arrow.now().date(), FrameType.DAY)
    if ashares_sync_status(last_trading_day) and not force:
        return

    data = []
    secs = get_ashare_list()
    for sec in secs:
        items = get_security_info(sec)
        data.append((last_trading_day, sec, *items, SecurityType.STOCK.value))

    cfg.hay_store.save_ashare_list(data)
    cfg.chores_db.save_ashares_sync_status(last_trading_day)


def sync_calendar():
    """交易日历"""
    calendar = get_calendar()
    tf.save_calendar(calendar)

def sync_factor():
    secs = get_ashare_list()
    last_trade_day = tf.floor(arrow.now().date(), FrameType.DAY)

    data = []
    for sec in secs:
        factor = get_factor(sec, EPOCH, last_trade_day)
        factor["sec"] = [sec] * len(factor)
        data.append(factor)

    cfg.hay_store.save_factors(data)
