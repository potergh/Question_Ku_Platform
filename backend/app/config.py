"""Application configuration — path settings only. AI config lives in DB."""

from pathlib import Path
from pydantic_settings import BaseSettings


# Project root = d:\家教\Question_Ku_Platform
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
OCR_OUTPUT_DIR = DATA_DIR / "ocr_output"
EXPORT_DIR = DATA_DIR / "exports"
DB_PATH = DATA_DIR / "db.sqlite3"

# OCR packages directory
PACKAGES_DIR = BASE_DIR / "packages"


class Settings(BaseSettings):
    """Runtime settings (non-AI). AI settings are in the DB Settings table."""

    base_dir: Path = BASE_DIR
    data_dir: Path = DATA_DIR
    upload_dir: Path = UPLOAD_DIR
    ocr_output_dir: Path = OCR_OUTPUT_DIR
    export_dir: Path = EXPORT_DIR
    db_path: Path = DB_PATH

    @property
    def database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.db_path}"

    def ensure_dirs(self):
        """Create all required directories if they don't exist."""
        for d in [self.data_dir, self.upload_dir, self.ocr_output_dir, self.export_dir]:
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
