import sqlite3

import cfg4py
import pytest
from coretypes import FrameType

from pyqmt.service.tasks import do_sync_backward, do_sync_forward
from tests.config import get_config_dir, init_sqlite_db


@pytest.fixture(scope="module", autouse=True)
def setup():
    print("called init")
    cfg = cfg4py.init(get_config_dir())
    cfg.sqlite = sqlite3.connect(cfg.sqlite_path, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)  # type: ignore
    cfg.sqlite.row_factory = sqlite3.Row

    init_sqlite_db(cfg.sqlite)


@pytest.mark.parametrize(
        "symbols, frame_type",
        [
            (["000001.SZ"], FrameType.DAY),
            (["000001.SZ"], FrameType.MIN1)
        ]
)
def test_do_sync_forward(symbols, frame_type):
    do_sync_forward(symbols, frame_type)
