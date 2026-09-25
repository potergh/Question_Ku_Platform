"""Application configuration — path settings only. AI config lives in DB."""

from pathlib import Path
from pydantic_settings import BaseSettings


# 项目根 = backend/app/config.py 上溯三级。所有路径都由 __file__ 推导，
# 因此整包可以放在任意目录下运行（部署位置无关）；不要改成硬编码路径。
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
OCR_OUTPUT_DIR = DATA_DIR / "ocr_output"
DB_PATH = DATA_DIR / "db.sqlite3"

# OCR packages directory
PACKAGES_DIR = BASE_DIR / "packages"


class Settings(BaseSettings):
    """Runtime settings (non-AI). AI settings are in the DB Settings table."""

    base_dir: Path = BASE_DIR
    data_dir: Path = DATA_DIR
    upload_dir: Path = UPLOAD_DIR
    ocr_output_dir: Path = OCR_OUTPUT_DIR
    db_path: Path = DB_PATH

    @property
    def database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.db_path}"

    def ensure_dirs(self):
        """Create all required directories if they don't exist."""
        for d in [self.data_dir, self.upload_dir, self.ocr_output_dir]:
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
