import os
import json
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent

load_dotenv(BASE_DIR / ".env")

_CONFIG_PATH = BASE_DIR / "config.json"

# Cache con validacion por mtime: get_config() se llama en cada tool, y asi no
# releemos el JSON del disco cada vez. Si editas config.json, el cambio se
# aplica igual (mtime cambia -> recarga).
_config: dict | None = None
_config_mtime: float | None = None


def get_config() -> dict:
    global _config, _config_mtime
    try:
        mtime = _CONFIG_PATH.stat().st_mtime
    except OSError:
        return {}
    if _config is None or mtime != _config_mtime:
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                _config = json.load(f)
            _config_mtime = mtime
        except (OSError, ValueError) as e:
            if _config is None:
                print(f"[ERROR] No se pudo leer config.json: {e}")
                return {}
            # Mantenemos la ultima configuracion valida si el archivo esta roto.
            _config_mtime = mtime
    return _config


def get_env(key: str) -> str | None:
    return os.getenv(key)


def load_config() -> dict:
    """Fuerza una recarga de config.json (ignora el cache)."""
    global _config, _config_mtime
    _config = None
    _config_mtime = None
    return get_config()


def get_setting(section: str, key: str, default=None):
    return get_config().get(section, {}).get(key, default)
