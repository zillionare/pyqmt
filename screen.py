"""股票行情筛选程序

功能：
1. volume: 筛选成交量放大且后续收阳线的股票
2. slope: 计算5日均线斜率和决定系数

用法：
    python screen.py volume
    python screen.py slope
"""

import datetime
import time
from typing import Optional

import fire
import numpy as np
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


def fetch_last_n_days(pro, n: int = 10) -> tuple[pl.DataFrame, dict[str, str]]:
    """获取过去N个交易日的全市场数据

    Args:
        pro: tushare pro 接口
        n: 交易日数量

    Returns:
        (合并后的 DataFrame, symbol->name 字典)
    """
    # 获取股票名称映射
    stock_names = fetch_stock_names(pro)
    logger.info(f"获取到 {len(stock_names)} 只股票的基本信息")

    # 获取最近N个交易日
    today = datetime.date.today()
    start_date = today - datetime.timedelta(days=n * 2)  # 多取一些，过滤周末节假日

    df_trade_cal = pro.trade_cal(
        start_date=start_date.strftime("%Y%m%d"),
        end_date=today.strftime("%Y%m%d"),
        is_open=1
    )

    if df_trade_cal is None or df_trade_cal.empty:
        return pl.DataFrame(), stock_names

    trade_dates = [
        datetime.datetime.strptime(d, "%Y%m%d").date()
        for d in df_trade_cal["cal_date"].tolist()[-n:]  # 取最近N个交易日
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


def check_volume_spike(df: pl.DataFrame, symbol: str) -> tuple[bool, datetime.date | None, float]:
    """检查是否存在成交量放大5倍以上的日期

    排除前一日是一字板的情况（open == close），这是虚假信号。

    Args:
        df: 单个股票的数据
        symbol: 股票代码

    Returns:
        (是否存在, t0日期, 放大倍数)
    """
    # 按日期排序
    df = df.sort("trade_date")

    if len(df) < 2:
        return False, None, 0.0

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
            return True, curr_day["trade_date"], ratio

    return False, None, 0.0


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
        收益率标准差（波动率），保留两位小数
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

    if len(returns) < 2:
        return 0.0

    # 计算标准差
    import statistics
    return round(statistics.stdev(returns), 2)


def calc_ma_slope_and_r2(closes: list[float], ma_period: int = 5) -> tuple[float, float]:
    """计算均线最后三点斜率和决定系数

    Args:
        closes: 收盘价列表（按时间顺序）
        ma_period: 均线周期，默认5日

    Returns:
        (最后三点斜率, 决定系数R²)
    """
    if len(closes) < ma_period + 1:
        return 0.0, 0.0

    # 计算MA
    ma_values = []
    for i in range(ma_period - 1, len(closes)):
        ma = sum(closes[i - ma_period + 1:i + 1]) / ma_period
        ma_values.append(ma)

    # 需要至少6个MA点（5日均线需要6个有效数据点）
    if len(ma_values) < 6:
        return 0.0, 0.0

    # 取最后6个MA点
    x = np.arange(len(ma_values))
    y = np.array(ma_values)

    # 线性回归计算斜率和R²
    coeffs = np.polyfit(x, y, 1)
    slope = coeffs[0]

    # 计算R²
    y_pred = np.polyval(coeffs, x)
    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0.0

    # 计算最后三点斜率
    last_three_slope = (ma_values[-1] - ma_values[-3]) / 2

    return last_three_slope, r_squared


class Screener:
    """股票筛选器"""

    def __init__(self):
        self.pro = ts.pro_api()

    def volume(self):
        """筛选成交量放大且后续收阳线的股票

        筛选条件：
        - 存在某日成交量是之前5倍以上（t0日）
        - t0日之后都收阳线
        """
        logger.info("开始成交量放大筛选...")

        # 获取历史数据
        history_df, stock_names = fetch_last_n_days(self.pro, n=10)

        if history_df.is_empty():
            logger.error("未能获取历史数据")
            return

        logger.info(f"获取到 {history_df['symbol'].n_unique()} 只股票的历史数据")

        # 筛选股票
        results = []
        for symbol in history_df["symbol"].unique():
            symbol_df = history_df.filter(pl.col("symbol") == symbol)

            # 检查成交量放大
            has_spike, t0_date, ratio = check_volume_spike(symbol_df, symbol)

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
                    "volume_ratio": round(ratio, 2),
                    "days_after": len(symbol_df.filter(pl.col("trade_date") > t0_date)),
                    "volatility": volatility,
                })

        # 打印结果
        print("\n" + "=" * 80)
        print("成交量放大筛选结果")
        print("=" * 80)

        if not results:
            print("没有符合条件的股票")
        else:
            result_df = pl.DataFrame(results)
            print(f"共找到 {len(results)} 只符合条件的股票:\n")
            print(result_df.to_pandas().to_string(index=False))

        print("=" * 80)

    def slope(self):
        """计算5日均线斜率和决定系数

        取最近10天数据，计算5日均线（6个有效数据点），
        按最后三点斜率由高到低排序，过滤掉决定系数低于75%分位的，
        最多输出前10支。
        """
        logger.info("开始均线斜率筛选...")

        # 获取历史数据（需要至少10天来计算5日均线）
        history_df, stock_names = fetch_last_n_days(self.pro, n=15)

        if history_df.is_empty():
            logger.error("未能获取历史数据")
            return

        logger.info(f"获取到 {history_df['symbol'].n_unique()} 只股票的历史数据")

        # 计算每只股票的数据
        results = []
        for symbol in history_df["symbol"].unique():
            symbol_df = history_df.filter(pl.col("symbol") == symbol)

            # 按日期排序获取收盘价
            symbol_df = symbol_df.sort("trade_date")
            closes = symbol_df["close"].to_list()

            # 计算5日均线斜率和R²
            last_three_slope, r_squared = calc_ma_slope_and_r2(closes, ma_period=5)

            # 只保留有有效数据的股票
            if last_three_slope != 0.0 or r_squared != 0.0:
                results.append({
                    "symbol": symbol,
                    "name": stock_names.get(symbol, "未知"),
                    "slope": round(last_three_slope, 4),
                    "r_squared": round(r_squared, 4),
                    "data_points": len(closes),
                })

        if not results:
            print("没有符合条件的股票")
            return

        # 按斜率由高到低排序
        results.sort(key=lambda x: x["slope"], reverse=True)

        # 计算R²的75%分位
        r2_values = [r["r_squared"] for r in results]
        r2_75th = np.percentile(r2_values, 75)

        logger.info(f"R² 75%分位: {r2_75th:.4f}")

        # 过滤掉R²低于75%分位的
        filtered_results = [r for r in results if r["r_squared"] >= r2_75th]

        # 只取前10支
        top_10 = filtered_results[:10]

        # 打印结果
        print("\n" + "=" * 80)
        print("均线斜率筛选结果（5日均线，R²>=75%分位，前10支）")
        print("=" * 80)

        if not top_10:
            print("没有符合条件的股票")
        else:
            result_df = pl.DataFrame(top_10)
            print(f"共找到 {len(top_10)} 只符合条件的股票（R²阈值: {r2_75th:.4f}）:\n")
            print(result_df.to_pandas().to_string(index=False))

        print("=" * 80)


def main():
    """主函数入口"""
    fire.Fire(Screener)


if __name__ == "__main__":
    main()
