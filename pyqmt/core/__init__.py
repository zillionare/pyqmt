import datetime
import logging
from functools import wraps

logger = logging.getLogger(__name__)


def handle_xt_error(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.warning("calling %s with %s, %s cause exception", args, kwargs)
            logger.exception(e)

    return wrapper


def str2date(dt: str) -> datetime.date:
    if len(dt) != 8:
        raise ValueError(f"input date should be at 8 length, got {dt}")

    year, month, day = int(dt[:4]), int(dt[4:6]), int(dt[6:])
    return datetime.date(year, month, day)


def date2str(dt: datetime.date) -> str:
    return f"{dt.year:0>4}{dt.month:0>2}{dt.day:0>2}"


def str2time(dt: str) -> datetime.datetime:
    if len(dt) != 14:
        raise ValueError(f"input date should be at 14 length, got {dt}")

    year, month, day, hour, minute, second = (
        int(dt[:4]),
        int(dt[4:6]),
        int(dt[6:8]),
        int(dt[8:10]),
        int(dt[10:12]),
        int(dt[12:14]),
    )

    return datetime.datetime(year, month, day, hour, minute, second)


def time2str(dt: datetime.datetime) -> str:
    return f"{dt.year:0>4}{dt.month:0>2}{dt.day:0>2}{dt.hour:0>2}{dt.minute:0>2}{dt.second:0>2}"
