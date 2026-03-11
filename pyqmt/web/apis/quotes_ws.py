"""实时行情 WebSocket API。"""

import asyncio
import datetime
import json
from typing import Any

from fasthtml.common import fast_app
from loguru import logger
from starlette.websockets import WebSocket, WebSocketDisconnect

from pyqmt.core.enums import Topics
from pyqmt.core.message import msg_hub

app, rt = fast_app()


def _encode(topic: str, payload: Any) -> str:
    return json.dumps(
        {
            "topic": topic,
            "data": payload,
        },
        ensure_ascii=False,
        default=str,
    )


def _enqueue_message(
    queue: asyncio.Queue[tuple[str, Any]], topic: str, payload: Any
) -> None:
    if queue.full():
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
    queue.put_nowait((topic, payload))


async def quotes_ws(websocket: WebSocket):
    """行情推送 WebSocket 端点。

    Args:
        websocket: WebSocket 连接
    """
    await websocket.accept()
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue(maxsize=200)

    def on_quotes(data: Any) -> None:
        loop.call_soon_threadsafe(
            _enqueue_message, queue, Topics.QUOTES_ALL.value, data
        )

    def on_limits(data: Any) -> None:
        loop.call_soon_threadsafe(
            _enqueue_message, queue, Topics.STOCK_LIMIT.value, data
        )

    def on_bars_1m(data: Any) -> None:
        loop.call_soon_threadsafe(
            _enqueue_message, queue, Topics.BARS_1M.value, data
        )

    def on_bars_30m(data: Any) -> None:
        loop.call_soon_threadsafe(
            _enqueue_message, queue, Topics.BARS_30M.value, data
        )

    def on_bars_1d(data: Any) -> None:
        loop.call_soon_threadsafe(
            _enqueue_message, queue, Topics.BARS_1D.value, data
        )

    msg_hub.subscribe(Topics.QUOTES_ALL.value, on_quotes)
    msg_hub.subscribe(Topics.STOCK_LIMIT.value, on_limits)
    msg_hub.subscribe(Topics.BARS_1M.value, on_bars_1m)
    msg_hub.subscribe(Topics.BARS_30M.value, on_bars_30m)
    msg_hub.subscribe(Topics.BARS_1D.value, on_bars_1d)

    try:
        while True:
            try:
                topic, payload = await asyncio.wait_for(queue.get(), timeout=15)
                await websocket.send_text(_encode(topic, payload))
            except TimeoutError:
                await websocket.send_text(
                    _encode(
                        "heartbeat",
                        {"ts": datetime.datetime.now().isoformat()},
                    )
                )
    except WebSocketDisconnect:
        return
    except Exception as e:
        logger.error(f"quotes websocket error: {e}")
    finally:
        msg_hub.unsubscribe(Topics.QUOTES_ALL.value, on_quotes)
        msg_hub.unsubscribe(Topics.STOCK_LIMIT.value, on_limits)
        msg_hub.unsubscribe(Topics.BARS_1M.value, on_bars_1m)
        msg_hub.unsubscribe(Topics.BARS_30M.value, on_bars_30m)
        msg_hub.unsubscribe(Topics.BARS_1D.value, on_bars_1d)


app.add_websocket_route("/quotes", quotes_ws)
