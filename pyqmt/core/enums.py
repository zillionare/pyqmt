from enum import Enum, IntEnum


class BidType(IntEnum):
    """交易中的委托类型枚举类。

    | Value | Name       | Description (Chinese)                         |
    |-------|------------|-------------------------------------------------|
    | 0     | FIXED      | 指定价格下单 (Place order at specified price) |
    | 1     | LATEST     | 最新价 (Latest price)                          |
    | 2     | MARKET     | 市价单 (Market order)                          |
    | 3     | MINE_FIRST | 本方最优价 (Best price on own side)            |
    | 4     | PEER_FIRST | 对方最优价 (Best price on counterparty side)    |
    | 255   | UNKNOWN    | 未知 (Unknown)                                 |
    """

    FIXED = 0  # 指定价格下单
    LATEST = 1  # 最新价，兼顾成交速度与价格可控，有可能部成
    MARKET = 2  # 市价单，5档转撤
    MINE_FIRST = 3  # 本方最优价
    PEER_FIRST = 4  # 对方最优价
    UNKNOWN = 255  # 未知


class OrderSide(IntEnum):
    """交易中的买卖方向枚举类。

    | Value | Name  | Description (Chinese) |
    |-------|-------|-----------------------|
    | 1     | BUY   | 买入 (Buy)            |
    | -1    | SELL  | 卖出 (Sell)           |
    | 0     | XDXR  | 分红配股 (Dividend & allotment) |
    | 255   | UNKNOWN | 未知 (Unknown)       |
    """

    BUY = 1
    SELL = -1
    XDXR = 0
    UNKNOWN = 255  # 未知

    def __str__(self):
        return {
            OrderSide.BUY: "买入",
            OrderSide.SELL: "卖出",
            OrderSide.XDXR: "分红配股",
        }[self]


class OrderStatus(IntEnum):
    """订单状态枚举类。

    | Value | Name            | Description (Chinese)         |
    |-------|-----------------|-------------------------------|
    | 48    | UNREPORTED      | 未报 (Unreported)             |
    | 49    | WAIT_REPORTING  | 待报 (Waiting to report)      |
    | 50    | REPORTED        | 已报 (Reported)               |
    | 51    | REPORTED_CANCEL | 已报待撤 (Reported, pending cancel) |
    | 52    | PARTSUCC_CANCEL | 部分成交待撤 (Partially filled, pending cancel) |
    | 53    | PART_CANCEL     | 部分成交，余下待撤 (Partially filled, remainder pending cancel) |
    | 54    | CANCELED        | 已撤 (Canceled)               |
    | 55    | PART_SUCC       | 部分成交 (Partially succeeded)|
    | 56    | SUCCEEDED       | 已成交 (Fully succeeded)      |
    | 57    | JUNK            | 无效订单 (Invalid order)      |
    | 255   | UNKNOWN         | 未知 (Unknown)                |
    """

    UNREPORTED = 48  # 未报
    WAIT_REPORTING = 49  # 待报
    REPORTED = 50  # 已报
    REPORTED_CANCEL = 51  # 已报待撤
    PARTSUCC_CANCEL = 52  # 部分成交待撤
    PART_CANCEL = 53  # 部分成交，余下待撤
    CANCELED = 54  # 已撤
    PART_SUCC = 55  # 部分成交
    SUCCEEDED = 56  # 已成交
    JUNK = 57  # 无效订单
    UNKNOWN = 255  # 未知


class FrameType(Enum):
    """对证券交易中K线周期的封装。提供了以下对应周期:

    |     周期    | 字符串 | 类型                 | 数值 |
    | --------- | --- | ------------------ | -- |
    |     年线    | 1Y  | FrameType.YEAR     | 10 |
    |     季线    | 1Q  | FrameType.QUATER |  9  |
    |     月线    | 1M  | FrameType.MONTH    | 8  |
    |     周线    | 1W  | FrameType.WEEK     | 7  |
    |     日线    | 1D  | FrameType.DAY      | 6  |
    |     60分钟线 | 60m | FrameType.MIN60    | 5  |
    |     30分钟线 | 30m | FrameType.MIN30    | 4  |
    |     15分钟线 | 15m | FrameType.MIN15    | 3  |
    |     5分钟线  | 5m  | FrameType.MIN5     | 2  |
    |     分钟线   | 1m  | FrameType.MIN1     |  1 |

    """

    DAY = "1d"
    MIN60 = "60m"
    MIN30 = "30m"
    MIN15 = "15m"
    MIN5 = "5m"
    MIN1 = "1m"
    WEEK = "1w"
    MONTH = "1M"
    QUARTER = "1Q"
    YEAR = "1Y"

    def to_int(self) -> int:
        """转换为整数表示，用于串行化"""
        mapping = {
            FrameType.MIN1: 1,
            FrameType.MIN5: 2,
            FrameType.MIN15: 3,
            FrameType.MIN30: 4,
            FrameType.MIN60: 5,
            FrameType.DAY: 6,
            FrameType.WEEK: 7,
            FrameType.MONTH: 8,
            FrameType.QUARTER: 9,
            FrameType.YEAR: 10,
        }
        return mapping[self]

    @staticmethod
    def from_int(frame_type: int) -> "FrameType":
        """将整数表示的`frame_type`转换为`FrameType`类型"""
        mapping = {
            1: FrameType.MIN1,
            2: FrameType.MIN5,
            3: FrameType.MIN15,
            4: FrameType.MIN30,
            5: FrameType.MIN60,
            6: FrameType.DAY,
            7: FrameType.WEEK,
            8: FrameType.MONTH,
            9: FrameType.QUARTER,
            10: FrameType.YEAR,
        }

        return mapping[frame_type]

    def __lt__(self, other):
        if self.__class__ is other.__class__:
            return self.to_int() < other.to_int()
        return NotImplemented

    def __le__(self, other) -> bool:
        if self.__class__ is other.__class__:
            return self.to_int() <= other.to_int()

        return NotImplemented

    def __ge__(self, other) -> bool:
        if self.__class__ is other.__class__:
            return self.to_int() >= other.to_int()

        return NotImplemented

    def __gt__(self, other) -> bool:
        if self.__class__ is other.__class__:
            return self.to_int() > other.to_int()

        return NotImplemented


class BrokerKind(Enum):
    """broker 类型"""

    BACKTEST = "bt"
    SIMULATION = "sim"
    QMT = "qmt"


class Topics(Enum):
    """消息主题"""

    QUOTES_ALL = "quotes.all"
    STOCK_LIMIT = "stock_limit"
    BARS_1M = "bars.1m"
    BARS_30M = "bars.30m"
    BARS_1D = "bars.1d"
