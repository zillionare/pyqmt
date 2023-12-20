import sqlite3

import arrow
import cfg4py
import pytest
from coretypes import FrameType

from pyqmt.core.timeframe import tf
from pyqmt.dal.cache import RedisCache
from pyqmt.service.sync import (
    sync_ashare_list,
    sync_bars_backward,
    sync_bars_forward,
    sync_calendar,
)
from tests.config import get_config_dir, init_chores_db


@pytest.fixture(scope="function", autouse=True)
def setup():
    print("called init")
    cfg = cfg4py.init(get_config_dir())
    cfg.chores_db = sqlite3.connect(cfg.chores_db_path, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)  # type: ignore
    cfg.chores_db.row_factory = sqlite3.Row

    init_chores_db(cfg.chores_db)

    cfg.cache = RedisCache()
    cfg.cache.r.flushall()

    sync_calendar()
    tf.init()


@pytest.mark.parametrize(
    "symbols, frame_type",
    [(["000001.SZ"], FrameType.DAY), (["000001.SZ"], FrameType.MIN1)],
)
def test_sync_bars_forward(symbols, frame_type):
    sync_bars_forward(symbols, frame_type)


@pytest.mark.parametrize(
    "symbols, frame_type",
    [(["000001.SZ"], FrameType.DAY), (["000001.SZ"], FrameType.MIN1)],
)
def test_sync_bars_backward(symbols, frame_type):
    sync_bars_forward(symbols, frame_type)
    sync_bars_backward(symbols, frame_type)

def test_sync_calendar():
    cfg = cfg4py.get_instance()

    cfg.cache.r.flushall()
    sync_calendar()

    keys = cfg.cache.r.keys()
    assert "calendar:1d" in keys

    tf.init()
    last_trading_day = tf.floor(arrow.now().date(), FrameType.DAY)
    assert tf.int2date(tf.day_frames[-1]) == last_trading_day

def test_sync_ashare_list():
    sync_ashare_list()
