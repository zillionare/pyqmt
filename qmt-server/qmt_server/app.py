"""qmt-server application entry."""

from fasthtml.common import Mount, Route, fast_app, serve
from qmt_server.apis import admin_app, quotes_app, sectors_app, trade_app
from qmt_server.runtime import ensure_ready
from starlette.responses import JSONResponse


async def _health():
    return JSONResponse({"code": 0, "message": "ok"})


def create_app():
    """Create and initialize qmt-server ASGI app."""
    ensure_ready()
    app, _ = fast_app(
        routes=[
            Route("/healthz", _health, methods=["GET"]),
            Mount("/admin", admin_app),
            Mount("/api/v1/trade", trade_app),
            Mount("/api/v1", sectors_app),
            Mount("/ws", quotes_app),
        ]
    )
    return app


def main():
    """Run qmt-server."""
    serve()


app = create_app()
