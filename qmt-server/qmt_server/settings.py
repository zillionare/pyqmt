"""qmt-server runtime settings."""

import json
from dataclasses import dataclass, asdict
from pathlib import Path

from pyqmt.config import cfg


@dataclass
class QmtServerSettings:
    """qmt-server settings."""

    qmt_account_id: str = ""
    qmt_path: str = ""
    xtdata_path: str = ""

    @property
    def is_configured(self) -> bool:
        """Whether core qmt settings are configured."""
        return bool(self.qmt_account_id) and bool(self.qmt_path)


def _settings_path() -> Path:
    home = Path(cfg.home).expanduser()
    folder = home / "qmt_server"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "settings.json"


def load_settings() -> QmtServerSettings:
    """Load settings from file."""
    path = _settings_path()
    if not path.exists():
        return QmtServerSettings()
    data = json.loads(path.read_text(encoding="utf-8"))
    return QmtServerSettings(
        qmt_account_id=str(data.get("qmt_account_id", "")).strip(),
        qmt_path=str(data.get("qmt_path", "")).strip(),
        xtdata_path=str(data.get("xtdata_path", "")).strip(),
    )


def save_settings(settings: QmtServerSettings) -> QmtServerSettings:
    """Persist settings to file."""
    path = _settings_path()
    path.write_text(
        json.dumps(asdict(settings), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return settings
