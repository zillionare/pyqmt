"""qmt-server runtime lifecycle."""

import datetime
import os
import sys

from loguru import logger
from qmt_server.settings import QmtServerSettings, load_settings, save_settings

from pyqmt.config import cfg, init_config
from pyqmt.core.scheduler import scheduler
from pyqmt.data import init_data
from pyqmt.data.dal.sector_dal import SectorDAL
from pyqmt.data.fetchers.xtdata_sectors import get_tradeable_sectors
from pyqmt.data.models.calendar import calendar
from pyqmt.data.services.sector_sync import SectorSyncService
from pyqmt.data.sqlite import db
from pyqmt.service.livequote import live_quote
from pyqmt.service.qmt_broker import QMTBroker

_qmt_broker: QMTBroker | None = None
_sector_sync: SectorSyncService | None = None
_settings = QmtServerSettings()
_ready = False


def _resolve_account_id() -> str:
    """Resolve QMT account id from persisted settings."""
    if _settings.qmt_account_id:
        return _settings.qmt_account_id
    if getattr(cfg, "qmt", None) and cfg.qmt.account_id:
        return cfg.qmt.account_id
    raise RuntimeError("未配置 QMT 账号，请先在初始化向导完成配置")


def _apply_runtime_paths() -> None:
    if _settings.qmt_path:
        if getattr(cfg, "qmt", None):
            cfg.qmt.path = _settings.qmt_path
        if _settings.qmt_path not in sys.path:
            sys.path.insert(0, _settings.qmt_path)
    if _settings.xtdata_path and _settings.xtdata_path not in sys.path:
        sys.path.insert(0, _settings.xtdata_path)
    if os.name == "nt" and _settings.qmt_path:
        try:
            os.add_dll_directory(_settings.qmt_path)
        except Exception:
            pass


def _create_broker() -> QMTBroker:
    """Create QMT broker singleton."""
    global _qmt_broker
    if _qmt_broker is None:
        account_id = _resolve_account_id()
        _qmt_broker = QMTBroker(account_id=account_id, portfolio_id=account_id)
    return _qmt_broker


def _create_sector_sync() -> SectorSyncService:
    """Create sector sync singleton."""
    global _sector_sync
    if _sector_sync is None:
        _sector_sync = SectorSyncService(SectorDAL(db), calendar)
    return _sector_sync


def _sync_sector_universe() -> None:
    """Sync sector list and constituents for current day."""
    service = _create_sector_sync()
    trade_date = datetime.date.today()
    sector_count = service.sync_sector_list(trade_date=trade_date)
    constituent_count = service.sync_sector_constituents(trade_date=trade_date)
    logger.info(
        "sector universe synced: sectors={}, constituents={}",
        sector_count,
        constituent_count,
    )


def _sync_sector_bars() -> None:
    """Sync sector bars for current day."""
    service = _create_sector_sync()
    trade_date = datetime.date.today()
    sectors = get_tradeable_sectors()
    bars = service.bars_store.fetch_multiple(
        sector_ids=sectors,
        start=trade_date,
        end=trade_date,
    )
    logger.info("sector bars synced: records={}", bars)


def _setup_jobs() -> None:
    """Register qmt-server cron jobs."""
    scheduler.add_job(
        _sync_sector_universe,
        "cron",
        hour=9,
        minute=20,
        name="qmt_server.sector.universe.sync",
    )
    scheduler.add_job(
        _sync_sector_bars,
        "cron",
        hour=16,
        minute=0,
        name="qmt_server.sector.bars.sync",
    )


def ensure_ready() -> None:
    """Initialize config, data layer, quote service and jobs."""
    global _ready, _settings
    if _ready:
        return

    init_config()
    _settings = load_settings()
    _apply_runtime_paths()
    init_data(cfg.home, init_db=True)
    scheduler.start()
    live_quote.start()
    _create_sector_sync()
    _setup_jobs()
    if _settings.is_configured:
        _create_broker()
    else:
        logger.warning("QMT settings not configured, trade API will return errors")
    _ready = True


def get_broker() -> QMTBroker:
    """Get initialized QMT broker."""
    ensure_ready()
    return _create_broker()


def get_sector_sync() -> SectorSyncService:
    """Get initialized sector sync service."""
    ensure_ready()
    return _create_sector_sync()


def get_settings() -> QmtServerSettings:
    """Get current qmt-server settings."""
    ensure_ready()
    return _settings


def update_settings(
    qmt_account_id: str,
    qmt_path: str,
    xtdata_path: str,
) -> QmtServerSettings:
    """Update settings and refresh runtime environment."""
    global _settings, _qmt_broker
    ensure_ready()
    _settings = save_settings(
        QmtServerSettings(
            qmt_account_id=qmt_account_id.strip(),
            qmt_path=qmt_path.strip(),
            xtdata_path=xtdata_path.strip(),
        )
    )
    _apply_runtime_paths()
    _qmt_broker = None
    if _settings.is_configured:
        _create_broker()
    return _settings
