import logging
from sqlite3 import Row
from typing import Any, Optional, Union

import cfg4py
from arrow import Arrow
from coretypes import FrameType

logger = logging.getLogger(__name__)
cfg = cfg4py.get_instance()


def bars_cache_status(
    frame_type: FrameType, col: Optional[str] = None
) -> Union[Row, Any]:
    """加载同步状态

    创建数据库时，必须指定1d, 1m的epoch
    """
    cur = cfg.sqlite.cursor()
    sql = "select * from bars_cache_status where frame_type = ?"
    query = cur.execute(sql, (6,))
    record = query.fetchone()

    return record[col] if col is not None else record


def save_bars_cache_status(start: Arrow, end: Arrow, frame_type: FrameType):
    cur = cfg.sqlite.cursor()
    sql = "update bars_cache_status set start = ?, end = ? where frame_type = ?"
    cur.execute(sql, (start.date(), end.date(), FrameType.to_int(frame_type)))
    cfg.sqlite.commit()
