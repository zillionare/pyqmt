"""Sector APIs for qmt-server."""

import datetime

from fasthtml.common import fast_app
from qmt_server.runtime import get_sector_sync
from starlette.requests import Request
from starlette.responses import JSONResponse

from pyqmt.data.dal.sector_dal import SectorDAL
from pyqmt.data.sqlite import db

app, rt = fast_app()


def _ok(data):
    return JSONResponse({"code": 0, "message": "success", "data": data})


def _page(items: list[dict], page: int, size: int) -> dict:
    total = len(items)
    start = max(page - 1, 0) * size
    end = start + size
    return {
        "items": items[start:end],
        "total": total,
        "page": page,
        "size": size,
    }


def _as_date(value: str | None) -> datetime.date:
    if value:
        return datetime.date.fromisoformat(value)
    return datetime.date.today()


@rt("/sectors")
async def list_sectors(
    request: Request,
    sector_type: str | None = None,
    trade_date: str | None = None,
    page: int = 1,
    size: int = 50,
):
    """List sectors by date and type."""
    dal = SectorDAL(db)
    items = dal.list_sectors(
        sector_type=sector_type,
        trade_date=_as_date(trade_date),
    )
    rows = [item.to_dict() for item in items]
    return _ok(_page(rows, page=page, size=size))


@rt("/sectors/{sector_id}/constituents")
async def list_constituents(
    request: Request,
    sector_id: str,
    trade_date: str | None = None,
    page: int = 1,
    size: int = 100,
):
    """List constituents of a sector."""
    dal = SectorDAL(db)
    items = dal.get_constituents(
        sector_id=sector_id,
        trade_date=_as_date(trade_date),
    )
    rows = [item.to_dict() for item in items]
    return _ok(_page(rows, page=page, size=size))


@rt("/sync/sectors", methods=["POST"])
async def sync_sectors(request: Request, trade_date: str | None = None):
    """Run sector universe sync once."""
    service = get_sector_sync()
    dt = _as_date(trade_date)
    sectors = service.sync_sector_list(trade_date=dt)
    constituents = service.sync_sector_constituents(trade_date=dt)
    return _ok(
        {
            "trade_date": dt.isoformat(),
            "sectors": sectors,
            "constituents": constituents,
        }
    )


@rt("/sync/sector-bars", methods=["POST"])
async def sync_sector_bars(request: Request, trade_date: str | None = None):
    """Run sector bars sync once."""
    service = get_sector_sync()
    dt = _as_date(trade_date)
    sectors = service.dal.list_sectors(trade_date=dt)
    ids = [item.id for item in sectors]
    records = service.bars_store.fetch_multiple(
        sector_ids=ids,
        start=dt,
        end=dt,
    )
    return _ok({"trade_date": dt.isoformat(), "bars": records})


@rt("/sectors/{sector_id}/bars")
async def get_sector_bars(
    request: Request,
    sector_id: str,
    start: str | None = None,
    end: str | None = None,
):
    """Get sector bars from parquet storage."""
    service = get_sector_sync()
    start_date = _as_date(start)
    end_date = _as_date(end) if end else start_date
    df = service.bars_store.get(
        sector_ids=[sector_id],
        start=start_date,
        end=end_date,
        eager_mode=True,
    )
    return _ok(df.to_dicts())
