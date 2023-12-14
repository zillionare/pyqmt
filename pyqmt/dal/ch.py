import cfg4py
import clickhouse_connect
from clickhouse_connect.driver.client import Client
from coretypes import Frame, FrameType


class ClickHouse(object):
    def __init__(self):
        self.client: Client = None # type: ignore

    def start(self):
        cfg = cfg4py.get_instance()
        host = cfg.db.host
        user = cfg.db.user
        password = cfg.db.password
        database = cfg.db.database
        self.client = clickhouse_connect.get_client(
            host=host, username=user, password=password, database=database
        )

    def save_bars(self, frame_type: FrameType, bars):
        if frame_type == FrameType.DAY:
            table = "day_bars"
        else:
            table = "1m_bars"

        self.client.insert(table, bars, column_names = bars.dtype.names)
