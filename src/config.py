"""
Config centralizado de rutas y ajustes de ejecución.

Ubicación esperada de este archivo:
    <proyecto>\System\src\config.py

Estructura esperada del proyecto:
    System/
      audios/
      outputs/
      transcripciones/
      src/
        config.py   <-- este archivo
      venv/
    (opcional) .env  <-- variables para sobrescribir rutas y ajustes
"""

from __future__ import annotations
from pathlib import Path
import os

# -----------------------------------------------------------------------------
# Raíz del proyecto (carpeta "System")
# -----------------------------------------------------------------------------
# Este archivo vive en System/src/config.py, por eso subimos 1 nivel.
PROJECT_ROOT: Path = Path(__file__).resolve().parents[1]

# Carga variables desde .env si existe (no es obligatorio)
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except Exception:
    pass

def _env_path(var_name: str, default: Path) -> Path:
    """Lee una ruta desde el entorno; si no existe, usa el default."""
    val = os.getenv(var_name, "").strip()
    return Path(val).expanduser() if val else default

# -----------------------------------------------------------------------------
# Rutas principales (se pueden sobrescribir vía .env o variables de entorno)
# -----------------------------------------------------------------------------
AUDIOS_DIR: Path            = _env_path("AUDIOS_DIR",            PROJECT_ROOT / "audios")
OUTPUTS_DIR: Path           = _env_path("OUTPUTS_DIR",           PROJECT_ROOT / "outputs")
TRANSCRIPCIONES_DIR: Path   = _env_path("TRANSCRIPCIONES_DIR",   PROJECT_ROOT / "transcripciones")
MODELS_DIR: Path            = _env_path("MODELS_DIR",            PROJECT_ROOT / "models")  # opcional
LOGS_DIR: Path              = _env_path("LOGS_DIR",              PROJECT_ROOT / "logs")    # opcional
TEMP_DIR: Path              = _env_path("TEMP_DIR",              PROJECT_ROOT / "tmp")     # opcional

# -----------------------------------------------------------------------------
# Utilidades de rutas
# -----------------------------------------------------------------------------
def ensure_dirs() -> None:
    """Crea las carpetas clave si no existen."""
    for d in [AUDIOS_DIR, OUTPUTS_DIR, TRANSCRIPCIONES_DIR, MODELS_DIR, LOGS_DIR, TEMP_DIR]:
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception:
            # No romper si alguna no se puede crear (p. ej., MODELS_DIR opcional)
            pass

def win_long(path: Path) -> str:
    """
    Devuelve la ruta con prefijo '\\\\?\\' en Windows para soportar rutas largas.
    Úsala solo cuando llames a APIs del sistema que fallen por longitud.
    """
    s = str(path.resolve())
    if os.name == "nt" and not s.startswith("\\\\?\\"):
        return "\\\\?\\" + s
    return s

# -----------------------------------------------------------------------------
# Ajustes de ejecución (CPU/GPU auto) para Whisper / faster-whisper
# -----------------------------------------------------------------------------
try:
    import torch
    DEVICE: str = "cuda" if torch.cuda.is_available() else "cpu"
except Exception:
    DEVICE = "cpu"

# Para faster-whisper: fp16 en GPU, int8 en CPU
FW_MODEL_SIZE = os.getenv("FW_MODEL_SIZE", "medium")             # Opciones: tiny, base, small, medium, large-v1, large-v2, large-v3
FW_COMPUTE_TYPE: str = "float16" if DEVICE == "cuda" else "int8"

# Para whisper clásico (opcional): tamaño de modelo por defecto
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "medium")   # Opciones: tiny, base, small, medium, large-v1, large-v2, large-v3

# -----------------------------------------------------------------------------
# ffmpeg (pydub / whisper clásico lo necesitan). Dejar vacío si ya está en PATH
# -----------------------------------------------------------------------------
FFMPEG_PATH: str = os.getenv("FFMPEG_PATH", "").strip()

def configure_pydub_ffmpeg_if_needed() -> None:
    """Configura pydub para usar FFMPEG_PATH si está definido."""
    if FFMPEG_PATH:
        try:
            from pydub import AudioSegment
            AudioSegment.converter = FFMPEG_PATH
        except Exception:
            pass  # No hacemos hard-fail si pydub no está instalado

# Llamada opcional en import: crear carpetas para evitar sorpresas
ensure_dirs()