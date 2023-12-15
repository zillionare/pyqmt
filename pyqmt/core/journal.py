import logging
from sqlite3 import Row
from typing import Any, Optional, Union

import cfg4py
from arrow import Arrow
from coretypes import FrameType

logger = logging.getLogger(__name__)
cfg = cfg4py.get_instance()


def load_sync_status(
    frame_type: FrameType, col: Optional[str] = None
) -> Union[Row, Any]:
    """加载同步状态

    创建数据库时，必须指定1d, 1m的epoch
    """
    cur = cfg.sqlite.cursor()
    sql = "select * from sync_status where frame_type = ?"
    query = cur.execute(sql, (6,))
    record = query.fetchone()

    return record[col] if col is not None else record


def save_sync_status(start: Arrow, end: Arrow, frame_type: FrameType):
    cur = cfg.sqlite.cursor()
    sql = "update sync_status set start = ?, end = ? where frame_type = ?"
    cur.execute(sql, (start.date(), end.date(), FrameType.to_int(frame_type)))
    cfg.sqlite.commit()


def save_sync_status_1m(synced_start: Arrow, synced_end: Arrow):
    global status_file
    status = load_sync_status()
    status[SYNCED_1m_START] = synced_start.format("YYYYMMDDHHmmss")
    status[SYNCED_1m_END] = synced_end.format("YYYYMMDDHHmmss")

    with open(status_file, "w", encoding="utf-8") as f:
        json.dump(status, f)
