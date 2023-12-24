import datetime
from typing import List, Tuple

import cfg4py
import clickhouse_connect
import pandas as pd
from clickhouse_connect.driver.client import Client
from coretypes import Frame, FrameType, SecurityType

from pyqmt.core.constants import HaystoreTbl


class Haystore(object):
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
        assert frame_type in [FrameType.DAY, FrameType.MIN1]
        if frame_type == FrameType.DAY:
            table = HaystoreTbl.bars_1d
        else:
            table = HaystoreTbl.bars_1m

        self.client.insert(table, bars, column_names=bars.dtype.names)

    def save_ashare_list(
        self,
        data: List[Tuple[datetime.date, str, str, str, datetime.date, datetime.date]],
    ):
        """保存证券（股票、指数）列表

        Args:
            data: contains date, code, alias, ipo day, exit day and type
        """
        cols = ["dt", "symbol", "alias", "ipo", "exit", "type"]
        self.client.insert(HaystoreTbl.securities, data, column_names=cols)

    def save_factors(self, data):
        pass
