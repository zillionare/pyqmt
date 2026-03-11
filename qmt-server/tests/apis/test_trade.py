import datetime

from starlette.testclient import TestClient

from qmt_server.apis.trade import app as trade_app


class _Data:
    def __init__(self, value):
        self.value = value

    def to_dict(self):
        return self.value


class _FakeBroker:
    def get_asset(self):
        return _Data({"cash": 1000})

    def get_positions(self):
        return [_Data({"asset": "000001.SZ", "shares": 100})]

    def get_orders(self, status=None, start=None, end=None):
        assert status is None
        assert isinstance(start, datetime.date) or start is None
        assert isinstance(end, datetime.date) or end is None
        return [_Data({"qtoid": "q1"})]

    def get_trades(self, start=None, end=None):
        assert isinstance(start, datetime.date) or start is None
        assert isinstance(end, datetime.date) or end is None
        return [_Data({"eid": "e1"})]

    async def buy(self, asset, shares, price, strategy):
        assert asset == "000001.SZ"
        assert shares == 100
        assert price == 10.0
        assert strategy == "s"
        return [_Data({"eid": "buy1"})]

    async def sell(self, asset, shares, price, strategy):
        assert asset == "000001.SZ"
        assert shares == 100
        assert price == 10.0
        assert strategy == "s"
        return [_Data({"eid": "sell1"})]

    async def cancel_order(self, qtoid):
        assert qtoid == "q1"


def test_trade_routes(monkeypatch):
    monkeypatch.setattr("qmt_server.apis.trade.get_broker", lambda: _FakeBroker())
    client = TestClient(trade_app)

    resp = client.get("/asset")
    assert resp.status_code == 200
    assert resp.json()["data"]["cash"] == 1000

    resp = client.get("/positions")
    assert resp.status_code == 200
    assert resp.json()["data"][0]["asset"] == "000001.SZ"

    resp = client.get("/orders", params={"start": "2026-03-01", "end": "2026-03-11"})
    assert resp.status_code == 200
    assert resp.json()["data"][0]["qtoid"] == "q1"

    resp = client.get("/trades", params={"start": "2026-03-01", "end": "2026-03-11"})
    assert resp.status_code == 200
    assert resp.json()["data"][0]["eid"] == "e1"

    resp = client.post(
        "/orders/buy",
        params={"asset": "000001.SZ", "shares": 100, "price": 10.0, "strategy": "s"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"][0]["eid"] == "buy1"

    resp = client.post(
        "/orders/sell",
        params={"asset": "000001.SZ", "shares": 100, "price": 10.0, "strategy": "s"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"][0]["eid"] == "sell1"

    resp = client.post("/orders/q1/cancel")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "canceled"
