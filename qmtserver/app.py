"""Main module."""

import uvicorn
from blacksheep import Application, get

from qmtserver.handlers import data

app = Application()


@get("/status")
async def status():
    return "OK"
