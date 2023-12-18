import datetime
from typing import List

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

    def save_ashare_list(self, ashares: List[str], _type: SecurityType, dt: datetime.date):
        """保存`frame`日的证券（股票、指数）列表

        Args:
            ashares: 证券列表
            _type: "stock", "index"中的一个
            dt:  归属日期
        """
        df = pd.DataFrame(ashares, columns=["symbol"])

        df["symbol"] = df["symbol"].str.replace(".SH", ".XSHG")
        df["symbol"] = df["symbol"].str.replace(".SZ", ".XSHE")
        df["date"] = [dt] * len(df)
        df["type"] = [_type.value] * len(df)

        self.client.insert(CH_SECURITIES_TBL, df.values, column_names=df.columns)
