import datetime
import json
import logging
import os
from dataclasses import dataclass
from typing import List, Union

from arrow import Arrow

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
from pyqmt.core.constants import (
    DATE_FORMAT,
    EPOCH,
    EPOCH_KEY,
    SYNC_1D_FROM,
    SYNC_1D_TO,
    SYNCED_1D_END,
    SYNCED_1D_START,
    TIME_FORMAT,
    SYNC_1m_FROM,
    SYNC_1m_TO,
    SYNCED_1m_END,
    SYNCED_1m_START,
)

logger = logging.getLogger(__name__)
status_file = os.path.join(get_config_dir(), "sync.json")
lock = FileLock(status_file + ".lock", timeout=2)


@dataclass
class SyncTaskMeta:
    start: Union[datetime.date, datetime.datetime]
    end: Union[datetime.date, datetime.datetime]
    period: str
    stocks: set
    collected: set


def validate_sync_end(tm: Arrow):
    if tm.hour != 15 or tm.second != 0 or tm.minute != 0:
        raise ValueError(
            f"指定同步结束时间错误，必须以150000结束: {tm.hour:0>2} {tm.minute:0>2} {tm.second:0>2}"
        )


def validate_sync_start(tm: Arrow):
    if tm.hour != 9 or tm.second != 0 or tm.minute != 30:
        raise ValueError(
            f"指定同步开始时间错误，必须以093000开始: {tm.hour:0>2} {tm.minute:0>2} {tm.second:0>2}"
        )


@lock
def load_sync_status():
    global status_file
    try:
        with open(status_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.exception(e)
        return {}


@lock
def save_sync_status_1d(synced_start: Arrow, synced_end: Arrow):
    global status_file

    status = load_sync_status()
    status[SYNCED_1D_START] = synced_start.format("YYYYMMDD")
    status[SYNCED_1D_END] = synced_end.format("YYYYMMDD")

    with open(status_file, "w", encoding="utf-8") as f:
        json.dump(status, f)


@lock
def save_sync_status_1m(synced_start: Arrow, synced_end: Arrow):
    global status_file
    status = load_sync_status()
    status[SYNCED_1m_START] = synced_start.format("YYYYMMDDHHmmss")
    status[SYNCED_1m_END] = synced_end.format("YYYYMMDDHHmmss")

    with open(status_file, "w", encoding="utf-8") as f:
        json.dump(status, f)


def do_sync_1m_forward(stocks):
    status = load_sync_status()
    synced = status.get(SYNCED_1D_END)
    if synced is None:
        logger.info("wait until first sync finish, before forward sync start")
        return

    start = arrow.get(synced, TIME_FORMAT)
    end = arrow.now().shift(days=-1)

    download_history_data2(
        stocks, "1m", start.format(TIME_FORMAT), end.format(TIME_FORMAT)
    )
    logger.info("done with 1m forward sync: %s~%s", start, end)


def do_sync_1d_backward(stocks):
    status = load_sync_status()

    start = status.get(SYNC_1D_FROM)
    end = status.get(SYNCED_1D_START)

    # 如果已经运行过同步任务，则 SYNCED_1D_START 有值，将从此处往过去同步
    # 否则将从SYNC_1D_TO起，向过去同步
    if end is None:
        end = status.get(SYNC_1D_TO)

    if end is None:
        # 如果SYNC_1D_TO也未指定，则从上一个自然日起（确保已收盘）
        end = arrow.now().shift(days=-1)
    else:
        end = arrow.get(end, DATE_FORMAT)

    if start is None:  # 如果未指定开始日，从end同步一年,直到epoch
        start = end.shift(days=-365)
        epoch = status.get(EPOCH_KEY, EPOCH)
        if start < arrow.get(epoch, DATE_FORMAT):
            start = arrow.get(epoch, DATE_FORMAT)
    else:
        start = arrow.get(start, DATE_FORMAT)

    if start >= end:
        logger.info("backward synd already done: %s~%s", start, end)
        return

    logger.info("start 1d backward sync: %s~%s", start, end)

    cur_end = end
    while cur_end > start:
        cur_start = cur_end.shift(days=-250)
        if cur_start < start:
            cur_start = arrow.get(start)

        logger.info(
            "syncing from %s to %s, %s stocks in total", cur_start, cur_end, len(stocks)
        )

        download_history_data2(
            stocks, "1d", cur_start.format(DATE_FORMAT), cur_end.format(DATE_FORMAT)
        )
        save_sync_status_1d(cur_start, end)
        cur_end = cur_start

    logger.info("done with 1d backward sync: %s~%s", start, end)


def do_sync_1d_forward(stocks):
    status = load_sync_status()
    synced = status.get(SYNCED_1m_END)
    if synced is None:
        logger.info("wait until first sync finish, before forward sync start")
        return

    start = arrow.get(synced, DATE_FORMAT)
    end = arrow.now().shift(days=-1).replace(hour=15, minute=0, second=0)

    # 此处时间错误，会导致行情数据不连贯
    validate_sync_start(start)
    validate_sync_end(end)

    download_history_data2(
        stocks, "1m", start.format(TIME_FORMAT), end.format(TIME_FORMAT)
    )
    logger.info("done with 1d forward sync: %s~%s", start, end)


def do_sync_1m_backward(stocks: List[str]):
    status = load_sync_status()

    start = status.get(SYNC_1m_FROM)
    end = status.get(SYNCED_1m_START)

    # 如果已经运行过同步任务，则 SYNCED_1m_START 有值，将从此处往过去同步
    # 否则将从SYNC_1m_TO起，向过去同步
    if end is None:
        end = status.get(SYNC_1m_TO)

    if end is None:
        # 如果SYNC_1m_TO也未指定，则从上一个自然日起（确保已收盘）
        end = arrow.now().shift(days=-1).replace(hour=15, minute=0, second=0)
    else:
        end = arrow.get(end, TIME_FORMAT)

    if start is None:  # 如果未指定开始日，从end同步10天,直到epoch
        start = end.shift(days=-10).replace(hour=9, minute=30, second=0)
        epoch = status.get(EPOCH_KEY, EPOCH)
        if start < arrow.get(epoch, DATE_FORMAT):
            start = arrow.get(epoch, DATE_FORMAT)
    else:
        start = arrow.get(start, TIME_FORMAT)

    # 此处时间错误，会导致行情数据不连贯
    validate_sync_start(start)
    validate_sync_end(end)

    if start >= end:
        logger.info("backward synd already done: %s~%s", start, end)
        return

    logger.info("done with 1m backward sync: %s~%s", start, end)

    cur_end = end
    while cur_end > start:
        cur_start = cur_end.shift(days=-5)
        if cur_start < start:
            cur_start = arrow.get(start)

        logger.info(
            "syncing from %s to %s, %s stocks in total", cur_start, cur_end, len(stocks)
        )

        download_history_data2(
            stocks, "1d", cur_start.format(TIME_FORMAT), cur_end.format(TIME_FORMAT)
        )
        save_sync_status_1m(cur_start, end)
        cur_end = cur_start
    logger.info("done with 1m backward sync: %s~%s", start, end)


def create_sync_jobs(sched):
    """从sync.json中读取数据，创建任务"""
    # stocks = get_stock_list_in_sector('沪深A股')
    # TODO: revert this back
    stocks = ["000317.SZ"]
    logger.info(
        "Got %s stocks to sync. !!!Note!!! some of them will not be synced due to time earlier than their IPO date",
        len(stocks),
    )

    # 先启动往过去的同步，这样往现在的同步才会有锚点
    sched.add_job(do_sync_1d_backward, args=(stocks,))
    sched.add_job(do_sync_1d_forward, args=(stocks,))

    sched.add_job(do_sync_1m_backward, args=(stocks,))
    sched.add_job(do_sync_1m_forward, args=(stocks,))

    # TODO: 再启动定时任务，每天凌晨进行同步
