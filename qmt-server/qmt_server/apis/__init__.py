"""API router exports for qmt-server."""

from qmt_server.apis.admin import app as admin_app
from qmt_server.apis.quotes import app as quotes_app
from qmt_server.apis.sectors import app as sectors_app
from qmt_server.apis.trade import app as trade_app

__all__ = ["admin_app", "quotes_app", "sectors_app", "trade_app"]
