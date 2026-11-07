from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="NEWWORLDS_")

    database_url: str = "postgresql://newworlds:newworlds@localhost:5433/newworlds"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    prepared_data_dir: str = str(REPO_ROOT / "data" / "prepared")
    cache_dir: str = str(REPO_ROOT / "data" / "cache")
    # NASA FIRMS MAP_KEY (free, https://firms.modaps.eosdis.nasa.gov/api/map_key/). Fires are off without it.
    firms_map_key: str | None = None
    overpass_url: str = "https://overpass-api.de/api/interpreter"


settings = Settings()
