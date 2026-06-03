import tempfile
from pathlib import Path

from paper_radar.db import PaperRadarDb


class TempDbMixin:
    _tmp: tempfile.TemporaryDirectory

    def make_db(self) -> PaperRadarDb:
        self._tmp = tempfile.TemporaryDirectory()
        db = PaperRadarDb(Path(self._tmp.name) / "radar.sqlite3")
        db.initialize()
        return db

    def cleanup_db(self) -> None:
        self._tmp.cleanup()
