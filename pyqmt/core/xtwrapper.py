from typing import List, Optional, Union

import arrow
from arrow import Arrow
from coretypes import Frame, FrameType
from xtquant.xtdata import download_history_data2

from pyqmt.core.constants import DATE_FORMAT, TIME_FORMAT, min_level_frames
from pyqmt.core.errors import XtQuantError


def cache_bars(stock_list: Union[str, List[str]], frame_type: FrameType, start_time: Arrow, end_time:Arrow)->bool:
    """让xtdata缓存行情数据"""
    if isinstance(stock_list, str):
        stock_list = [stock_list]

    if frame_type in min_level_frames:
        start = start_time.format(TIME_FORMAT)
        end = end_time.format(TIME_FORMAT)
    else:
        start = start_time.format(DATE_FORMAT)
        end = end_time.format(DATE_FORMAT)

    # todo: 增加重启重连功能
    try:
        return download_history_data2(stock_list, frame_type.value, start, end) # type: ignore
    except Exception as e:
        raise XtQuantError.parse_msg(str(e))
