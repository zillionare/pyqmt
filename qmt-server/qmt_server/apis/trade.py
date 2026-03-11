"""Trade APIs for qmt-server."""

import datetime
from typing import Any

from fasthtml.common import fast_app
from qmt_server.runtime import get_broker
from starlette.requests import Request
from starlette.responses import JSONResponse

from pyqmt.core.enums import OrderStatus

app, rt = fast_app()


def _to_dict(item: Any) -> dict[str, Any]:
    if hasattr(item, "to_dict"):
        return item.to_dict()
    if isinstance(item, dict):
        return item
    return {"value": str(item)}


def _ok(data: Any) -> JSONResponse:
    return JSONResponse({"code": 0, "message": "success", "data": data})


def _parse_date(value: str | None) -> datetime.date | None:
    if not value:
        return None
    return datetime.date.fromisoformat(value)


@rt("/asset")
async def get_asset(request: Request):
    """Get account asset snapshot."""
    broker = get_broker()
    return _ok(_to_dict(broker.get_asset()))


@rt("/positions")
async def get_positions(request: Request):
    """Get all positions."""
    broker = get_broker()
    data = [_to_dict(pos) for pos in broker.get_positions()]
    return _ok(data)


@rt("/orders")
async def get_orders(
    request: Request,
    status: str | None = None,
    start: str | None = None,
    end: str | None = None,
):
    """Query orders."""
    broker = get_broker()
    order_status = OrderStatus(status) if status else None
    data = [
        _to_dict(order)
        for order in broker.get_orders(
            status=order_status,
            start=_parse_date(start),
            end=_parse_date(end),
        )
    ]
    return _ok(data)


@rt("/trades")
async def get_trades(
    request: Request,
    start: str | None = None,
    end: str | None = None,
):
    """Query trades."""
    broker = get_broker()
    data = [
        _to_dict(trade)
        for trade in broker.get_trades(
            start=_parse_date(start),
            end=_parse_date(end),
        )
    ]
    return _ok(data)


@rt("/orders/buy", methods=["POST"])
async def buy(
    request: Request,
    asset: str,
    shares: int,
    price: float = 0,
    strategy: str = "",
):
    """Place a buy order."""
    broker = get_broker()
    trades = await broker.buy(
        asset=asset,
        shares=shares,
        price=price,
        strategy=strategy,
    )
    return _ok([_to_dict(trade) for trade in trades])


@rt("/orders/sell", methods=["POST"])
async def sell(
    request: Request,
    asset: str,
    shares: int,
    price: float = 0,
    strategy: str = "",
):
    """Place a sell order."""
    broker = get_broker()
    trades = await broker.sell(
        asset=asset,
        shares=shares,
        price=price,
        strategy=strategy,
    )
    return _ok([_to_dict(trade) for trade in trades])


@rt("/orders/{qtoid}/cancel", methods=["POST"])
async def cancel_order(request: Request, qtoid: str):
    """Cancel an order by qtoid."""
    broker = get_broker()
    await broker.cancel_order(qtoid)
    return _ok({"qtoid": qtoid, "status": "canceled"})
