"""股票行情筛选程序

功能：
1. 通过 tushare 获取过去10日全市场行情数据
2. 筛选条件：
   - 存在某日成交量是之前5倍以上（t0日）
   - t0日之后都收阳线

注意：此脚本为独立脚本，临时存放于本项目。
"""

import datetime
import os
import time

import polars as pl
import tushare as ts
from loguru import logger


def fetch_history_data(pro, trade_date: datetime.date) -> pl.DataFrame:
    """获取单日全市场行情数据

    Args:
        pro: tushare pro 接口
        trade_date: 交易日期

    Returns:
        Polars DataFrame，包含 open, close, volume 等列
    """
    date_str = trade_date.strftime("%Y%m%d")

    try:
        df_pd = pro.daily(trade_date=date_str)
        if df_pd is None or df_pd.empty:
            return pl.DataFrame()

        df = pl.from_pandas(df_pd)

        # 统一列名
        df = df.rename({
            "ts_code": "symbol",
            "open": "open",
            "close": "close",
            "high": "high",
            "low": "low",
            "vol": "volume",
        })

        # 添加日期列
        df = df.with_columns(
            pl.lit(trade_date).alias("trade_date")
        )

        # 选择需要的列
        df = df.select(["symbol", "trade_date", "open", "close", "volume"])

        return df

    except Exception as e:
        logger.error(f"获取 {trade_date} 数据失败: {e}")
        return pl.DataFrame()


def fetch_stock_names(pro) -> dict[str, str]:
    """获取所有股票代码和名称的映射

    Args:
        pro: tushare pro 接口

    Returns:
        symbol -> name 的字典
    """
    try:
        df_basic = pro.stock_basic(exchange='', list_status='L',
                                    fields='ts_code,name')
        if df_basic is None or df_basic.empty:
            return {}

        return dict(zip(df_basic['ts_code'].tolist(), df_basic['name'].tolist()))
    except Exception as e:
        logger.error(f"获取股票名称失败: {e}")
        return {}


def fetch_last_10_days(pro) -> tuple[pl.DataFrame, dict[str, str]]:
    """获取过去10个交易日的全市场数据

    Args:
        pro: tushare pro 接口

    Returns:
        (合并后的 DataFrame, symbol->name 字典)
    """
    # 获取股票名称映射
    stock_names = fetch_stock_names(pro)
    logger.info(f"获取到 {len(stock_names)} 只股票的基本信息")

    # 获取最近10个交易日
    today = datetime.date.today()
    start_date = today - datetime.timedelta(days=20)  # 多取一些，过滤周末节假日

    df_trade_cal = pro.trade_cal(
        start_date=start_date.strftime("%Y%m%d"),
        end_date=today.strftime("%Y%m%d"),
        is_open=1
    )

    if df_trade_cal is None or df_trade_cal.empty:
        return pl.DataFrame(), stock_names

    trade_dates = [
        datetime.datetime.strptime(d, "%Y%m%d").date()
        for d in df_trade_cal["cal_date"].tolist()[-10:]  # 取最近10个交易日
    ]

    logger.info(f"将获取以下交易日的数据: {trade_dates}")

    all_data = []
    for trade_date in trade_dates:
        df = fetch_history_data(pro, trade_date)
        if not df.is_empty():
            all_data.append(df)
        time.sleep(0.1)  # 避免请求过快

    if not all_data:
        return pl.DataFrame(), stock_names

    return pl.concat(all_data), stock_names


def check_volume_spike(df: pl.DataFrame, symbol: str) -> tuple[bool, datetime.date | None]:
    """检查是否存在成交量放大5倍以上的日期

    排除前一日是一字板的情况（open == close），这是虚假信号。

    Args:
        df: 单个股票的数据
        symbol: 股票代码

    Returns:
        (是否存在, t0日期)
    """
    # 按日期排序
    df = df.sort("trade_date")

    if len(df) < 2:
        return False, None

    # 转换为列表便于索引
    data = df.to_dicts()

    # 从第2天开始检查（需要有前一天的数据做比较）
    for i in range(1, len(data)):
        prev_day = data[i - 1]
        curr_day = data[i]

        # 检查前一日是否是一字板（open == close）
        if prev_day["open"] == prev_day["close"]:
            continue  # 跳过虚假信号

        if prev_day["volume"] == 0:
            continue

        ratio = curr_day["volume"] / prev_day["volume"]
        if ratio >= 5.0:
            return True, curr_day["trade_date"]

    return False, None


def check_consecutive_yang(df: pl.DataFrame, t0_date: datetime.date) -> bool:
    """检查 t0 日之后是否都收阳线

    Args:
        df: 单个股票的数据
        t0_date: 成交量放大日

    Returns:
        是否都收阳线
    """
    df = df.sort("trade_date")

    # 获取 t0 日之后的数据（不包括 t0 日）
    df_after = df.filter(pl.col("trade_date") > t0_date)

    if df_after.is_empty():
        return False

    # 检查每一天是否收阳线（close > open）
    for row in df_after.iter_rows(named=True):
        if row["close"] <= row["open"]:
            return False

    return True


def calc_volatility(df: pl.DataFrame) -> float:
    """计算每日收益率的波动率（标准差）

    Args:
        df: 单个股票的数据，包含 close 列

    Returns:
        收益率标准差（波动率）
    """
    if len(df) < 2:
        return 0.0

    # 按日期排序
    df = df.sort("trade_date")

    # 计算每日收益率: (close_t / close_{t-1}) - 1
    closes = df["close"].to_list()
    returns = []
    for i in range(1, len(closes)):
        if closes[i - 1] > 0:
            daily_return = (closes[i] / closes[i - 1]) - 1
            returns.append(daily_return)

    if not returns:
        return 0.0

    # 计算标准差
    import statistics
    return statistics.stdev(returns)


def screen_stocks(df: pl.DataFrame, stock_names: dict[str, str]) -> list[dict]:
    """筛选符合条件的股票

    Args:
        df: 合并后的全市场数据
        stock_names: symbol -> name 的字典

    Returns:
        符合条件的股票列表
    """
    if df.is_empty():
        return []

    results = []

    # 按股票分组处理
    for symbol in df["symbol"].unique():
        symbol_df = df.filter(pl.col("symbol") == symbol)

        # 检查成交量放大
        has_spike, t0_date = check_volume_spike(symbol_df, symbol)

        if not has_spike or t0_date is None:
            continue

        # 检查 t0 日后是否都收阳线
        if check_consecutive_yang(symbol_df, t0_date):
            # 获取 t0 日的数据
            t0_data = symbol_df.filter(pl.col("trade_date") == t0_date).row(0, named=True)

            # 计算波动率
            volatility = calc_volatility(symbol_df)

            results.append({
                "symbol": symbol,
                "name": stock_names.get(symbol, "未知"),
                "t0_date": t0_date,
                "t0_close": t0_data["close"],
                "t0_volume": t0_data["volume"],
                "days_after": len(symbol_df.filter(pl.col("trade_date") > t0_date)),
                "volatility": volatility,
            })

    return results


def main():
    """主函数"""
    logger.info("开始股票筛选...")

    # 初始化 tushare
    pro = ts.pro_api()

    # 获取历史数据
    logger.info("获取历史数据...")
    history_df, stock_names = fetch_last_10_days(pro)

    if history_df.is_empty():
        logger.error("未能获取历史数据")
        return

    logger.info(f"获取到 {history_df['symbol'].n_unique()} 只股票的历史数据")

    # 筛选股票
    logger.info("开始筛选...")
    results = screen_stocks(history_df, stock_names)

    # 打印结果
    print("\n" + "=" * 80)
    print("筛选结果")
    print("=" * 80)

    if not results:
        print("没有符合条件的股票")
    else:
        # 转换为 DataFrame
        result_df = pl.DataFrame(results)

        # 调整列顺序
        result_df = result_df.select([
            "symbol", "name", "t0_date", "t0_close", "t0_volume", "days_after", "volatility"
        ])

        # 格式化输出
        print(f"共找到 {len(results)} 只符合条件的股票:\n")
        print(result_df.to_pandas().to_string(index=False))

    print("=" * 80)


if __name__ == "__main__":
    main()
