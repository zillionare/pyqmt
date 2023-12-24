import arrow
import cfg4py
import pytest
from coretypes import SecurityType

from tests.config import get_config_dir, init_haystore


@pytest.fixture(scope="module", autouse=True)
def setup():
    init_haystore()


def test_save_securities():
    cfg = cfg4py.get_instance()

    shares = ["000001.SZ", "600001.SH"]
    cfg.haystore.save_ashare_list(shares, SecurityType.STOCK, arrow.now().date())
