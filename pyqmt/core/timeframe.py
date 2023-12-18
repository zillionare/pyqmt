#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import datetime
import itertools
import logging
from types import NoneType
from typing import List, Tuple, Union

import arrow
import cfg4py
import numpy as np
from arrow import Arrow
from coretypes import Frame, FrameType
from numpy.typing import NDArray

from pyqmt.core.ext import count_between, floor, shift

logger = logging.getLogger(__file__)
EPOCH = datetime.datetime(1970, 1, 1, 0, 0, 0)
CALENDAR_START = datetime.date(2005, 1, 4)

cfg = cfg4py.get_instance()
class TimeFrame:
    minute_level_frames = [
        FrameType.MIN1,
        FrameType.MIN5,
        FrameType.MIN15,
        FrameType.MIN30,
        FrameType.MIN60,
    ]
    day_level_frames = [
        FrameType.DAY,
        FrameType.WEEK,
        FrameType.MONTH,
        FrameType.QUARTER,
        FrameType.YEAR,
    ]

    ticks = {
        FrameType.MIN1: [i for i in itertools.chain(range(571, 691), range(781, 901))],
        FrameType.MIN5: [
            i for i in itertools.chain(range(575, 695, 5), range(785, 905, 5))
        ],
        FrameType.MIN15: [
            i for i in itertools.chain(range(585, 705, 15), range(795, 915, 15))
        ],
        FrameType.MIN30: [
            int(s[:2]) * 60 + int(s[2:])
            for s in ["1000", "1030", "1100", "1130", "1330", "1400", "1430", "1500"]
        ],
        FrameType.MIN60: [
            int(s[:2]) * 60 + int(s[2:]) for s in ["1030", "1130", "1400", "1500"]
        ],
    }
    day_frames: NDArray
    week_frames: NDArray
    month_frames: NDArray
    quarter_frames: NDArray
    year_frames: NDArray

    @classmethod
    def _load_calendar(cls):
        """从数据缓存中加载更新日历"""

        names = [
            "day_frames",
            "week_frames",
            "month_frames",
            "quarter_frames",
            "year_frames",
        ]
        for name, frame_type in zip(names, cls.day_level_frames):
            key = f"calendar:{frame_type.value}"
            result = cfg.cache.security.lrange(key, 0, -1)
            if result is not None and len(result):
                frames = [int(x) for x in result]
                setattr(cls, name, np.array(frames))
            else:  # pragma: no cover
                raise ValueError("calendar not in redis")

    @classmethod
    def init(cls):
        """初始化日历"""
        cls._load_calendar()

    @classmethod
    def save_calendar(cls, trade_days):
        for ft in [FrameType.WEEK, FrameType.MONTH, FrameType.QUARTER, FrameType.YEAR]:
            days = cls.resample_frames(trade_days, ft)
            frames = [cls.date2int(x) for x in days]

            key = f"calendar:{ft.value}"
            pl = cfg.cache.security.pipeline()
            pl.delete(key)
            pl.rpush(key, *frames)
            pl.execute()

        frames = [cls.date2int(x) for x in trade_days]
        key = f"calendar:{FrameType.DAY.value}"
        pl = cfg.cache.security.pipeline()
        pl.delete(key)
        pl.rpush(key, *frames)
        pl.execute()

    @classmethod
    def remove_calendar(cls):
        for ft in cls.day_level_frames:
            key = f"calendar:{ft.value}"
            cfg.cache.security.delete(key)

    @classmethod
    def int2time(cls, tm: int) -> datetime.datetime:
        """将整数表示的时间转换为`datetime`类型表示

        examples:
            >>> TimeFrame.int2time(202005011500)
            datetime.datetime(2020, 5, 1, 15, 0)

        Args:
            tm: time in YYYYMMDDHHmm format

        Returns:
            转换后的时间
        """
        s = str(tm)
        # its 8 times faster than arrow.get()
        return datetime.datetime(
            int(s[:4]), int(s[4:6]), int(s[6:8]), int(s[8:10]), int(s[10:12])
        )

    @classmethod
    def time2int(cls, tm: Union[datetime.datetime, Arrow]) -> int:
        """将时间类型转换为整数类型

        tm可以是Arrow类型,也可以是datetime.datetime或者任何其它类型,只要它有year,month...等
        属性
        Examples:
            >>> TimeFrame.time2int(datetime.datetime(2020, 5, 1, 15))
            202005011500

        Args:
            tm:

        Returns:
            转换后的整数,比如2020050115
        """
        return int(f"{tm.year:04}{tm.month:02}{tm.day:02}{tm.hour:02}{tm.minute:02}")

    @classmethod
    def date2int(cls, d: Union[datetime.datetime, datetime.date, Arrow]) -> int:
        """将日期转换为整数表示

        在zillionare中,如果要对时间和日期进行持久化操作,我们一般将其转换为int类型

        Examples:
            >>> TimeFrame.date2int(datetime.date(2020,5,1))
            20200501

        Args:
            d: date

        Returns:
            日期的整数表示,比如20220211
        """
        return int(f"{d.year:04}{d.month:02}{d.day:02}")

    @classmethod
    def int2date(cls, d: Union[int, str]) -> datetime.date:
        """将数字表示的日期转换成为日期格式

        Examples:
            >>> TimeFrame.int2date(20200501)
            datetime.date(2020, 5, 1)

        Args:
            d: YYYYMMDD表示的日期

        Returns:
            转换后的日期
        """
        s = str(d)
        # it's 8 times faster than arrow.get
        return datetime.date(int(s[:4]), int(s[4:6]), int(s[6:]))

    @classmethod
    def day_shift(cls, start: datetime.date, offset: int) -> datetime.date:
        """对指定日期进行前后移位操作

        如果 n == 0,则返回d对应的交易日(如果是非交易日,则返回刚结束的一个交易日）
        如果 n > 0,则返回d对应的交易日后第 n 个交易日
        如果 n < 0,则返回d对应的交易日前第 n 个交易日

        Examples:
            >>> TimeFrame.day_frames = [20191212, 20191213, 20191216, 20191217,20191218, 20191219]
            >>> TimeFrame.day_shift(datetime.date(2019,12,13), 0)
            datetime.date(2019, 12, 13)

            >>> TimeFrame.day_shift(datetime.date(2019, 12, 15), 0)
            datetime.date(2019, 12, 13)

            >>> TimeFrame.day_shift(datetime.date(2019, 12, 15), 1)
            datetime.date(2019, 12, 16)

            >>> TimeFrame.day_shift(datetime.date(2019, 12, 13), 1)
            datetime.date(2019, 12, 16)

        Args:
            start: the origin day
            offset: days to shift, can be negative

        Returns:
            移位后的日期
        """
        # accelerated from 0.12 to 0.07, per 10000 loop, type conversion time included
        istart = cls.date2int(start)

        return cls.int2date(shift(cls.day_frames, istart, offset))

    @classmethod
    def week_shift(cls, start: datetime.date, offset: int) -> datetime.date:
        """对指定日期按周线帧进行前后移位操作

        参考 [omicron.models.timeframe.TimeFrame.day_shift][]
        Examples:
            >>> TimeFrame.week_frames = np.array([20200103, 20200110, 20200117, 20200123,20200207, 20200214])
            >>> moment = arrow.get('2020-1-21').date()
            >>> TimeFrame.week_shift(moment, 1)
            datetime.date(2020, 1, 23)

            >>> TimeFrame.week_shift(moment, 0)
            datetime.date(2020, 1, 17)

            >>> TimeFrame.week_shift(moment, -1)
            datetime.date(2020, 1, 10)

        Returns:
            移位后的日期
        """
        istart = cls.date2int(start)
        return cls.int2date(shift(cls.week_frames, istart, offset))

    @classmethod
    def month_shift(cls, start: datetime.date, offset: int) -> datetime.date:
        """求`start`所在的月移位后的frame

        本函数首先将`start`对齐,然后进行移位。
        Examples:
            >>> TimeFrame.month_frames = np.array([20150130, 20150227, 20150331, 20150430])
            >>> TimeFrame.month_shift(arrow.get('2015-2-26').date(), 0)
            datetime.date(2015, 1, 30)

            >>> TimeFrame.month_shift(arrow.get('2015-2-27').date(), 0)
            datetime.date(2015, 2, 27)

            >>> TimeFrame.month_shift(arrow.get('2015-3-1').date(), 0)
            datetime.date(2015, 2, 27)

            >>> TimeFrame.month_shift(arrow.get('2015-3-1').date(), 1)
            datetime.date(2015, 3, 31)

        Returns:
            移位后的日期
        """
        istart = cls.date2int(start)
        return cls.int2date(shift(cls.month_frames, istart, offset))

    @classmethod
    def get_ticks(cls, frame_type: FrameType) -> Union[List, NDArray]:
        """取月线、周线、日线及各分钟线对应的frame

        对分钟线,返回值仅包含时间,不包含日期(均为整数表示）

        Examples:
            >>> TimeFrame.month_frames = np.array([20050131, 20050228, 20050331])
            >>> TimeFrame.get_ticks(FrameType.MONTH)[:3]
            array([20050131, 20050228, 20050331])

        Args:
            frame_type : [description]

        Raises:
            ValueError: [description]

        Returns:
            月线、周线、日线及各分钟线对应的frame
        """
        if frame_type in cls.minute_level_frames:
            return cls.ticks[frame_type]

        if frame_type == FrameType.DAY:
            return cls.day_frames
        elif frame_type == FrameType.WEEK:
            return cls.week_frames
        elif frame_type == FrameType.MONTH:
            return cls.month_frames
        else:  # pragma: no cover
            raise ValueError(f"{frame_type} not supported!")

    @classmethod
    def shift(
        cls,
        moment: Union[Arrow, datetime.date, datetime.datetime],
        n: int,
        frame_type: FrameType,
    ) -> Union[datetime.date, datetime.datetime]:
        """将指定的moment移动N个`frame_type`位置。

        当N为负数时,意味着向前移动；当N为正数时,意味着向后移动。如果n为零,意味着移动到最接近
        的一个已结束的frame。

        如果moment没有对齐到frame_type对应的时间,将首先进行对齐。

        See also:

        - [day_shift][omicron.models.timeframe.TimeFrame.day_shift]
        - [week_shift][omicron.models.timeframe.TimeFrame.week_shift]
        - [month_shift][omicron.models.timeframe.TimeFrame.month_shift]

        Examples:
            >>> TimeFrame.shift(datetime.date(2020, 1, 3), 1, FrameType.DAY)
            datetime.date(2020, 1, 6)

            >>> TimeFrame.shift(datetime.datetime(2020, 1, 6, 11), 1, FrameType.MIN30)
            datetime.datetime(2020, 1, 6, 11, 30)


        Args:
            moment:
            n:
            frame_type:

        Returns:
            移位后的Frame
        """
        if frame_type == FrameType.DAY:
            assert isinstance(moment, datetime.date)
            return cls.day_shift(moment, n)

        elif frame_type == FrameType.WEEK:
            assert isinstance(moment, datetime.date)
            return cls.week_shift(moment, n)
        elif frame_type == FrameType.MONTH:
            assert isinstance(moment, datetime.date)
            return cls.month_shift(moment, n)
        elif frame_type in [
            FrameType.MIN1,
            FrameType.MIN5,
            FrameType.MIN15,
            FrameType.MIN30,
            FrameType.MIN60,
        ]:
            assert isinstance(moment, datetime.datetime)
            tm = moment.hour * 60 + moment.minute

            new_tick_pos = cls.ticks[frame_type].index(tm) + n
            days = new_tick_pos // len(cls.ticks[frame_type])
            min_part = new_tick_pos % len(cls.ticks[frame_type])

            date_part = cls.day_shift(moment.date(), days)
            minutes = cls.ticks[frame_type][min_part]
            h, m = minutes // 60, minutes % 60
            return datetime.datetime(
                date_part.year,
                date_part.month,
                date_part.day,
                h,
                m,
                tzinfo=moment.tzinfo,
            )
        else:  # pragma: no cover
            raise ValueError(f"{frame_type} is not supported.")

    @classmethod
    def count_day_frames(
        cls, start: Union[datetime.date, Arrow], end: Union[datetime.date, Arrow]
    ) -> int:
        """calc trade days between start and end in close-to-close way.

        if start == end, this will returns 1. Both start/end will be aligned to open
        trade day before calculation.

        Examples:
            >>> start = datetime.date(2019, 12, 21)
            >>> end = datetime.date(2019, 12, 21)
            >>> TimeFrame.day_frames = [20191219, 20191220, 20191223, 20191224, 20191225]
            >>> TimeFrame.count_day_frames(start, end)
            1

            >>> # non-trade days are removed
            >>> TimeFrame.day_frames = [20200121, 20200122, 20200123, 20200203, 20200204, 20200205]
            >>> start = datetime.date(2020, 1, 23)
            >>> end = datetime.date(2020, 2, 4)
            >>> TimeFrame.count_day_frames(start, end)
            3

        args:
            start:
            end:
        returns:
            count of days
        """
        istart = cls.date2int(start)
        iend = cls.date2int(end)
        return int(count_between(cls.day_frames, istart, iend))

    @classmethod
    def count_week_frames(cls, start: datetime.date | Arrow, end: datetime.date | Arrow) -> int:
        """
        calc trade weeks between start and end in close-to-close way. Both start and
        end will be aligned to open trade day before calculation. After that, if start
         == end, this will returns 1

        for examples, please refer to [count_day_frames][omicron.models.timeframe.TimeFrame.count_day_frames]
        args:
            start:
            end:
        returns:
            count of weeks
        """
        istart = cls.date2int(start)
        iend = cls.date2int(end)
        return int(count_between(cls.week_frames, istart, iend))

    @classmethod
    def count_month_frames(cls, start: datetime.date | Arrow, end: datetime.date | Arrow) -> int:
        """calc trade months between start and end date in close-to-close way
        Both start and end will be aligned to open trade day before calculation. After
        that, if start == end, this will returns 1.

        For examples, please refer to [count_day_frames][omicron.models.timeframe.TimeFrame.count_day_frames]

        Args:
            start:
            end:

        Returns:
            months between start and end
        """
        istart = cls.date2int(start)
        iend = cls.date2int(end)

        return int(count_between(cls.month_frames, istart, iend))

    @classmethod
    def count_quarter_frames(cls, start: datetime.date | Arrow, end: datetime.date | Arrow) -> int:
        """calc trade quarters between start and end date in close-to-close way
        Both start and end will be aligned to open trade day before calculation. After
        that, if start == end, this will returns 1.

        For examples, please refer to [count_day_frames][omicron.models.timeframe.TimeFrame.count_day_frames]

        Args:
            start (datetime.date): [description]
            end (datetime.date): [description]

        Returns:
            quarters between start and end
        """
        istart = cls.date2int(start)
        iend = cls.date2int(end)

        return int(count_between(cls.quarter_frames, istart, iend))

    @classmethod
    def count_year_frames(cls, start: datetime.date | Arrow, end: datetime.date | Arrow) -> int:
        """calc trade years between start and end date in close-to-close way
        Both start and end will be aligned to open trade day before calculation. After
        that, if start == end, this will returns 1.

        For examples, please refer to [count_day_frames][omicron.models.timeframe.TimeFrame.count_day_frames]

        Args:
            start (datetime.date): [description]
            end (datetime.date): [description]

        Returns:
            years between start and end
        """
        istart = cls.date2int(start)
        iend = cls.date2int(end)

        return int(count_between(cls.year_frames, istart, iend))

    @classmethod
    def count_frames(
        cls,
        start: Union[datetime.date, datetime.datetime, Arrow],
        end: Union[datetime.date, datetime.datetime, Arrow],
        frame_type,
    ) -> int:
        """计算start与end之间有多少个周期为frame_type的frames

        See also:

        - [count_day_frames][omicron.models.timeframe.TimeFrame.count_day_frames]
        - [count_week_frames][omicron.models.timeframe.TimeFrame.count_week_frames]
        - [count_month_frames][omicron.models.timeframe.TimeFrame.count_month_frames]

        Args:
            start : start frame
            end : end frame
            frame_type : the type of frame

        Raises:
            ValueError: 如果frame_type不支持,则会抛出此异常。

        Returns:
            从start到end的帧数
        """
        if frame_type == FrameType.DAY:
            return cls.count_day_frames(start, end)
        elif frame_type == FrameType.WEEK:
            return cls.count_week_frames(start, end)
        elif frame_type == FrameType.MONTH:
            return cls.count_month_frames(start, end)
        elif frame_type == FrameType.QUARTER:
            return cls.count_quarter_frames(start, end)
        elif frame_type == FrameType.YEAR:
            return cls.count_year_frames(start, end)
        elif frame_type in [
            FrameType.MIN1,
            FrameType.MIN5,
            FrameType.MIN15,
            FrameType.MIN30,
            FrameType.MIN60,
        ]:
            tm_start = start.hour * 60 + start.minute # type: ignore
            tm_end = end.hour * 60 + end.minute # type: ignore
            days = cls.count_day_frames(start.date(), end.date()) - 1 # type: ignore

            tm_start_pos = cls.ticks[frame_type].index(tm_start)
            tm_end_pos = cls.ticks[frame_type].index(tm_end)

            min_bars = tm_end_pos - tm_start_pos + 1

            return days * len(cls.ticks[frame_type]) + min_bars
        else:  # pragma: no cover
            raise ValueError(f"{frame_type} is not supported yet")

    @classmethod
    def is_trade_day(cls, dt: Union[datetime.date, datetime.datetime, Arrow]) -> bool:
        """判断`dt`是否为交易日

        Examples:
            >>> TimeFrame.is_trade_day(arrow.get('2020-1-1'))
            False

        Args:
            dt :

        Returns:
            bool
        """
        return cls.date2int(dt) in cls.day_frames

    @classmethod
    def is_open_time(cls, tm: datetime.datetime | Arrow | NoneType = None) -> bool:
        """判断`tm`指定的时间是否处在交易时间段。

        交易时间段是指集合竞价时间段之外的开盘时间

        Examples:
            >>> TimeFrame.day_frames = np.array([20200102, 20200103, 20200106, 20200107, 20200108])
            >>> TimeFrame.is_open_time(arrow.get('2020-1-1 14:59').naive)
            False
            >>> TimeFrame.is_open_time(arrow.get('2020-1-3 14:59').naive)
            True

        Args:
            tm : [description]. Defaults to None.

        Returns:
            bool
        """
        tm = tm or arrow.now()

        if not cls.is_trade_day(tm):
            return False

        tick = tm.hour * 60 + tm.minute
        return tick in cls.ticks[FrameType.MIN1]

    @classmethod
    def is_opening_call_auction_time(
        cls, tm: Union[Arrow, datetime.datetime] = None
    ) -> bool:
        """判断`tm`指定的时间是否为开盘集合竞价时间

        Args:
            tm : [description]. Defaults to None.

        Returns:
            bool
        """
        if tm is None:
            tm = cls.now()

        if not cls.is_trade_day(tm):
            return False

        minutes = tm.hour * 60 + tm.minute
        return 9 * 60 + 15 < minutes <= 9 * 60 + 25

    @classmethod
    def is_closing_call_auction_time(
        cls, tm: Union[datetime.datetime, Arrow] = None
    ) -> bool:
        """判断`tm`指定的时间是否为收盘集合竞价时间

        Fixme:
            此处实现有误,收盘集合竞价时间应该还包含上午收盘时间

        Args:
            tm : [description]. Defaults to None.

        Returns:
            bool
        """
        tm = tm or cls.now()

        if not cls.is_trade_day(tm):
            return False

        minutes = tm.hour * 60 + tm.minute
        return 15 * 60 - 3 <= minutes < 15 * 60

    @classmethod
    def floor(cls, moment: Frame, frame_type: FrameType) -> Frame:
        """求`moment`在指定的`frame_type`中的下界

        比如,如果`moment`为10:37,则当`frame_type`为30分钟时,对应的上界为10:00

        Examples:
            >>> # 如果moment为日期,则当成已收盘处理
            >>> TimeFrame.day_frames = np.array([20050104, 20050105, 20050106, 20050107, 20050110, 20050111])
            >>> TimeFrame.floor(datetime.date(2005, 1, 7), FrameType.DAY)
            datetime.date(2005, 1, 7)

            >>> # moment指定的时间还未收盘,floor到上一个交易日
            >>> TimeFrame.floor(datetime.datetime(2005, 1, 7, 14, 59), FrameType.DAY)
            datetime.date(2005, 1, 6)

            >>> TimeFrame.floor(datetime.date(2005, 1, 13), FrameType.WEEK)
            datetime.date(2005, 1, 7)

            >>> TimeFrame.floor(datetime.date(2005,2, 27), FrameType.MONTH)
            datetime.date(2005, 1, 31)

            >>> TimeFrame.floor(datetime.datetime(2005,1,5,14,59), FrameType.MIN30)
            datetime.datetime(2005, 1, 5, 14, 30)

            >>> TimeFrame.floor(datetime.datetime(2005, 1, 5, 14, 59), FrameType.MIN1)
            datetime.datetime(2005, 1, 5, 14, 59)

            >>> TimeFrame.floor(arrow.get('2005-1-5 14:59').naive, FrameType.MIN1)
            datetime.datetime(2005, 1, 5, 14, 59)

        Args:
            moment:
            frame_type:

        Returns:
            `moment`在指定的`frame_type`中的下界
        """
        if frame_type in cls.minute_level_frames:
            tm, day_offset = cls.minute_frames_floor(
                cls.ticks[frame_type], moment.hour * 60 + moment.minute
            )
            h, m = tm // 60, tm % 60
            if cls.day_shift(moment, 0) < moment.date() or day_offset == -1:
                h = 15
                m = 0
                new_day = cls.day_shift(moment, day_offset)
            else:
                new_day = moment.date()
            return datetime.datetime(new_day.year, new_day.month, new_day.day, h, m)

        if type(moment) == datetime.date:
            moment = datetime.datetime(moment.year, moment.month, moment.day, 15)

        # 如果是交易日,但还未收盘
        if (
            cls.date2int(moment) in cls.day_frames
            and moment.hour * 60 + moment.minute < 900
        ):
            moment = cls.day_shift(moment, -1)

        day = cls.date2int(moment)
        if frame_type == FrameType.DAY:
            arr = cls.day_frames
        elif frame_type == FrameType.WEEK:
            arr = cls.week_frames
        elif frame_type == FrameType.MONTH:
            arr = cls.month_frames
        else:  # pragma: no cover
            raise ValueError(f"frame type {frame_type} not supported.")

        floored = floor(arr, day)
        return cls.int2date(floored)

    @classmethod
    def last_min_frame(
        cls, day: Union[str, Arrow, datetime.date], frame_type: FrameType
    ) -> Union[datetime.date, datetime.datetime]:
        """获取`day`日周期为`frame_type`的结束frame。

        Example:
            >>> TimeFrame.last_min_frame(arrow.get('2020-1-5').date(), FrameType.MIN30)
            datetime.datetime(2020, 1, 3, 15, 0)

        Args:
            day:
            frame_type:

        Returns:
            `day`日周期为`frame_type`的结束frame
        """
        if isinstance(day, str):
            day = cls.date2int(arrow.get(day).date())
        elif isinstance(day, arrow.Arrow) or isinstance(day, datetime.datetime):
            day = cls.date2int(day.date())
        elif isinstance(day, datetime.date):
            day = cls.date2int(day)
        else:
            raise TypeError(f"{type(day)} is not supported.")

        if frame_type in cls.minute_level_frames:
            last_close_day = cls.day_frames[cls.day_frames <= day][-1]
            day = cls.int2date(last_close_day)
            return datetime.datetime(day.year, day.month, day.day, hour=15, minute=0)
        else:  # pragma: no cover
            raise ValueError(f"{frame_type} not supported")

    @classmethod
    def frame_len(cls, frame_type: FrameType) -> int:
        """返回以分钟为单位的frame长度。

        对日线以上级别没有意义,但会返回240

        Examples:
            >>> TimeFrame.frame_len(FrameType.MIN5)
            5

        Args:
            frame_type:

        Returns:
            返回以分钟为单位的frame长度。

        """

        if frame_type == FrameType.MIN1:
            return 1
        elif frame_type == FrameType.MIN5:
            return 5
        elif frame_type == FrameType.MIN15:
            return 15
        elif frame_type == FrameType.MIN30:
            return 30
        elif frame_type == FrameType.MIN60:
            return 60
        else:
            return 240

    @classmethod
    def first_min_frame(
        cls, day: Union[str, Arrow, Frame], frame_type: FrameType
    ) -> Union[datetime.date, datetime.datetime]:
        """获取指定日期类型为`frame_type`的`frame`。

        Examples:
            >>> TimeFrame.day_frames = np.array([20191227, 20191230, 20191231, 20200102, 20200103])
            >>> TimeFrame.first_min_frame('2019-12-31', FrameType.MIN1)
            datetime.datetime(2019, 12, 31, 9, 31)

        Args:
            day: which day?
            frame_type: which frame_type?

        Returns:
            `day`当日的第一帧
        """
        day = cls.date2int(arrow.get(day).date())

        if frame_type == FrameType.MIN1:
            floor_day = cls.day_frames[cls.day_frames <= day][-1]
            day = cls.int2date(floor_day)
            return datetime.datetime(day.year, day.month, day.day, hour=9, minute=31)
        elif frame_type == FrameType.MIN5:
            floor_day = cls.day_frames[cls.day_frames <= day][-1]
            day = cls.int2date(floor_day)
            return datetime.datetime(day.year, day.month, day.day, hour=9, minute=35)
        elif frame_type == FrameType.MIN15:
            floor_day = cls.day_frames[cls.day_frames <= day][-1]
            day = cls.int2date(floor_day)
            return datetime.datetime(day.year, day.month, day.day, hour=9, minute=45)
        elif frame_type == FrameType.MIN30:
            floor_day = cls.day_frames[cls.day_frames <= day][-1]
            day = cls.int2date(floor_day)
            return datetime.datetime(day.year, day.month, day.day, hour=10)
        elif frame_type == FrameType.MIN60:
            floor_day = cls.day_frames[cls.day_frames <= day][-1]
            day = cls.int2date(floor_day)
            return datetime.datetime(day.year, day.month, day.day, hour=10, minute=30)
        else:  # pragma: no cover
            raise ValueError(f"{frame_type} not supported")

    @classmethod
    def get_frames(cls, start: Frame, end: Frame, frame_type: FrameType) -> List[int]:
        """取[start, end]间所有类型为frame_type的frames

        调用本函数前,请先通过`floor`或者`ceiling`将时间帧对齐到`frame_type`的边界值

        Example:
            >>> start = arrow.get('2020-1-13 10:00').naive
            >>> end = arrow.get('2020-1-13 13:30').naive
            >>> TimeFrame.day_frames = np.array([20200109, 20200110, 20200113,20200114, 20200115, 20200116])
            >>> TimeFrame.get_frames(start, end, FrameType.MIN30)
            [202001131000, 202001131030, 202001131100, 202001131130, 202001131330]

        Args:
            start:
            end:
            frame_type:

        Returns:
            frame list
        """
        n = cls.count_frames(start, end, frame_type)
        return cls.get_frames_by_count(end, n, frame_type)

    @classmethod
    def get_frames_by_count(
        cls, end: Arrow, n: int, frame_type: FrameType
    ) -> List[int]:
        """取以end为结束点,周期为frame_type的n个frame

        调用前请将`end`对齐到`frame_type`的边界

        Examples:
            >>> end = arrow.get('2020-1-6 14:30').naive
            >>> TimeFrame.day_frames = np.array([20200102, 20200103,20200106, 20200107, 20200108, 20200109])
            >>> TimeFrame.get_frames_by_count(end, 2, FrameType.MIN30)
            [202001061400, 202001061430]

        Args:
            end:
            n:
            frame_type:

        Returns:
            frame list
        """

        if frame_type == FrameType.DAY:
            end = cls.date2int(end)
            pos = np.searchsorted(cls.day_frames, end, side="right")
            return cls.day_frames[max(0, pos - n) : pos].tolist()
        elif frame_type == FrameType.WEEK:
            end = cls.date2int(end)
            pos = np.searchsorted(cls.week_frames, end, side="right")
            return cls.week_frames[max(0, pos - n) : pos].tolist()
        elif frame_type == FrameType.MONTH:
            end = cls.date2int(end)
            pos = np.searchsorted(cls.month_frames, end, side="right")
            return cls.month_frames[max(0, pos - n) : pos].tolist()
        elif frame_type in {
            FrameType.MIN1,
            FrameType.MIN5,
            FrameType.MIN15,
            FrameType.MIN30,
            FrameType.MIN60,
        }:
            n_days = n // len(cls.ticks[frame_type]) + 2
            ticks = cls.ticks[frame_type] * n_days

            days = cls.get_frames_by_count(end, n_days, FrameType.DAY)
            days = np.repeat(days, len(cls.ticks[frame_type]))

            ticks = [
                day.item() * 10000 + int(tm / 60) * 100 + tm % 60
                for day, tm in zip(days, ticks)
            ]

            # list index is much faster than index_sorted when the arr is small
            pos = ticks.index(cls.time2int(end)) + 1

            return ticks[max(0, pos - n) : pos]
        else:  # pragma: no cover
            raise ValueError(f"{frame_type} not support yet")

    @classmethod
    def ceiling(cls, moment: Frame, frame_type: FrameType) -> Frame:
        """求`moment`所在类型为`frame_type`周期的上界

        比如`moment`为14:59分,如果`frame_type`为30分钟,则它的上界应该为15:00

        Example:
            >>> TimeFrame.day_frames = [20050104, 20050105, 20050106, 20050107]
            >>> TimeFrame.ceiling(datetime.date(2005, 1, 7), FrameType.DAY)
            datetime.date(2005, 1, 7)

            >>> TimeFrame.week_frames = [20050107, 20050114, 20050121, 20050128]
            >>> TimeFrame.ceiling(datetime.date(2005, 1, 4), FrameType.WEEK)
            datetime.date(2005, 1, 7)

            >>> TimeFrame.ceiling(datetime.date(2005,1,7), FrameType.WEEK)
            datetime.date(2005, 1, 7)

            >>> TimeFrame.month_frames = [20050131, 20050228]
            >>> TimeFrame.ceiling(datetime.date(2005,1 ,1), FrameType.MONTH)
            datetime.date(2005, 1, 31)

            >>> TimeFrame.ceiling(datetime.datetime(2005,1,5,14,59), FrameType.MIN30)
            datetime.datetime(2005, 1, 5, 15, 0)

            >>> TimeFrame.ceiling(datetime.datetime(2005, 1, 5, 14, 59), FrameType.MIN1)
            datetime.datetime(2005, 1, 5, 14, 59)

            >>> TimeFrame.ceiling(arrow.get('2005-1-5 14:59').naive, FrameType.MIN1)
            datetime.datetime(2005, 1, 5, 14, 59)

        Args:
            moment (datetime.datetime): [description]
            frame_type (FrameType): [description]

        Returns:
            `moment`所在类型为`frame_type`周期的上界
        """
        if frame_type in cls.day_level_frames and type(moment) == datetime.datetime:
            moment = moment.date()

        floor = cls.floor(moment, frame_type)
        if floor == moment:
            return moment
        elif floor > moment:
            return floor
        else:
            return cls.shift(floor, 1, frame_type)

    @classmethod
    def combine_time(
        cls,
        date: datetime.date,
        hour: int,
        minute: int = 0,
        second: int = 0,
        microsecond: int = 0,
    ) -> datetime.datetime:
        """用`date`指定的日期与`hour`, `minute`, `second`等参数一起合成新的时间

        Examples:
            >>> TimeFrame.combine_time(datetime.date(2020, 1, 1), 14, 30)
            datetime.datetime(2020, 1, 1, 14, 30)

        Args:
            date : [description]
            hour : [description]
            minute : [description]. Defaults to 0.
            second : [description]. Defaults to 0.
            microsecond : [description]. Defaults to 0.

        Returns:
            合成后的时间
        """
        return datetime.datetime(
            date.year, date.month, date.day, hour, minute, second, microsecond
        )

    @classmethod
    def replace_date(
        cls, dtm: datetime.datetime, dt: datetime.date
    ) -> datetime.datetime:
        """将`dtm`变量的日期更换为`dt`指定的日期

        Example:
            >>> TimeFrame.replace_date(arrow.get('2020-1-1 13:49').datetime, datetime.date(2019, 1,1))
            datetime.datetime(2019, 1, 1, 13, 49)

        Args:
            dtm (datetime.datetime): [description]
            dt (datetime.date): [description]

        Returns:
            变换后的时间
        """
        return datetime.datetime(
            dt.year, dt.month, dt.day, dtm.hour, dtm.minute, dtm.second, dtm.microsecond
        )

    @classmethod
    def resample_frames(
        cls, trade_days: List[datetime.date], frame_type: FrameType
    ) -> List[datetime.date]:
        """将从行情服务器获取的交易日历重采样,生成周帧和月线帧

        Args:
            trade_days: 交易日
            frame_type: 待重采样的周期

        Returns:
            重采样后的日期列表
        """
        if frame_type == FrameType.WEEK:
            weeks = []
            last = trade_days[0]
            for cur in trade_days:
                if cur.weekday() < last.weekday() or (cur - last).days >= 7:
                    weeks.append(last)
                last = cur

            if weeks[-1] < last:
                weeks.append(last)

            return weeks
        elif frame_type == FrameType.MONTH:
            months = []
            last = trade_days[0]
            for cur in trade_days:
                if cur.day < last.day:
                    months.append(last)
                last = cur
            months.append(last)

            return months
        elif frame_type == FrameType.QUARTER:
            quarters = []
            last = trade_days[0]
            for cur in trade_days:
                if last.month % 3 == 0:
                    if cur.month > last.month or cur.year > last.year:
                        quarters.append(last)
                last = cur
            quarters.append(last)

            return quarters
        elif frame_type == FrameType.YEAR:
            years = []
            last = trade_days[0]
            for cur in trade_days:
                if cur.year > last.year:
                    years.append(last)
                last = cur
            years.append(last)

            return years
        else:  # pragma: no cover
            raise ValueError(f"Unsupported FrameType: {frame_type}")

    @classmethod
    def minute_frames_floor(cls, ticks, moment) -> Tuple[int, int]:
        """
        对于分钟级的frame,返回它们与frame刻度向下对齐后的frame及日期进位。如果需要对齐到上一个交易
        日,则进位为-1,否则为0.

        Examples:
            >>> ticks = [600, 630, 660, 690, 810, 840, 870, 900]
            >>> TimeFrame.minute_frames_floor(ticks, 545)
            (900, -1)
            >>> TimeFrame.minute_frames_floor(ticks, 600)
            (600, 0)
            >>> TimeFrame.minute_frames_floor(ticks, 605)
            (600, 0)
            >>> TimeFrame.minute_frames_floor(ticks, 899)
            (870, 0)
            >>> TimeFrame.minute_frames_floor(ticks, 900)
            (900, 0)
            >>> TimeFrame.minute_frames_floor(ticks, 905)
            (900, 0)

        Args:
            ticks (np.array or list): frames刻度
            moment (int): 整数表示的分钟数,比如900表示15：00

        Returns:
            tuple, the first is the new moment, the second is carry-on
        """
        if moment < ticks[0]:
            return ticks[-1], -1
        # ’right' 相当于 ticks <= m
        index = np.searchsorted(ticks, moment, side="right")
        return ticks[index - 1], 0

    @classmethod
    def is_bar_closed(cls, frame: Frame, ft: FrameType) -> bool:
        """判断`frame`所代表的bar是否已经收盘(结束）

        如果是日线,frame不为当天,则认为已收盘；或者当前时间在收盘时间之后,也认为已收盘。
        如果是其它周期,则只有当frame正好在边界上,才认为是已收盘。这里有一个假设：我们不会在其它周期上,判断未来的某个frame是否已经收盘。

        Args:
            frame : bar所处的时间,必须小于当前时间
            ft: bar所代表的帧类型

        Returns:
            bool: 是否已经收盘
        """
        floor = cls.floor(frame, ft)

        now = arrow.now()
        if ft == FrameType.DAY:
            return floor < now.date() or now.hour >= 15
        else:
            return floor == frame

    @classmethod
    def get_frame_scope(cls, frame: Frame, ft: FrameType) -> Tuple[Frame, Frame]:
        # todo: 函数的通用性不足,似乎应该放在具体的业务类中。如果是通用型的函数,参数不应该局限于周和月。
        """对于给定的时间,取所在周的第一天和最后一天,所在月的第一天和最后一天

        Args:
            frame : 指定的日期,date对象
            ft: 帧类型,支持WEEK和MONTH

        Returns:
            Tuple[Frame, Frame]: 周或者月的首末日期(date对象）

        """
        if frame is None:
            raise ValueError("frame cannot be None")
        if ft not in (FrameType.WEEK, FrameType.MONTH):
            raise ValueError(f"FrameType only supports WEEK and MONTH: {ft}")

        if isinstance(frame, datetime.datetime):
            frame = frame.date()

        if frame < CALENDAR_START:
            raise ValueError(f"cannot be earlier than {CALENDAR_START}: {frame}")

        # datetime.date(2021, 10, 8),这是个特殊的日期
        if ft == FrameType.WEEK:
            if frame < datetime.date(2005, 1, 10):
                return datetime.date(2005, 1, 4), datetime.date(2005, 1, 7)

            if not cls.is_trade_day(frame):  # 非交易日的情况,直接回退一天
                week_day = cls.day_shift(frame, 0)
            else:
                week_day = frame

            w1 = TimeFrame.floor(week_day, FrameType.WEEK)
            if w1 == week_day:  # 本周的最后一个交易日
                week_end = w1
            else:
                week_end = TimeFrame.week_shift(week_day, 1)

            w0 = TimeFrame.week_shift(week_end, -1)
            week_start = TimeFrame.day_shift(w0, 1)
            return week_start, week_end

        if ft == FrameType.MONTH:
            if frame <= datetime.date(2005, 1, 31):
                return datetime.date(2005, 1, 4), datetime.date(2005, 1, 31)

            month_start = frame.replace(day=1)
            if not cls.is_trade_day(month_start):  # 非交易日的情况,直接加1
                month_start = cls.day_shift(month_start, 1)

            month_end = TimeFrame.month_shift(month_start, 1)
            return month_start, month_end

tf = TimeFrame()

__all__ = ["tf"]
