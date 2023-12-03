import datetime
import pickle
from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import xtquant.xtdata as xt
from blacksheep import (
    Content,
    FromJSON,
    FromQuery,
    Response,
    StreamedContent,
    get,
    json,
    post,
)


@dataclass
class MarketDataRequest:
    start: str
    end: str
    count: int=-1
    dividend_type: str = 'none'
    period: str = '1d'
    fill_data: bool=True
    stocks: Optional[List[str]] = None

@get("/qmt/calendar")
async def get_calendar(
    start: FromQuery[str],
    end: FromQuery[str],
    market: FromQuery[Optional[str]] = FromQuery("sh"),
) -> Response:
    """获取交易日历

    Args:
        start: 起始日期
        end: 结束日期
        market: 交易市场代码。如果未传入，默认取沪市日历
    """
    # mv = market.value or "sh"
    dates_in_ms = xt.get_trading_dates(market.value, start.value, end.value)
    dates = np.array(dates_in_ms, dtype="datetime64[ms]").astype(datetime.date)

    return json(dates.tolist())


@get("/qmt/stock_list_in_sector")
async def get_stock_list_in_sector(name: FromQuery[str] = FromQuery("沪深A股")):
    """获取板块成员名单

    如果板块名称未传入，则默认取沪深全A名单。
    """
    stocks = xt.get_stock_list_in_sector(name.value)
    return json(stocks)


@get("/qmt/sector_list")
async def get_sector_list():
    """获取所有板块信息"""
    return json(xt.get_sector_list())


@get("/qmt/instrument_type")
async def get_instrument_type(
    sec: FromQuery[str], instruments: FromQuery[List[str]]
) -> dict:
    """判断`sec`(证券代码)是否属于`instruments`指定的品种

    Example:
        /instrument_type?sec=000001.SH&instruments=index&instruments=stock
    """
    return xt.get_instrument_type(sec.value, instruments.value)


@get("/qmt/instrument_detail")
async def get_instrument_detail(sec: FromQuery[str]) -> dict|None:
    return xt.get_instrument_detail(sec.value)


@get("/qmt/divid_factors")
async def get_divid_factors(
    sec: FromQuery[str], start: FromQuery[str] = FromQuery(""), end: FromQuery[str]=FromQuery("")
)->str:
    df = xt.get_divid_factors(sec.value, start.value, end.value)
    return df.to_json()

@post("/qmt/market_data")
async def get_market_data(params: FromJSON[MarketDataRequest]):
    req = params.value
    data = xt.get_market_data(field_list=[],
                       stock_list=req.stocks or [],
                       period=req.period,
                       start_time = req.start,
                       end_time=req.end,
                       count=req.count,
                       dividend_type=req.dividend_type,
                       fill_data=req.fill_data)
    raise NotImplementedError
