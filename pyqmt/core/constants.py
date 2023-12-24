from coretypes import FrameType

EPOCH_KEY = "epoch"
EPOCH = "20050104"

TIME_FORMAT = "YYYYMMDDHHmmss"
DATE_FORMAT = "YYYYMMDD"

day_level_frames = [FrameType.DAY, FrameType.WEEK, FrameType.MONTH, FrameType.QUARTER]

min_level_frames = [
    FrameType.MIN1,
    FrameType.MIN5,
    FrameType.MIN15,
    FrameType.MIN30,
    FrameType.MIN60,
]

class HaystoreTbl:
    securities = "securities"
    bars_1m = "bars_1m"
    bars_1d = "bars_1d"

class ChoreTbl:
    ashares_sync = "sync_ashare_list_status"
    bars_cache = "bars_cache_status"
    sync_bars_jobs = "sync_bars_jobs"
    sync_sector_jobs = "sync_sector.jobs"
