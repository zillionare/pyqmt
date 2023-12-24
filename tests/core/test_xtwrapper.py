from unittest.mock import patch

import numpy as np

from pyqmt.core.xtwrapper import get_ashare_list


def test_get_ashare_list():
    """测试get_ashare_list的cache机制"""
    ashares = get_ashare_list()
    with patch(
        "pyqmt.core.xtwrapper.xt.get_stock_list_in_sector", return_value=["hello"]
    ):
        cached = get_ashare_list()
        assert np.array_equal(cached, ashares)

        get_ashare_list.cache_clear()
        result = get_ashare_list()
        assert np.array_equal(result, ["hello"])
