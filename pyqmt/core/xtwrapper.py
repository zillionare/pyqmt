import datetime
from functools import cache
from typing import List, Optional, Union

import numpy as np
from arrow import Arrow
from coretypes import Frame, FrameType
from xtquant import xtdata as xt

from pyqmt.core.constants import DATE_FORMAT, TIME_FORMAT, min_level_frames
from pyqmt.core.errors import XtQuantError


def cache_bars(
    symbols: Union[str, List[str]],
    frame_type: FrameType,
    start_time: Arrow,
    end_time: Arrow,
) -> bool:
    """让xtdata缓存行情数据"""
    if isinstance(symbols, str):
        symbols = [symbols]

    if frame_type in min_level_frames:
        start = start_time.format(TIME_FORMAT)
        end = end_time.format(TIME_FORMAT)
    else:
        start = start_time.format(DATE_FORMAT)
        end = end_time.format(DATE_FORMAT)

    # todo: 增加重启重连功能、超时功能
    try:
        return xt.download_history_data2(symbols, frame_type.value, start, end)  # type: ignore
    except Exception as e:
        raise XtQuantError.parse_msg(str(e))


def get_bars(symbols: List[str], frame_type: FrameType, start: Arrow, end: Arrow):
    if frame_type in min_level_frames:
        FMT = TIME_FORMAT
    else:
        FMT = DATE_FORMAT

    return xt.get_market_data(
        stock_list=symbols,
        period=frame_type.value,
        start_time=start.format(FMT),
        end_time=end.format(FMT),
        fill_data=False,
        dividend_type='none'
    )

@cache
def get_ashare_list():
    ashare_all = "沪深A股"
    return xt.get_stock_list_in_sector(ashare_all)

def get_sectors():
    sectors = xt.download_sector_data()

@cache
def get_calendar():
    market = 'SH'
    days = xt.get_trading_dates(market, start_time='', end_time='')
    return np.array(days, dtype='datetime64[ms]').astype(datetime.date)
