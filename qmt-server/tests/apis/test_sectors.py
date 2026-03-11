from qmt_server.apis.sectors import app as sectors_app
from starlette.testclient import TestClient


class _Data:
    def __init__(self, value):
        self.value = value

    def to_dict(self):
        return self.value


class _FakeDal:
    def __init__(self, _db):
        self.db = _db

    def list_sectors(self, sector_type=None, trade_date=None):
        assert trade_date is not None
        return [_Data({"id": "BK001", "name": "板块"})]

    def get_constituents(self, sector_id, trade_date):
        assert sector_id == "BK001"
        assert trade_date is not None
        return [_Data({"symbol": "000001.SZ"})]


class _FakeSync:
    class _BarsStore:
        def fetch_multiple(self, sector_ids, start, end):
            assert isinstance(sector_ids, list)
            assert start is not None
            assert end is not None
            return 3

        def get(self, sector_ids, start, end, eager_mode=True):
            class _DF:
                def to_dicts(self):
                    return [{"sector_id": sector_ids[0], "open": 1.0}]

            return _DF()

    class _Dal:
        class _Sector:
            id = "BK001"

        def list_sectors(self, trade_date=None):
            assert trade_date is not None
            return [self._Sector()]

    def __init__(self):
        self.bars_store = self._BarsStore()
        self.dal = self._Dal()

    def sync_sector_list(self, trade_date):
        assert trade_date is not None
        return 1

    def sync_sector_constituents(self, trade_date):
        assert trade_date is not None
        return 2

    def sync_daily_bars(self, trade_date):
        assert trade_date is not None
        return 3


def test_sector_routes(monkeypatch):
    monkeypatch.setattr("qmt_server.apis.sectors.SectorDAL", _FakeDal)
    monkeypatch.setattr("qmt_server.apis.sectors.get_sector_sync", lambda: _FakeSync())
    client = TestClient(sectors_app)

    resp = client.get("/sectors", params={"trade_date": "2026-03-11"})
    assert resp.status_code == 200
    assert resp.json()["data"]["items"][0]["id"] == "BK001"

    resp = client.get("/sectors/BK001/constituents", params={"trade_date": "2026-03-11"})
    assert resp.status_code == 200
    assert resp.json()["data"]["items"][0]["symbol"] == "000001.SZ"

    resp = client.post("/sync/sectors", params={"trade_date": "2026-03-11"})
    assert resp.status_code == 200
    assert resp.json()["data"]["sectors"] == 1
    assert resp.json()["data"]["constituents"] == 2

    resp = client.post("/sync/sector-bars", params={"trade_date": "2026-03-11"})
    assert resp.status_code == 200
    assert resp.json()["data"]["bars"] == 3

    resp = client.get("/sectors/BK001/bars", params={"start": "2026-03-01", "end": "2026-03-11"})
    assert resp.status_code == 200
    assert resp.json()["data"][0]["sector_id"] == "BK001"
