import datetime
import logging
from sqlite3 import Row
from typing import Any, Optional, Union

import cfg4py
from arrow import Arrow
from coretypes import FrameType
from numpy.typing import NDArray

from pyqmt.core.constants import ChoreTbl

logger = logging.getLogger(__name__)
cfg = cfg4py.get_instance()


def bars_cache_status(
    frame_type: FrameType, col: Optional[str] = None
) -> Union[Row, Any]:
    """加载同步状态

    创建数据库时，必须指定1d, 1m的epoch
    """
    cur = cfg.chores_db.cursor()
    sql = f"select * from {ChoreTbl.bars_cache} where frame_type = ?"
    query = cur.execute(sql, (FrameType.to_int(frame_type),))
    record = query.fetchone()

    return record[col] if col is not None else record


def save_bars_cache_status(start: Arrow, end: Arrow, frame_type: FrameType):
    cur = cfg.chores_db.cursor()
    sql = f"update {ChoreTbl.bars_cache} set start = ?, end = ? where frame_type = ?"
    cur.execute(sql, (start.date(), end.date(), FrameType.to_int(frame_type)))
    cfg.chores_db.commit()


def ashares_sync_status(dt: datetime.date) -> bool:
    """检查某天的a股列表是否已同步到clickhouse"""
    cur = cfg.chores_db.cursor()
    sql = f"select * from {ChoreTbl.ashares_sync} where frame = ?"
    query = cur.execute(sql, (dt,))
    return query.fetchone() is not None

def save_ashares_sync_status(dt: datetime.date, count:int):
    """保存A股列表同步状态"""
    sql = f"insert into {ChoreTbl.ashares_sync}('frame', 'count') values (?, ?)"
    cur = cfg.chores_db.cursor()
    cur.execute(sql, (dt, count))
    cfg.chores_db.commit()
