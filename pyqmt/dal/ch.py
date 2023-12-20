import datetime
from typing import List, Tuple

import cfg4py
import clickhouse_connect
import pandas as pd
from clickhouse_connect.driver.client import Client
from coretypes import Frame, FrameType, SecurityType

from pyqmt.core.constants import CH_SECURITIES_TBL


class ClickHouse(object):
    def __init__(self):
        self.client: Client = None  # type: ignore

    def connect(self):
        cfg = cfg4py.get_instance()
        host = cfg.clickhouse.host
        user = cfg.clickhouse.user
        password = cfg.clickhouse.password
        database = cfg.clickhouse.database
        self.client = clickhouse_connect.get_client(
            host=host, username=user, password=password, database=database
        )

    def save_bars(self, frame_type: FrameType, bars):
        if frame_type == FrameType.DAY:
            table = "day_bars"
        else:
            table = "1m_bars"

        self.client.insert(table, bars, column_names=bars.dtype.names)

    def save_ashare_list(self, data: List[Tuple[datetime.date, str, str, str, datetime.date, datetime.date]]):
        """保存证券（股票、指数）列表

        Args:
            data: contains date, code, alias, ipo day, exit day and type
        """
        cols = ["dt", "code", "alias", "ipo", "exit", "type"]
        self.client.insert(CH_SECURITIES_TBL, data, column_names=cols)
