from coretypes import FrameType

EPOCH_KEY = "epoch"
EPOCH = "20050104"

TIME_FORMAT = "YYYYMMDDHHmmss"
DATE_FORMAT = "YYYYMMDD"

day_level_frames = [
    FrameType.DAY,
    FrameType.WEEK,
    FrameType.MONTH,
    FrameType.QUARTER
]

min_level_frames = [
    FrameType.MIN1,
    FrameType.MIN5,
    FrameType.MIN15,
    FrameType.MIN30,
    FrameType.MIN60
]
