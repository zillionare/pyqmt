"""实时行情服务

支持两种模式:
1. qmt: 直接从本地 QMT 获取全推数据（Windows 环境推荐）
2. none: 不使用实时行情（仅使用历史数据）
"""

import datetime
import threading
import time
from typing import Any, Dict, Optional

import polars as pl
from loguru import logger

from pyqmt.config import cfg
from pyqmt.core.enums import Topics
from pyqmt.core.message import msg_hub
from pyqmt.core.scheduler import scheduler
from pyqmt.core.singleton import singleton
from pyqmt.data.fetchers.tushare import fetch_limit_price


@singleton
class LiveQuote:
    """实时行情服务

    支持从 QMT 直连获取全推数据，并维护一个进程内字典缓存。
    同时维护实时分钟线和日线数据，用于策略计算和图表展示。
    """

    def __init__(self):
        # 最新行情缓存 {symbol: {price, open, high, low, ...}}
        self._cache: Dict[str, Dict[str, Any]] = {}

        # 涨跌停价格缓存 {symbol: {up_limit, down_limit}}
        self._limits: Dict[str, Dict[str, float]] = {}
        self._limit_date: datetime.date | None = None

        # 复权因子缓存 {symbol: adjust_factor}
        self._adj_factors: Dict[str, float] = {}
        self._adj_factor_date: datetime.date | None = None

        # 实时 K 线数据 - 使用 Polars DataFrame 存储
        # 分钟线: 当前交易日的分钟数据
        self._minute_bars: pl.DataFrame = pl.DataFrame(
            schema={
                "symbol": pl.Utf8,
                "frame": pl.Datetime,
                "open": pl.Float64,
                "high": pl.Float64,
                "low": pl.Float64,
                "close": pl.Float64,
                "volume": pl.Int64,
                "amount": pl.Float64,
            }
        )
        self._min30_bars: pl.DataFrame = pl.DataFrame(
            schema={
                "symbol": pl.Utf8,
                "frame": pl.Datetime,
                "open": pl.Float64,
                "high": pl.Float64,
                "low": pl.Float64,
                "close": pl.Float64,
                "volume": pl.Int64,
                "amount": pl.Float64,
            }
        )

        # 日线: 当前交易日的日线数据（从开盘累计，包含 limit 和 adjust）
        # 在获取 stock limit 和 factor 后预生成框架，tick 数据到达时更新
        self._daily_bars: pl.DataFrame = pl.DataFrame(
            schema={
                "symbol": pl.Utf8,
                "frame": pl.Date,
                "open": pl.Float64,
                "high": pl.Float64,
                "low": pl.Float64,
                "close": pl.Float64,
                "volume": pl.Int64,
                "amount": pl.Float64,
                "up_limit": pl.Float64,
                "down_limit": pl.Float64,
                "adjust": pl.Float64,
            }
        )

        self._is_running = False
        self._mode: str | None = None

        # 当前交易日期
        self._trade_date: datetime.date | None = None

    def start(self):
        """启动订阅

        根据配置 mode 选择数据源:
        - qmt: 从本地 QMT 订阅全推数据
        - none: 不使用实时行情，仅启动涨跌停刷新
        """
        if self._is_running:
            return

        # 无论何种模式，都启动涨跌停限制的定时刷新
        self._start_limit_schedule()

        self._mode = cfg.livequote.mode

        if self._mode == "qmt":
            self._start_qmt_subscription()
        elif self._mode == "none":
            logger.info("LiveQuote running in none mode, no real-time quotes")
        else:
            logger.warning(f"Unknown livequote mode: {self._mode}, using none mode")

        self._is_running = True
        logger.info("LiveQuote service started in {} mode", self._mode)

    def stop(self):
        """停止服务"""
        self._is_running = False
        logger.info("LiveQuote service stopped")

    def _start_qmt_subscription(self):
        """从 QMT 订阅全推数据（Windows 本地模式）"""
        # 延迟导入 xtquant（仅在 Windows 上使用）
        from xtquant import xtdata as xt

        try:
            # 获取配置的市场列表，默认为 SH, SZ, BJ
            markets = getattr(cfg.livequote.qmt, "markets", ["SH", "SZ", "BJ"])

            # 订阅全量行情
            xt.subscribe_whole_quote(markets, self._on_qmt_quote)
            logger.info(f"Subscribed to QMT whole quote for markets: {markets}")

            # 启动 QMT 数据刷新循环（在后台线程中运行）
            def qmt_refresh_loop():
                """QMT 需要定期调用 run 方法来处理数据"""
                while self._is_running:
                    try:
                        xt.run()
                        time.sleep(0.1)  # 100ms 刷新间隔
                    except Exception as e:
                        logger.error(f"QMT refresh error: {e}")
                        time.sleep(1)

            thread = threading.Thread(
                target=qmt_refresh_loop, name="QMTQuoteRefresh", daemon=True
            )
            thread.start()
            logger.info("QMT quote refresh loop started")

        except Exception as e:
            logger.exception(f"Failed to start QMT subscription: {e}")

    def _on_qmt_quote(self, data: Dict[str, Any]):
        """处理来自 QMT 的全推行情数据

        使用 Polars 进行高性能数据转换和 K 线合成，完全避免 Python 层面的循环。
        QMT 返回的数据格式: {code: {'lastPrice': 10.5, 'open': 10.0, ...}}
        """
        try:
            if not data:
                return

            # 使用列表推导式进行高效转换（比 pandas 快 5 倍）
            # 1. 构造 Polars DataFrame
            df = pl.DataFrame(
                [
                    {
                        "symbol": code,
                        "price": quote.get("lastPrice", 0.0),
                        "open": quote.get("open", 0.0),
                        "high": quote.get("high", 0.0),
                        "low": quote.get("low", 0.0),
                        "close": quote.get("lastClose", 0.0),
                        "volume": quote.get("volume", 0),
                        "amount": quote.get("amount", 0.0),
                        "bid1": quote.get("bid1", 0.0),
                        "ask1": quote.get("ask1", 0.0),
                        "bid1_volume": quote.get("bid1Volume", 0),
                        "ask1_volume": quote.get("ask1Volume", 0),
                        "time": quote.get("time", 0),
                    }
                    for code, quote in data.items()
                ]
            )

            # 2. 更新缓存 - 使用 Polars 的 to_dicts() 批量转换
            cache_data = df.select([
                "symbol", "price", "open", "high", "low", "close",
                "volume", "amount", "bid1", "ask1", "bid1_volume", "ask1_volume", "time"
            ]).to_dicts()
            # 转换为以 symbol 为 key 的 dict（使用 dict comprehension  unavoidable）
            self._cache.update({item["symbol"]: item for item in cache_data})

            # 3. 合成 K 线数据
            self._merge_bars(df)

            # 4. 广播通知
            msg_hub.publish(Topics.QUOTES_ALL.value, self._cache)

            # 5. 记录日志（每100次推送）
            if not hasattr(self, "_qmt_quote_count"):
                self._qmt_quote_count = 0
            self._qmt_quote_count += 1

            if self._qmt_quote_count <= 5 or self._qmt_quote_count % 100 == 0:
                sample = cache_data[0] if cache_data else None
                logger.info(
                    "Received QMT quote #{}: {} stocks, sample: {} = {}",
                    self._qmt_quote_count,
                    len(df),
                    sample.get("symbol") if sample else None,
                    sample.get("price") if sample else None,
                )

        except Exception as e:
            logger.error("Error processing QMT quote: {}", e)

    def _merge_bars(self, df: pl.DataFrame):
        """合成分钟线和日线数据

        正确的逻辑：
        1. 分钟线：同一分钟内的 tick 合并（open=首条, high=max, low=min, close=最新, volume/amount=累计）
        2. 日线：从最新 tick 直接更新，不从分钟线重采样

        Args:
            df: 包含最新行情的 Polars DataFrame
        """
        try:
            now = datetime.datetime.now()
            today = now.date()

            # 检查是否是新的交易日
            if self._trade_date != today:
                self._trade_date = today
                self._minute_bars = self._minute_bars.clear()
                self._min30_bars = self._min30_bars.clear()
                self._daily_bars = self._daily_bars.clear()
                logger.info(f"New trade date: {today}, cleared bars cache")

            # 计算当前分钟（去掉秒和微秒）
            current_minute = now.replace(second=0, microsecond=0)

            # 1. 合成分钟线
            # 检查是否是同一分钟
            if len(self._minute_bars) > 0:
                # 获取当前分钟已有的数据
                existing = self._minute_bars.filter(
                    (pl.col("frame") == current_minute)
                )
                
                if len(existing) > 0:
                    # 同一分钟：需要合并（open保持，high/low更新，close更新，volume/amount累计）
                    # 先删除当前分钟的旧数据
                    self._minute_bars = self._minute_bars.filter(
                        pl.col("frame") != current_minute
                    )
                    
                    # 合并逻辑：与现有数据按 symbol 合并
                    merged = df.join(existing, on="symbol", how="outer", suffix="_old")
                    minute_df = merged.select([
                        pl.col("symbol"),
                        pl.lit(current_minute).alias("frame"),
                        # open: 如果有旧数据用旧的，否则用新的
                        pl.when(pl.col("open_old").is_not_null())
                        .then(pl.col("open_old"))
                        .otherwise(pl.col("open"))
                        .alias("open"),
                        # high: 取最大值
                        pl.max_horizontal("high", "high_old").alias("high"),
                        # low: 取最小值（注意处理 null）
                        pl.when(pl.col("low_old").is_not_null())
                        .then(pl.min_horizontal("low", "low_old"))
                        .otherwise(pl.col("low"))
                        .alias("low"),
                        # close: 用最新的
                        pl.col("price").alias("close"),
                        # volume: 累计
                        (pl.col("volume").fill_null(0) + pl.col("volume_old").fill_null(0)).alias("volume"),
                        # amount: 累计
                        (pl.col("amount").fill_null(0) + pl.col("amount_old").fill_null(0)).alias("amount"),
                    ])
                else:
                    # 新分钟：直接使用 tick 数据
                    minute_df = df.with_columns(
                        pl.lit(current_minute).alias("frame")
                    ).select([
                        "symbol",
                        "frame",
                        pl.col("open").alias("open"),
                        pl.col("high").alias("high"),
                        pl.col("low").alias("low"),
                        pl.col("price").alias("close"),
                        pl.col("volume").cast(pl.Int64).alias("volume"),
                        pl.col("amount").cast(pl.Float64).alias("amount"),
                    ])
            else:
                # 首次数据
                minute_df = df.with_columns(
                    pl.lit(current_minute).alias("frame")
                ).select([
                    "symbol",
                    "frame",
                    pl.col("open").alias("open"),
                    pl.col("high").alias("high"),
                    pl.col("low").alias("low"),
                    pl.col("price").alias("close"),
                    pl.col("volume").cast(pl.Int64).alias("volume"),
                    pl.col("amount").cast(pl.Float64).alias("amount"),
                ])

            # 追加到分钟线缓存
            self._minute_bars = self._minute_bars.vstack(minute_df).sort(["symbol", "frame"])
            msg_hub.publish(Topics.BARS_1M.value, minute_df.to_dicts())

            current_30m = now.replace(
                minute=(now.minute // 30) * 30,
                second=0,
                microsecond=0,
            )
            next_30m = current_30m + datetime.timedelta(minutes=30)
            bars_30m = (
                self._minute_bars
                .filter((pl.col("frame") >= current_30m) & (pl.col("frame") < next_30m))
                .sort(["symbol", "frame"])
                .group_by("symbol")
                .agg([
                    pl.col("open").first().alias("open"),
                    pl.col("high").max().alias("high"),
                    pl.col("low").min().alias("low"),
                    pl.col("close").last().alias("close"),
                    pl.col("volume").sum().cast(pl.Int64).alias("volume"),
                    pl.col("amount").sum().cast(pl.Float64).alias("amount"),
                ])
                .with_columns(pl.lit(current_30m).alias("frame"))
                .select([
                    "symbol",
                    "frame",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "amount",
                ])
            )
            if len(bars_30m) > 0:
                self._min30_bars = self._min30_bars.filter(pl.col("frame") != current_30m)
                self._min30_bars = self._min30_bars.vstack(bars_30m).sort(["symbol", "frame"])
                msg_hub.publish(Topics.BARS_30M.value, bars_30m.to_dicts())

            # 2. 合成日线 - 更新预生成的框架中的价格数据
            # 将最新 tick 数据转换为更新格式
            tick_update = df.select([
                "symbol",
                pl.col("open").alias("open_new"),
                pl.col("high").alias("high_new"),
                pl.col("low").alias("low_new"),
                pl.col("price").alias("close_new"),
                pl.col("volume").cast(pl.Int64).alias("volume_new"),
                pl.col("amount").cast(pl.Float64).alias("amount_new"),
            ])

            if len(self._daily_bars) == 0:
                # 如果没有预生成框架，创建新的（不含 limit/adjust）
                self._daily_bars = tick_update.with_columns(
                    pl.lit(today).alias("frame"),
                    pl.lit(0.0).alias("up_limit"),
                    pl.lit(0.0).alias("down_limit"),
                    pl.lit(1.0).alias("adjust"),
                ).select([
                    "symbol", "frame", "open_new", "high_new", "low_new", "close_new",
                    "volume_new", "amount_new", "up_limit", "down_limit", "adjust"
                ]).rename({
                    "open_new": "open",
                    "high_new": "high",
                    "low_new": "low",
                    "close_new": "close",
                    "volume_new": "volume",
                    "amount_new": "amount",
                })
            else:
                # 更新预生成框架中的价格数据（使用 join 更新）
                # 先删除这些 symbol 的旧数据
                existing_symbols = tick_update["symbol"].to_list()
                framework = self._daily_bars.filter(pl.col("symbol").is_in(existing_symbols))
                self._daily_bars = self._daily_bars.filter(
                    ~pl.col("symbol").is_in(existing_symbols)
                )

                # 合并 tick 数据和框架数据
                merged = tick_update.join(
                    framework.select(["symbol", "up_limit", "down_limit", "adjust"]),
                    on="symbol",
                    how="left"
                ).with_columns([
                    pl.col("up_limit").fill_null(0.0),
                    pl.col("down_limit").fill_null(0.0),
                    pl.col("adjust").fill_null(1.0),
                ])

                # 重命名列并合并回 daily_bars
                new_rows = merged.select([
                    "symbol",
                    pl.lit(today).alias("frame"),
                    pl.col("open_new").alias("open"),
                    pl.col("high_new").alias("high"),
                    pl.col("low_new").alias("low"),
                    pl.col("close_new").alias("close"),
                    pl.col("volume_new").alias("volume"),
                    pl.col("amount_new").alias("amount"),
                    "up_limit",
                    "down_limit",
                    "adjust",
                ])

                self._daily_bars = self._daily_bars.vstack(new_rows).sort("symbol")
            msg_hub.publish(Topics.BARS_1D.value, self._daily_bars.to_dicts())

        except Exception as e:
            logger.error("Error merging bars: {}", e)

    def _start_limit_schedule(self):
        """启动定时任务

        包括：
        1. 涨跌停价格刷新（每日 9:00）
        2. 复权因子获取（每日 9:20，带重试机制）
        3. 日线数据获取（每日 16:00）
        4. 清空 K 线缓存（仅在非交易时间，且 tushare 获取成功后）
        """
        # 仅在交易日 9:00 之后立即刷新一次
        now = datetime.datetime.now()
        if 9 <= now.hour < 15:  # 简单判断交易时间段
            self._refresh_limits()

        # 1. 涨跌停价格刷新任务
        scheduler.add_job(
            self._refresh_limits,
            "cron",
            hour=9,
            minute=0,
            name="livequote.limit.refresh",
        )

        # 2. 复权因子获取任务 - 9:20 开始获取，带重试机制
        scheduler.add_job(
            self._fetch_adj_factors_with_retry,
            "cron",
            hour=9,
            minute=20,
            name="livequote.adj_factor.fetch",
        )

        # 3. 日线数据获取任务 - 收盘后立即从 tushare 获取（16:00）
        scheduler.add_job(
            self._fetch_daily_bars,
            "cron",
            hour=16,
            minute=0,
            name="livequote.daily.fetch",
        )

    def _is_trading_time(self) -> bool:
        """检查当前是否处于交易时间

        交易时间：9:00 - 15:30
        """
        now = datetime.datetime.now()
        return 9 <= now.hour < 15 or (now.hour == 15 and now.minute <= 30)

    def _clear_bars_cache(self, force: bool = False):
        """清空 K 线缓存

        只能在非交易时间清空！

        Args:
            force: 是否强制清空（忽略交易时间检查，用于测试）
        """
        try:
            # 安全检查：交易时间禁止清空
            if not force and self._is_trading_time():
                logger.warning("Cannot clear bars cache during trading time!")
                return

            today = datetime.date.today()
            if self._trade_date != today:
                self._trade_date = today
                self._minute_bars = self._minute_bars.clear()
                self._min30_bars = self._min30_bars.clear()
                self._daily_bars = self._daily_bars.clear()
                logger.info(f"Bars cache cleared for new trade date: {today}")
        except Exception as e:
            logger.error(f"Error clearing bars cache: {e}")

    def _fetch_daily_bars(self):
        """从 tushare 获取当天日线数据

        在每日收盘后（16:00）执行，获取当天日线数据。
        成功获取后，立即清空实时 K 线缓存（仅在非交易时间）。

        注意：
        - 如果获取持续到第二天交易时段，则不会清空缓存
        - 这是为了防止在交易时段误清缓存
        """
        try:
            from pyqmt.data.fetchers.tushare import fetch_bars

            today = datetime.date.today()
            logger.info(f"Fetching daily bars for {today} from tushare...")

            df, errors = fetch_bars(today)

            if errors:
                logger.warning(f"Errors during fetching daily bars: {errors}")

            if df is not None and not df.empty:
                logger.info(f"Successfully fetched daily bars: {len(df)} records")

                # 保存到数据库或缓存（可选）
                # TODO: 如果需要持久化，可以在这里调用 DAL

                # 立即清空缓存（仅在非交易时间）
                self._clear_bars_cache()
            else:
                logger.warning(f"No daily bars data for {today}, keeping cache")

        except Exception as e:
            logger.error(f"Error fetching daily bars: {e}, keeping cache")

    def _refresh_limits(self, dt: datetime.date | None = None):
        """从 Tushare 刷新涨跌停价格"""
        import pandas as pd

        dt = dt or datetime.date.today()
        df, _ = fetch_limit_price(dt)
        if df is None or df.empty:
            return
        if "asset" not in df.columns and "ts_code" in df.columns:
            df = df.rename(columns={"ts_code": "asset"})
        if "asset" not in df.columns:
            return
        self._limit_date = dt

        # 优化：使用向量化操作替代循环
        df = df[df["asset"].notna() & (df["asset"] != "")]

        for col in ["up_limit", "down_limit"]:
            if col not in df.columns:
                df[col] = 0.0
            else:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

        df["asset"] = df["asset"].astype(str)
        self._limits.update(
            df.set_index("asset")[["up_limit", "down_limit"]].to_dict("index")
        )  # type: ignore

    def _fetch_adj_factors_with_retry(self):
        """获取当天复权因子（带重试机制）

        在 9:20 开始获取，如果返回结果不足当天股票列表数的 50%，
        持续每 30 秒调用一次，直到超过 90% 后返回。

        获取成功后，预生成 _daily_bars 框架（包含 limit 和 adjust）。
        """
        try:
            import pandas as pd
            import tushare as ts

            today = datetime.date.today()
            logger.info(f"Fetching adj factors for {today} from tushare...")

            pro = ts.pro_api()

            # 首先获取当天股票列表（用于计算覆盖率）
            stock_list = pro.stock_basic(exchange='', list_status='L')
            if stock_list is None or stock_list.empty:
                logger.warning("Failed to get stock list, cannot calculate coverage")
                return

            total_stocks = len(stock_list)
            logger.info(f"Total stocks in market: {total_stocks}")

            # 重试获取复权因子
            max_retries = 60  # 最多重试 60 次（30 分钟）
            retry_interval = 30  # 每 30 秒重试一次

            for attempt in range(max_retries):
                try:
                    # 获取当天复权因子
                    df = pro.adj_factor(trade_date=today.strftime('%Y%m%d'))

                    if df is not None and not df.empty:
                        # 计算覆盖率
                        coverage = len(df) / total_stocks
                        logger.info(f"Attempt {attempt + 1}: Got {len(df)} adj factors, "
                                  f"coverage: {coverage:.1%}")

                        # 如果覆盖率超过 90%，保存并退出
                        if coverage >= 0.9:
                            # 缓存复权因子
                            self._adj_factors = df.set_index('ts_code')['adj_factor'].to_dict()
                            self._adj_factor_date = today
                            logger.info(f"Successfully cached adj factors for {len(df)} stocks")

                            # 预生成 _daily_bars 框架
                            self._init_daily_bars_framework()
                            return

                        # 如果覆盖率超过 50%，继续等待更多数据
                        if coverage >= 0.5:
                            logger.info(f"Coverage >= 50%, waiting for more data...")
                        else:
                            logger.warning(f"Coverage < 50%, will retry...")
                    else:
                        logger.warning(f"Attempt {attempt + 1}: No adj factor data")

                except Exception as e:
                    logger.error(f"Attempt {attempt + 1}: Error fetching adj factors: {e}")

                # 等待后重试
                if attempt < max_retries - 1:
                    time.sleep(retry_interval)

            logger.error(f"Failed to get sufficient adj factors after {max_retries} attempts")

        except Exception as e:
            logger.error(f"Error in _fetch_adj_factors_with_retry: {e}")

    def _init_daily_bars_framework(self):
        """预生成 _daily_bars 框架

        在获取 stock limit 和 adj factor 后调用，
        生成包含 symbol, frame, up_limit, down_limit, adjust 的框架，
        其它价格列留空，待 tick 数据到达时更新。
        """
        try:
            today = datetime.date.today()

            # 构建基础数据列表
            data_rows = []
            for symbol in self._limits.keys():
                limit = self._limits.get(symbol, {})
                adj_factor = self._adj_factors.get(symbol, 1.0)

                data_rows.append({
                    "symbol": symbol,
                    "frame": today,
                    "open": 0.0,
                    "high": 0.0,
                    "low": 0.0,
                    "close": 0.0,
                    "volume": 0,
                    "amount": 0.0,
                    "up_limit": limit.get("up_limit", 0.0),
                    "down_limit": limit.get("down_limit", 0.0),
                    "adjust": adj_factor,
                })

            if data_rows:
                self._daily_bars = pl.DataFrame(data_rows)
                logger.info(f"Initialized daily bars framework with {len(data_rows)} stocks")
            else:
                logger.warning("No limit data available, cannot init daily bars framework")

        except Exception as e:
            logger.error(f"Error initializing daily bars framework: {e}")

    def get_quote(self, asset: str) -> Optional[Dict[str, Any]]:
        """获取指定资产的最新行情字典"""
        return self._cache.get(asset)

    def get_price_limits(self, asset: str) -> tuple[float, float]:
        """获取指定资产的涨跌停价格

        Returns:
            (down_limit, up_limit) 元组
        """
        limits = self._limits.get(asset)
        if not limits:
            return 0.0, 0.0
        return limits.get("down_limit", 0.0), limits.get("up_limit", 0.0)

    def get_limit(self, asset: str) -> Optional[Dict[str, float]]:
        """获取指定资产的完整涨跌停信息"""
        limits = self._limits.get(asset)
        if not limits:
            return None
        return limits.copy()

    def get_minute_bars(self, symbol: str) -> pl.DataFrame:
        """获取指定股票的分钟线数据

        Args:
            symbol: 股票代码，如 "000001.SZ"

        Returns:
            Polars DataFrame 包含分钟线数据
        """
        return self._minute_bars.filter(pl.col("symbol") == symbol)

    def get_daily_bar(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取指定股票的日线数据

        Args:
            symbol: 股票代码，如 "000001.SZ"

        Returns:
            日线数据字典，包含 open, high, low, close, volume, amount
        """
        df = self._daily_bars.filter(pl.col("symbol") == symbol)
        if len(df) == 0:
            return None
        row = df[0].to_dicts()[0]
        return row

    def get_daily_bars_with_history(
        self,
        symbol: str,
        n_days: int = 20,
        bar_dal=None,
    ) -> pl.DataFrame:
        """获取包含历史数据的日线（历史+实时合并）

        策略在盘中需要获取过去 N 天的日线（包括当天），使用此方法。
        该方法从数据库获取历史日线，并与实时缓存的当天日线合并。
        当天数据包含 up_limit, down_limit 和 adjust（复权因子）列。

        Args:
            symbol: 股票代码，如 "000001.SZ"
            n_days: 需要获取的天数（包括当天），默认 20 天
            bar_dal: BarDAL 实例，用于查询历史数据。如果为 None，则只返回实时数据

        Returns:
            Polars DataFrame，包含历史+当天的日线数据
            列: dt, symbol, open, high, low, close, volume, amount, up_limit, down_limit, adjust
            注：历史数据的 up_limit, down_limit, adjust 为 null

        Example:
            >>> df = live_quote.get_daily_bars_with_history("000001.SZ", n_days=20)
            >>> print(len(df))  # 最多 20 条（包括当天）
            >>> print(df.select(["dt", "close", "adjust"]))  # 查看收盘价和复权因子
        """
        try:
            today = datetime.date.today()
            # 计算起始日期（多取几天确保有足够数据）
            start_date = today - datetime.timedelta(days=n_days + 5)

            # 1. 获取历史数据（从数据库）
            history_df = pl.DataFrame()
            if bar_dal is not None:
                try:
                    history_df = bar_dal.get_stock_bars(
                        symbol=symbol,
                        start=start_date,
                        end=today - datetime.timedelta(days=1),  # 到昨天
                        freq="day",
                    )
                    # 只取最近 n_days-1 天（留一个位置给今天）
                    if len(history_df) > n_days - 1:
                        history_df = history_df.tail(n_days - 1)

                    # 历史数据添加空的 limit 和 adjust 列
                    if len(history_df) > 0:
                        history_df = history_df.with_columns([
                            pl.lit(None).alias("up_limit"),
                            pl.lit(None).alias("down_limit"),
                            pl.lit(None).alias("adjust"),
                        ])
                except Exception as e:
                    logger.warning(f"Failed to get history bars for {symbol}: {e}")

            # 2. 获取当天实时数据（从缓存）
            today_df = self._daily_bars.filter(pl.col("symbol") == symbol)
            if len(today_df) > 0:
                # 转换为与历史数据相同的格式
                today_df = today_df.rename({"frame": "dt"}).with_columns(
                    pl.col("dt").cast(pl.Date)
                )

            # 3. 合并历史+实时
            if len(history_df) > 0 and len(today_df) > 0:
                # 确保列一致（today_df 可能有更多列，选择共同的）
                common_cols = [col for col in history_df.columns if col in today_df.columns]
                today_df = today_df.select(common_cols)
                result = history_df.vstack(today_df).sort("dt")
            elif len(today_df) > 0:
                result = today_df
            elif len(history_df) > 0:
                result = history_df
            else:
                # 返回空 DataFrame（保持统一格式）
                result = pl.DataFrame(
                    schema={
                        "dt": pl.Date,
                        "symbol": pl.Utf8,
                        "open": pl.Float64,
                        "high": pl.Float64,
                        "low": pl.Float64,
                        "close": pl.Float64,
                        "volume": pl.Int64,
                        "amount": pl.Float64,
                        "up_limit": pl.Float64,
                        "down_limit": pl.Float64,
                        "adjust": pl.Float64,
                    }
                )

            # 4. 只取最近 n_days 天
            if len(result) > n_days:
                result = result.tail(n_days)

            return result

        except Exception as e:
            logger.error(f"Error getting daily bars with history for {symbol}: {e}")
            # 返回空 DataFrame
            return pl.DataFrame(
                schema={
                    "dt": pl.Date,
                    "symbol": pl.Utf8,
                    "open": pl.Float64,
                    "high": pl.Float64,
                    "low": pl.Float64,
                    "close": pl.Float64,
                    "volume": pl.Int64,
                    "amount": pl.Float64,
                    "up_limit": pl.Float64,
                    "down_limit": pl.Float64,
                    "adjust": pl.Float64,
                }
            )

    @property
    def all_limits(self) -> Dict[str, Dict[str, float]]:
        """获取所有缓存的涨跌停数据"""
        return self._limits.copy()

    @property
    def all_quotes(self) -> Dict[str, Dict[str, Any]]:
        """获取所有缓存的行情"""
        return self._cache.copy()

    @property
    def all_minute_bars(self) -> pl.DataFrame:
        """获取所有分钟线数据"""
        return self._minute_bars.clone()

    @property
    def all_daily_bars(self) -> pl.DataFrame:
        """获取所有日线数据"""
        return self._daily_bars.clone()

    @property
    def all_30m_bars(self) -> pl.DataFrame:
        """获取所有30分钟线数据"""
        return self._min30_bars.clone()

    @property
    def mode(self) -> str | None:
        """获取当前运行的模式"""
        return self._mode

    @property
    def is_running(self) -> bool:
        """检查服务是否正在运行"""
        return self._is_running


# 创建全局单例
live_quote = LiveQuote()
