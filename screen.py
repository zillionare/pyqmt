"""股票行情筛选程序

功能：
1. volume: 筛选成交量放大且后续收阳线的股票
2. slope: 计算5日均线斜率和决定系数

数据缓存：
- 默认缓存路径：/tmp/screen.pq
- 使用前复权数据（获取时带复权因子，存储前复权价格）
- 自动补齐缓存数据到最新日期

用法：
    python screen.py volume
    python screen.py slope
"""

import datetime
import sys
import time
from pathlib import Path

import fire
import numpy as np
import pandas as pd
import polars as pl
import tushare as ts
from loguru import logger
from tabulate import tabulate

# 配置日志级别为INFO，输出到stdout
logger.remove()
logger.add(sys.stdout, level="INFO")

# 默认缓存路径
SCREEN_DIR = Path.home() / "screen"
SCREEN_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_CACHE_PATH = str(SCREEN_DIR / "screen.pq")


def load_cached_data(cache_path: str = DEFAULT_CACHE_PATH) -> pl.DataFrame:
    """加载缓存数据

    Args:
        cache_path: 缓存文件路径

    Returns:
        缓存的DataFrame，如果没有缓存返回空DataFrame
    """
    cache_file = Path(cache_path)
    if not cache_file.exists():
        logger.info(f"缓存文件不存在: {cache_path}")
        return pl.DataFrame()

    try:
        df = pl.read_parquet(cache_path)
        logger.info(f"加载缓存数据: {len(df)} 条记录，日期范围: {df['trade_date'].min()} ~ {df['trade_date'].max()}")
        return df
    except Exception as e:
        logger.error(f"加载缓存数据失败: {e}")
        return pl.DataFrame()


def save_cached_data(df: pl.DataFrame, cache_path: str = DEFAULT_CACHE_PATH):
    """保存数据到缓存

    Args:
        df: 要保存的DataFrame
        cache_path: 缓存文件路径
    """
    try:
        df.write_parquet(cache_path)
        logger.info(f"数据已保存到缓存: {cache_path}，共 {len(df)} 条记录")
    except Exception as e:
        logger.error(f"保存缓存数据失败: {e}")


def get_trading_dates(pro, start_date: datetime.date, end_date: datetime.date) -> list[datetime.date]:
    """获取交易日列表（排除周末节假日）

    Args:
        pro: tushare pro 接口
        start_date: 开始日期
        end_date: 结束日期

    Returns:
        交易日列表
    """
    df_trade_cal = pro.trade_cal(
        start_date=start_date.strftime("%Y%m%d"),
        end_date=end_date.strftime("%Y%m%d"),
        is_open=1
    )

    if df_trade_cal is None or df_trade_cal.empty:
        return []

    return [
        datetime.datetime.strptime(d, "%Y%m%d").date()
        for d in df_trade_cal["cal_date"].tolist()
    ]


def fetch_daily_data(pro, trade_date: datetime.date) -> pl.DataFrame:
    """获取单日全市场行情数据（前复权）

    获取无复权数据 + 复权因子 + 换手率，计算前复权价格后存储

    Args:
        pro: tushare pro 接口
        trade_date: 交易日期

    Returns:
        Polars DataFrame，包含前复权的 open, close, volume, turnover 等列
    """
    date_str = trade_date.strftime("%Y%m%d")

    try:
        # 获取无复权日线数据
        df_daily = pro.daily(trade_date=date_str)
        if df_daily is None or df_daily.empty:
            return pl.DataFrame()

        # 获取复权因子
        df_adj = pro.adj_factor(trade_date=date_str)
        if df_adj is None or df_adj.empty:
            logger.warning(f"{trade_date} 未获取到复权因子，使用无复权数据")
            adj_dict = {}
        else:
            adj_dict = dict(zip(df_adj['ts_code'].tolist(), df_adj['adj_factor'].tolist()))

        # 获取换手率（从daily_basic接口）
        try:
            df_basic = pro.daily_basic(trade_date=date_str)
            if df_basic is not None and not df_basic.empty:
                turnover_dict = dict(zip(df_basic['ts_code'].tolist(), df_basic['turnover_rate'].tolist()))
            else:
                turnover_dict = {}
        except Exception as e:
            logger.warning(f"{trade_date} 获取换手率失败: {e}")
            turnover_dict = {}

        # 合并数据并计算前复权价格
        records = []
        for _, row in df_daily.iterrows():
            ts_code = row['ts_code']
            adj_factor = adj_dict.get(ts_code, 1.0)
            turnover = turnover_dict.get(ts_code, 0.0)

            records.append({
                'symbol': ts_code,
                'trade_date': trade_date,
                'open': row['open'] * adj_factor,
                'high': row['high'] * adj_factor,
                'low': row['low'] * adj_factor,
                'close': row['close'] * adj_factor,
                'volume': row['vol'],
                'turnover': turnover,
                'adj_factor': adj_factor,
            })

        return pl.DataFrame(records)

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


def update_cache(pro, cache_path: str = DEFAULT_CACHE_PATH, min_days: int = 70) -> pl.DataFrame:
    """更新缓存数据

    检查缓存中的日期范围，补齐数据以满足最少天数要求

    Args:
        pro: tushare pro 接口
        cache_path: 缓存文件路径
        min_days: 最少需要的数据天数，默认70天（确保RSI计算准确）

    Returns:
        更新后的完整DataFrame
    """
    # 加载现有缓存
    cached_df = load_cached_data(cache_path)

    today = datetime.date.today()

    if cached_df.is_empty():
        # 没有缓存，获取最近min_days天数据
        logger.info(f"没有缓存数据，获取最近{min_days}天数据...")
        start_date = today - datetime.timedelta(days=min_days + 30)  # 多取一些，过滤节假日
        trading_dates = get_trading_dates(pro, start_date, today)
        # 取最近min_days个交易日
        dates_to_fetch = trading_dates[-min_days:] if len(trading_dates) > min_days else trading_dates
    else:
        # 有缓存，检查日期范围
        max_date = cached_df['trade_date'].max()
        min_date = cached_df['trade_date'].min()
        current_days = len(cached_df['trade_date'].unique())
        logger.info(f"缓存日期范围: {min_date} ~ {max_date}，共 {current_days} 天")

        dates_to_fetch = []

        # 向后补齐：获取缓存最大日期之后的数据
        if max_date < today:
            forward_dates = get_trading_dates(pro, max_date + datetime.timedelta(days=1), today)
            dates_to_fetch.extend(forward_dates)
            logger.info(f"需要向后补齐 {len(forward_dates)} 个交易日: {forward_dates}")
            logger.info(f"today={today}, max_date={max_date}")

        # 向前补齐：如果数据不足min_days天，往前补
        if current_days < min_days:
            need_more = min_days - current_days + 5  # 多补5天
            logger.info(f"数据不足{min_days}天，需要向前补齐 {need_more} 个交易日")
            # 从当前最小日期往前推
            start_date = min_date - datetime.timedelta(days=need_more + 10)  # 多取一些
            backward_dates = get_trading_dates(pro, start_date, min_date - datetime.timedelta(days=1))
            # 取最后need_more天
            backward_dates = backward_dates[-need_more:] if len(backward_dates) > need_more else backward_dates
            dates_to_fetch.extend(backward_dates)
            logger.info(f"向前补齐的日期: {backward_dates}")

    # 获取缺失的数据
    new_data = []
    for trade_date in dates_to_fetch:
        df = fetch_daily_data(pro, trade_date)
        if not df.is_empty():
            new_data.append(df)
        else:
            logger.warning(f"{trade_date} 没有数据返回")
        time.sleep(0.1)  # 避免请求过快

    if not new_data:
        logger.info("没有新数据需要添加")
        return cached_df

    # 合并新数据
    new_df = pl.concat(new_data)
    logger.info(f"获取到新数据: {len(new_df)} 条记录")

    if cached_df.is_empty():
        combined_df = new_df
    else:
        # 合并并去重
        combined_df = pl.concat([cached_df, new_df])
        combined_df = combined_df.unique(subset=['symbol', 'trade_date'])

    # 保存到缓存
    save_cached_data(combined_df, cache_path)

    return combined_df


def calc_rsi(prices: list[float], period: int = 6) -> float:
    """计算RSI指标（使用Wilder平滑移动平均）

    标准RSI计算使用Wilder's Smoothing，而非简单移动平均

    Args:
        prices: 价格列表（按时间顺序）
        period: RSI周期，默认6

    Returns:
        RSI值（0-100）
    """
    if len(prices) < period + 1:
        return 0.0

    # 计算涨跌幅
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]

    # 分离上涨和下跌
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]

    # 使用Wilder平滑移动平均计算RSI
    # 第一个平均增益/损失使用简单平均
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    # 后续使用平滑移动平均
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    return round(rsi, 2)


def check_volume_spike(df: pl.DataFrame, symbol: str) -> tuple[bool, datetime.date | None, float]:
    """检查是否存在成交量放大5倍以上的日期

    排除前一日是一字板的情况（open == close），这是虚假信号。

    Args:
        df: 单个股票的数据
        symbol: 股票代码

    Returns:
        (是否存在, t0日期, 放大倍数)
    """
    df = df.sort("trade_date")

    if len(df) < 2:
        return False, None, 0.0

    data = df.to_dicts()

    for i in range(1, len(data)):
        prev_day = data[i - 1]
        curr_day = data[i]

        if prev_day["open"] == prev_day["close"]:
            continue

        if prev_day["volume"] == 0:
            continue

        ratio = curr_day["volume"] / prev_day["volume"]
        if ratio >= 5.0:
            return True, curr_day["trade_date"], ratio

    return False, None, 0.0


def check_consecutive_yang(df: pl.DataFrame, t0_date: datetime.date) -> tuple[bool, float]:
    """检查 t0 日之后是否都收阳线，并返回放量后的最小成交量

    Args:
        df: 单个股票的数据
        t0_date: 成交量放大日

    Returns:
        (是否都收阳线, 放量后最小成交量)
    """
    df = df.sort("trade_date")
    df_after = df.filter(pl.col("trade_date") > t0_date)

    if df_after.is_empty():
        return False, 0.0

    min_volume = float('inf')
    for row in df_after.iter_rows(named=True):
        close_price = row["close"]
        open_price = row["open"]
        volume = row.get("volume", 0)

        if close_price <= open_price:
            return False, 0.0
        min_volume = min(min_volume, volume)

    return True, min_volume


def calc_volatility(df: pl.DataFrame) -> float:
    """计算每日收益率的波动率（标准差）

    Args:
        df: 单个股票的数据，包含 close 列

    Returns:
        收益率标准差（波动率），保留两位小数
    """
    if len(df) < 2:
        return 0.0

    df = df.sort("trade_date")
    closes = df["close"].to_list()
    returns = []

    for i in range(1, len(closes)):
        if closes[i - 1] > 0:
            daily_return = (closes[i] / closes[i - 1]) - 1
            returns.append(daily_return)

    if len(returns) < 2:
        return 0.0

    import statistics
    return round(statistics.stdev(returns), 2)


def calc_ma_slope_and_r2(closes: list[float], ma_period: int = 10, slope_days: int = 5, r2_days: int = 10) -> tuple[float, float]:
    """计算均线斜率和决定系数

    Args:
        closes: 收盘价列表（按时间顺序）
        ma_period: 均线周期，默认10日
        slope_days: 计算斜率的天数，默认最后5天
        r2_days: 计算R²的天数，默认最后10天

    Returns:
        (最后slope_days天斜率, 最后r2_days天R²)
    """
    if len(closes) < ma_period + 1:
        return 0.0, 0.0

    ma_values = []
    for i in range(ma_period - 1, len(closes)):
        ma = sum(closes[i - ma_period + 1:i + 1]) / ma_period
        ma_values.append(ma)

    # 需要至少 ma_period + r2_days 个MA点
    if len(ma_values) < r2_days:
        return 0.0, 0.0

    # 取最后r2_days个MA点计算R²
    ma_for_r2 = ma_values[-r2_days:]
    x = np.arange(len(ma_for_r2))
    y = np.array(ma_for_r2)

    coeffs = np.polyfit(x, y, 1)

    y_pred = np.polyval(coeffs, x)
    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0.0

    # 计算最后slope_days天的斜率
    ma_for_slope = ma_values[-slope_days:]
    last_slope = (ma_for_slope[-1] - ma_for_slope[0]) / (slope_days - 1) if slope_days > 1 else 0.0

    return last_slope, r_squared


class Screener:
    """股票筛选器"""

    def __init__(self, cache_path: str = DEFAULT_CACHE_PATH):
        self.pro = ts.pro_api()
        self.cache_path = cache_path
        self.history_df = pl.DataFrame()
        self.stock_names = {}
        self.data_days = 0  # 数据天数

    def _load_data(self):
        """加载数据（从缓存或更新）"""
        self.history_df = update_cache(self.pro, self.cache_path)
        self.stock_names = fetch_stock_names(self.pro)

        if not self.history_df.is_empty():
            self.data_days = len(self.history_df['trade_date'].unique())
            logger.info(f"数据加载完成: {self.data_days} 天，{self.history_df['symbol'].n_unique()} 只股票")

    def _get_rsi_for_symbol(self, symbol: str) -> float:
        """获取某只股票的RSI(6)

        RSI需要至少60天数据才能准确计算（递归计算，早期数据不稳定）
        默认获取70天数据以确保RSI计算准确

        Args:
            symbol: 股票代码

        Returns:
            RSI值，如果数据不足返回0.0
        """
        symbol_df = self.history_df.filter(pl.col("symbol") == symbol)
        # 需要至少60天数据才计算RSI（默认获取70天以确保准确）
        if len(symbol_df) < 60:
            return 0.0

        symbol_df = symbol_df.sort("trade_date")
        closes = symbol_df["close"].to_list()

        return calc_rsi(closes, period=6)

    def _get_recent_rsi_series(self, symbol: str, days: int = 5) -> list[float]:
        """获取某只股票最近N天的RSI序列

        Args:
            symbol: 股票代码
            days: 最近天数，默认5天

        Returns:
            RSI序列列表，如果数据不足返回空列表
        """
        symbol_df = self.history_df.filter(pl.col("symbol") == symbol)
        if len(symbol_df) < 60:
            return []

        symbol_df = symbol_df.sort("trade_date")
        closes = symbol_df["close"].to_list()

        # 计算RSI序列
        rsi_series = []
        for i in range(len(closes) - 60 + 1):
            rsi = calc_rsi(closes[i:i+60], period=6)
            rsi_series.append(rsi)

        # 返回最近days天的RSI
        return rsi_series[-days:] if len(rsi_series) >= days else rsi_series

    def volume(self, log_level: str="INFO", dig: str=""):
        """筛选成交量放大且后续收阳线的股票

        筛选条件：
        - 存在某日成交量是之前5倍以上（t0日）
        - t0日之后都收阳线

        Args:
            log_level: 日志级别，默认INFO
            dig: 追踪指定股票代码的淘汰原因，如"000062.SZ"
        """
        logger.info("开始成交量放大筛选...")
        self._load_data()

        if self.history_df.is_empty():
            logger.error("未能获取历史数据")
            return

        # 获取最近10天的数据用于筛选
        recent_dates = self.history_df['trade_date'].unique().sort()[-10:]
        recent_df = self.history_df.filter(pl.col("trade_date").is_in(pl.lit(recent_dates).implode()))

        logger.info(f"使用最近10天数据进行筛选: {recent_dates[0]} ~ {recent_dates[-1]}")

        # 如果指定了dig，转换为大写并检查是否存在
        dig_symbol = dig.upper() if dig else ""
        dig_info = []

        results = []
        for symbol in recent_df["symbol"].unique():
            stock_name = self.stock_names.get(symbol, symbol)
            is_dig_target = (symbol == dig_symbol)

            if is_dig_target:
                dig_info.append(f"\n{'='*80}")
                dig_info.append(f"追踪股票: {symbol} ({stock_name})")
                dig_info.append(f"{'='*80}")

            # 过滤9开头的股票（北交所等）
            if symbol.startswith('9'):
                if is_dig_target:
                    dig_info.append("❌ 被淘汰: 9开头（北交所等）")
                continue

            # 过滤ST股票
            if stock_name and ('ST' in stock_name or '*ST' in stock_name):
                if is_dig_target:
                    dig_info.append("❌ 被淘汰: ST股票")
                continue

            symbol_df = recent_df.filter(pl.col("symbol") == symbol)

            has_spike, t0_date, ratio = check_volume_spike(symbol_df, symbol)

            if not has_spike or t0_date is None:
                if is_dig_target:
                    dig_info.append("❌ 被淘汰: 没有成交量放大（10天内没有成交量是之前5倍以上）")
                    # 输出最近几天的成交量数据用于调试
                    dig_info.append("\n最近10天成交量数据:")
                    for row in symbol_df.sort("trade_date").iter_rows(named=True):
                        dig_info.append(f"  {row['trade_date']}: volume={row['volume']:.2f}")
                continue

            if is_dig_target:
                dig_info.append(f"✓ 通过: 发现放量日 {t0_date}, 放量倍数={ratio:.2f}")

            # 过滤放量前一天是一字板的股票（涨幅>9%且价格波动<1%）
            df_before = symbol_df.filter(pl.col("trade_date") < t0_date)
            if not df_before.is_empty():
                df_before = df_before.sort("trade_date", descending=True)
                prev_row = df_before.row(0, named=True)
                prev_return = prev_row["close"] / prev_row["open"] - 1 if prev_row["open"] > 0 else 0
                price_change_pct = abs(prev_row["close"] - prev_row["open"]) / prev_row["open"] if prev_row["open"] > 0 else 0
                is_yiziban = prev_return > 0.09 and price_change_pct < 0.01
                if is_dig_target:
                    dig_info.append(f"放量前一天 ({prev_row['trade_date']}): 涨幅={prev_return*100:.2f}%, 价格波动={price_change_pct*100:.2f}%")
                if is_yiziban:
                    if is_dig_target:
                        dig_info.append("❌ 被淘汰: 放量前一天是一字板（涨幅>9%且价格波动<1%）")
                    continue
                elif is_dig_target:
                    dig_info.append("✓ 通过: 放量前一天不是一字板")

            # 计算t0日之后的阳线天数和最小成交量
            df_after = symbol_df.filter(pl.col("trade_date") > t0_date).sort("trade_date")
            up_days_count = 0

            for row in df_after.iter_rows(named=True):
                if row["close"] > row["open"]:
                    up_days_count += 1




            # RSI使用全量数据计算（默认70天以确保准确）
            rsi = self._get_rsi_for_symbol(symbol)

            if is_dig_target:
                dig_info.append(f"RSI-6={rsi:.2f}")

            # 过滤最后一天RSI小于60的股票（RSI为0表示数据不足，不淘汰）
            if 0 < rsi < 60:
                if is_dig_target:
                    dig_info.append("❌ 被淘汰: RSI-6 < 60")
                continue
            elif is_dig_target:
                if rsi == 0:
                    dig_info.append("✓ 通过: RSI数据不足，不淘汰")
                else:
                    dig_info.append("✓ 通过: RSI-6 >= 60")

            # 获取放量当天的换手率
            t0_row = symbol_df.filter(pl.col("trade_date") == t0_date)
            turnover = t0_row["turnover"].to_list()[0] if not t0_row.is_empty() else 0.0

            if is_dig_target:
                dig_info.append(f"放量日换手率={turnover:.2f}%")

            # 过滤放量当天换手率不足5%的股票
            if turnover < 5:
                if is_dig_target:
                    dig_info.append("❌ 被淘汰: 放量日换手率 < 5%")
                continue
            elif is_dig_target:
                dig_info.append("✓ 通过: 放量日换手率 >= 5%")

            # 计算从放量日到今天的交易日数
            all_dates = self.history_df['trade_date'].unique().sort()
            trading_days_count = len([d for d in all_dates if d >= t0_date])

            if is_dig_target:
                dig_info.append(f"✅ 最终入选: 距今{trading_days_count}个交易日")
                dig_info.append(f"{'='*80}\n")

            result = {
                "symbol": symbol,
                "name": self.stock_names.get(symbol, "未知"),
                "t0_date": t0_date.strftime("%Y-%m-%d") if hasattr(t0_date, 'strftime') else str(t0_date)[:10],
                "trading_days": trading_days_count,
                "volume_ratio": round(ratio, 2),
                "up_days": up_days_count,
                "turnover": f"{turnover:.1f}%",
                "rsi_6": rsi,
            }

            results.append(result)

        # 输出追踪信息
        if dig_info:
            print("\n".join(dig_info))

        print("\n" + "=" * 80)
        print("成交量放大筛选结果")
        print("=" * 80)

        if not results:
            print("没有符合条件的股票")
        else:
            print(f"共找到 {len(results)} 只符合条件的股票:")
            print(f"(数据天数: {self.data_days}天，RSI-6基于全量数据计算)")
            print()

            # 使用 tabulate 打印表格，按换手率从大到小排序
            df = pl.DataFrame(results).to_pandas()
            df = df.sort_values("turnover", ascending=False)
            headers = {
                "symbol": "代码",
                "name": "名称",
                "t0_date": "放量日",
                "trading_days": "距今",
                "up_days": "收阳天数",
                "volume_ratio": "量比",
                "turnover": "换手率",
                "rsi_6": "RSI",
            }
            # 调整列顺序
            column_order = ["代码", "名称", "放量日", "距今", "收阳天数", "量比", "换手率", "RSI"]
            df.columns = [headers.get(c, c) for c in df.columns]
            df = df[column_order]
            print(tabulate(df.values.tolist(), headers=df.columns.tolist(), tablefmt="simple"))

            # 保存筛选结果到CSV文件
            if not self.history_df.is_empty():
                last_date = self.history_df['trade_date'].max()
                # 准备CSV数据
                df_csv = df.copy()
                df_csv['命令'] = '放量'
                # 设置索引为筛选日
                if isinstance(last_date, datetime.date):
                    index_date = last_date.strftime("%Y-%m-%d")
                else:
                    index_date = str(last_date)[:10]
                df_csv['筛选日'] = index_date
                df_csv = df_csv.set_index('筛选日')

                # 保存到CSV (使用utf-8-sig以支持Excel打开)
                result_file = SCREEN_DIR / "result.csv"
                # 如果文件存在则读取并合并去重
                if result_file.exists() and result_file.stat().st_size > 0:
                    try:
                        existing_df = pd.read_csv(result_file, encoding='utf-8-sig')
                        # 合并数据
                        combined_df = pd.concat([existing_df, df_csv.reset_index()], ignore_index=True)
                        # 按筛选日和代码去重，保留最后出现的记录
                        combined_df = combined_df.drop_duplicates(subset=['筛选日', '代码'], keep='last')
                        # 重新设置索引
                        combined_df = combined_df.set_index('筛选日')
                        combined_df.to_csv(result_file, encoding='utf-8-sig')
                    except Exception as e:
                        logger.warning(f"读取或合并CSV失败，直接保存新数据: {e}")
                        df_csv.to_csv(result_file, encoding='utf-8-sig')
                else:
                    df_csv.to_csv(result_file, encoding='utf-8-sig')

                # 同时保存文本格式用于查看（与终端输出一致）
                if isinstance(last_date, datetime.date):
                    date_str = last_date.strftime("%y%m%d")
                else:
                    date_str = str(last_date)[:6]
                txt_file = SCREEN_DIR / f"screen-volume-{date_str}.txt"
                with open(txt_file, 'w', encoding='utf-8', newline='\r\n') as f:
                    f.write(tabulate(df.values.tolist(), headers=df.columns.tolist(), tablefmt="simple"))

                # 保存result.txt（覆盖模式，仅股票名，Windows换行）
                result_txt_file = SCREEN_DIR / "result.txt"
                with open(result_txt_file, 'w', encoding='utf-8', newline='\r\n') as f:
                    for name in df['名称']:
                        f.write(f"{name}\r\n")
                logger.info(f"结果列表已保存到: {result_txt_file}")

                print("=" * 80)
                logger.info(f"文本结果已保存到: {txt_file}")

    def slope(self):
        """计算10日均线斜率和决定系数

        取最近20天数据，计算10日均线，
        按最后5天斜率由高到低排序，过滤掉最后10天决定系数低于75%分位的，
        过滤近3天RSI超过90的（避免超买回调），
        最多输出前10支。
        """
        logger.info("开始均线斜率筛选...")
        self._load_data()

        if self.history_df.is_empty():
            logger.error("未能获取历史数据")
            return

        # 获取最近20天的数据用于计算（10日均线+10天R²需要至少20天数据）
        recent_dates = self.history_df['trade_date'].unique().sort()[-20:]
        recent_df = self.history_df.filter(pl.col("trade_date").is_in(pl.lit(recent_dates).implode()))

        logger.info(f"使用最近20天数据进行计算: {recent_dates[0]} ~ {recent_dates[-1]}")

        results = []
        for symbol in recent_df["symbol"].unique():
            # 过滤9开头的股票（北交所等）
            if symbol.startswith('9'):
                continue

            symbol_df = recent_df.filter(pl.col("symbol") == symbol)
            symbol_df = symbol_df.sort("trade_date")
            closes = symbol_df["close"].to_list()

            last_slope, r_squared = calc_ma_slope_and_r2(closes, ma_period=10, slope_days=5, r2_days=10)

            if last_slope != 0.0 or r_squared != 0.0:
                # RSI使用全量数据计算（默认70天以确保准确）
                stock_name = self.stock_names.get(symbol, symbol)

                rsi = self._get_rsi_for_symbol(symbol)

                # 过滤最后一天RSI小于50的股票
                if rsi < 50:
                    logger.debug(f"{stock_name}({symbol}) RSI={rsi:.2f} < 50，跳过")
                    continue

                # 检查近3天RSI是否有超过90的（过滤超买后回调的股票）
                recent_rsi_series = self._get_recent_rsi_series(symbol, days=3)
                has_extreme_rsi = any(r > 90 for r in recent_rsi_series if r > 0)

                if has_extreme_rsi:
                    logger.debug(f"{stock_name}({symbol}) 近3天有RSI超过90，跳过")
                    continue

                result = {
                    "symbol": symbol,
                    "name": self.stock_names.get(symbol, "未知"),
                    "slope": round(last_slope, 2),
                    "r_squared": round(r_squared, 2),
                    "rsi_6": rsi,
                }

                results.append(result)

        if not results:
            print("没有符合条件的股票")
            return

        results.sort(key=lambda x: x["slope"], reverse=True)

        r2_values = [r["r_squared"] for r in results]
        r2_75th = np.percentile(r2_values, 75)

        logger.info(f"R² 75%分位: {r2_75th:.4f}")

        filtered_results = [r for r in results if r["r_squared"] >= r2_75th]
        top_10 = filtered_results[:10]

        print("\n" + "=" * 80)
        print("均线斜率筛选结果（10日均线，10日R²>=75%分位，5日斜率，近3天RSI<=90，前10支）")
        print("=" * 80)

        if not top_10:
            print("没有符合条件的股票")
        else:
            print(f"共找到 {len(top_10)} 只符合条件的股票（R²阈值: {r2_75th:.4f}）:")
            print(f"(数据天数: {self.data_days}天，RSI-6基于全量数据计算)")
            print()

            # 使用 tabulate 打印表格
            df = pl.DataFrame(top_10).to_pandas()
            headers = {
                "symbol": "代码",
                "name": "名称",
                "slope": "斜率",
                "r_squared": "R²",
                "rsi_6": "RSI(6)",
            }
            df.columns = [headers.get(c, c) for c in df.columns]
            print(tabulate(df.values.tolist(), headers=df.columns.tolist(), tablefmt="simple"))

            # 保存筛选结果到CSV文件
            if not self.history_df.is_empty():
                last_date = self.history_df['trade_date'].max()
                # 准备CSV数据
                df_csv = df.copy()
                df_csv['命令'] = '均线'
                # 设置索引为筛选日
                if isinstance(last_date, datetime.date):
                    index_date = last_date.strftime("%Y-%m-%d")
                else:
                    index_date = str(last_date)[:10]
                df_csv['筛选日'] = index_date
                df_csv = df_csv.set_index('筛选日')

                # 保存到CSV (使用utf-8-sig以支持Excel打开)
                result_file = SCREEN_DIR / "result.csv"
                # 如果文件存在则读取并合并去重
                if result_file.exists() and result_file.stat().st_size > 0:
                    try:
                        existing_df = pd.read_csv(result_file, encoding='utf-8-sig')
                        # 合并数据
                        combined_df = pd.concat([existing_df, df_csv.reset_index()], ignore_index=True)
                        # 按筛选日和代码去重，保留最后出现的记录
                        combined_df = combined_df.drop_duplicates(subset=['筛选日', '代码'], keep='last')
                        # 重新设置索引
                        combined_df = combined_df.set_index('筛选日')
                        combined_df.to_csv(result_file, encoding='utf-8-sig')
                    except Exception as e:
                        logger.warning(f"读取或合并CSV失败，直接保存新数据: {e}")
                        df_csv.to_csv(result_file, encoding='utf-8-sig')
                else:
                    df_csv.to_csv(result_file, encoding='utf-8-sig')
                logger.info(f"筛选结果已保存到: {result_file}")

                # 同时保存文本格式用于查看（与终端输出一致）
                if isinstance(last_date, datetime.date):
                    date_str = last_date.strftime("%y%m%d")
                else:
                    date_str = str(last_date)[:6]
                txt_file = SCREEN_DIR / f"screen-slope-{date_str}.txt"
                with open(txt_file, 'w', encoding='utf-8', newline='\r\n') as f:
                    f.write(tabulate(df.values.tolist(), headers=df.columns.tolist(), tablefmt="simple"))
                logger.info(f"文本结果已保存到: {txt_file}")

                # 保存result.txt（覆盖模式，仅股票名，Windows换行）
                result_txt_file = SCREEN_DIR / "result.txt"
                with open(result_txt_file, 'w', encoding='utf-8', newline='\r\n') as f:
                    for name in df['名称']:
                        f.write(f"{name}\r\n")
                logger.info(f"结果列表已保存到: {result_txt_file}")

        print("=" * 80)


def main():
    """主函数入口"""
    fire.Fire(Screener)


if __name__ == "__main__":
    main()
