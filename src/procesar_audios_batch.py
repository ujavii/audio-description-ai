import os
import csv
import time
import re
import unicodedata
import subprocess
import sys
from pathlib import Path as _Path
from datetime import datetime

# ====== Rutas y ajustes centralizados ======
_THIS_DIR = _Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.config import (
    AUDIOS_DIR, OUTPUTS_DIR, TRANSCRIPCIONES_DIR,
    DEVICE, FW_COMPUTE_TYPE, configure_pydub_ffmpeg_if_needed, TEMP_DIR,
    FW_MODEL_SIZE, WHISPER_MODEL_SIZE,
)
from pydub.utils import mediainfo

configure_pydub_ffmpeg_if_needed()

# ====== Muestra el modelo Whisper configurado ======
print(f"[Modelos] faster-whisper={FW_MODEL_SIZE} ({FW_COMPUTE_TYPE}) | whisper={WHISPER_MODEL_SIZE} | device={DEVICE}")

# ========================
# Configuración
# ========================
from analisis_api import extraer_metadatos_api

# Variable global para el estado de Faster Whisper
FASTER_WHISPER_AVAILABLE = False

try:
    from faster_whisper import WhisperModel
    FASTER_WHISPER_AVAILABLE = True
except ImportError:
    FASTER_WHISPER_AVAILABLE = False
    try:
        import whisper  # para fallback
        print("Faster Whisper no está instalado. Usando Whisper normal.")
        print("   Para mejor rendimiento, instala Faster Whisper: pip install faster-whisper")
    except ImportError:
        raise ImportError("Error: No se encontró ni Faster Whisper ni Whisper instalado. "
                          "Instala al menos uno con: pip install faster-whisper o pip install openai-whisper")

# ========================
# DECODIFICACIÓN (ajusta aquí)
# ========================
DECODING_MODE = "auto"                  # opciones: "auto", "greedy", "beam", "beam5", "bestof5", "beam5_relaxed"
DECODING_BEAM_SIZE = 5                  # usado si DECODING_MODE == "beam"
DECODING_BEST_OF = 5                    # usado si DECODING_MODE == "bestof5"
DECODING_TEMPERATURE = 0.2              # usado si DECODING_MODE == "bestof5"
DECODING_VAD = True                     # solo aplica a faster-whisper
AUTO_TRIM_LEADING_SILENCE = True        # recorta silencio inicial si todos los intentos fallan

print(f"Perfil de decodificación: {DECODING_MODE} | beam={DECODING_BEAM_SIZE} | "
      f"best_of={DECODING_BEST_OF} | temp={DECODING_TEMPERATURE} | VAD={'on' if DECODING_VAD else 'off'}")

# ========================
# Orden natural (Windows-like)
# ========================
def _strip_accents(s: str) -> str:
    try:
        import unicodedata as _ud
        return ''.join(ch for ch in _ud.normalize('NFKD', s) if not _ud.combining(ch))
    except Exception:
        return s

def _natural_key(s: str):
    base = _strip_accents(s).casefold()
    parts = re.split(r'(\d+)', base)
    key = []
    for p in parts:
        key.append(int(p) if p.isdigit() else p)
    return key

def natural_sort(lista):
    ordenada = sorted(lista, key=_natural_key)
    print("Orden aplicada: natural (Windows-like).")
    return ordenada

# ========================
# Helpers
# ========================
def _fmt_hms(seconds: float) -> str:
    """Convierte segundos (float) a 'hh:mm:ss' redondeando al segundo más cercano."""
    total = int(round(seconds))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

def _fmt_secs(s):
    horas = int(s // 3600)
    minutos = int((s % 3600) // 60)
    segs = int(s % 60)
    return f"{horas:01d}:{minutos:02d}:{segs:02d}"

def _today_date_iso():
    return datetime.now().date().isoformat()

def _norm_lista(v, default="No indica"):
    if isinstance(v, list):
        v = [x for x in v if x]
        return ", ".join(v) if v else default
    return v if v else default

def _map_canal(ch):
    # Devuelve "1 (Monaural)" / "2 (Estereofónico)" / "n canales"
    try:
        n = int(ch)
    except Exception:
        return str(ch) if ch else "No indica"
    if n == 1:
        return "Monaural"
    if n == 2:
        return "Estereofónico"
    return f"{n} canales"

def _file_size_mb(ruta):
    try:
        b = os.path.getsize(ruta)
        return round(b / (1024 * 1024), 2)
    except Exception:
        return "No indica"

def _ruta_salida_csv():
    return str((OUTPUTS_DIR / "resultados_transcripciones.csv").resolve())

def _asegurar_header_csv(campos):
    salida_csv = _ruta_salida_csv()
    os.makedirs(os.path.dirname(salida_csv), exist_ok=True)
    if not os.path.exists(salida_csv):
        with open(salida_csv, mode="w", encoding="utf-8-sig", newline="") as f:
            csv.DictWriter(f, fieldnames=campos, delimiter=';').writeheader()

def _append_fila_csv(fila, campos):
    with open(_ruta_salida_csv(), mode="a", encoding="utf-8-sig", newline="") as f:
        csv.DictWriter(f, fieldnames=campos, delimiter=';').writerow(fila)

# ========================
# Perfiles de decodificación
# ========================
def _build_intentos_faster(mode: str):
    if mode == "greedy":
        return [("greedy-vad", dict(beam_size=1, temperature=0, vad_filter=DECODING_VAD, language="es"))]
    if mode == "beam":
        bs = DECODING_BEAM_SIZE or 5
        return [(f"beam{bs}-vad", dict(beam_size=bs, temperature=0, vad_filter=DECODING_VAD, language="es"))]
    if mode == "beam5":
        return [("beam5-vad", dict(beam_size=5, temperature=0, vad_filter=DECODING_VAD, language="es"))]
    if mode == "bestof5":
        return [("best_of5-t0.2-vad", dict(beam_size=1, best_of=max(DECODING_BEST_OF,5), temperature=max(DECODING_TEMPERATURE,0.2),
                                           vad_filter=DECODING_VAD, language="es"))]
    if mode == "beam5_relaxed":
        return [("beam5-vad-relaxed", dict(beam_size=5, temperature=0, vad_filter=DECODING_VAD, language="es",
                                           no_speech_threshold=0.9, log_prob_threshold=-2.0))]
    return [
        ("greedy-vad", dict(beam_size=1, temperature=0, vad_filter=DECODING_VAD, language="es")),
        ("beam5-vad", dict(beam_size=5, temperature=0, vad_filter=DECODING_VAD, language="es")),
        ("best_of5-t0.2-vad", dict(beam_size=1, best_of=5, temperature=0.2, vad_filter=DECODING_VAD, language="es")),
        ("beam5-vad-relaxed", dict(beam_size=5, temperature=0, vad_filter=DECODING_VAD, language="es",
                                   no_speech_threshold=0.9, log_prob_threshold=-2.0)),
    ]

def _build_intentos_whisper(mode: str):
    if mode == "greedy":
        return [("greedy", dict(beam_size=1, temperature=0, language="es"))]
    if mode == "beam":
        bs = DECODING_BEAM_SIZE or 5
        return [(f"beam{bs}", dict(beam_size=bs, temperature=0, language="es"))]
    if mode == "beam5":
        return [("beam5", dict(beam_size=5, temperature=0, language="es"))]
    if mode == "bestof5":
        return [("best_of5-t0.2", dict(beam_size=1, best_of=max(DECODING_BEST_OF,5), temperature=max(DECODING_TEMPERATURE,0.2),
                                       language="es"))]
    if mode == "beam5_relaxed":
        return [("beam5-relaxed", dict(beam_size=5, temperature=0, language="es",
                                       no_speech_threshold=0.9, logprob_threshold=-2.0))]
    return [
        ("greedy", dict(beam_size=1, temperature=0, language="es")),
        ("beam5", dict(beam_size=5, temperature=0, language="es")),
        ("best_of5-t0.2", dict(beam_size=1, best_of=5, temperature=0.2, language="es")),
        ("beam5-relaxed", dict(beam_size=5, temperature=0, language="es",
                               no_speech_threshold=0.9, logprob_threshold=-2.0)),
    ]

# ========================
# Transcripción (FW preferido + fallback)
# ========================
def _merge_cascade(preferidos, auto):
    out, seen = [], set()
    for desc, kwargs in (preferidos + auto):
        if desc not in seen:
            out.append((desc, kwargs)); seen.add(desc)
    return out

def _transcribir_intentos_faster(model, ruta_audio):
    preferidos = _build_intentos_faster(DECODING_MODE)
    cascada_auto = _build_intentos_faster("auto")
    intentos = _merge_cascade(preferidos, cascada_auto) if DECODING_MODE != "auto" else preferidos
    for i, (desc, kwargs) in enumerate(intentos, start=1):
        try:
            print(f"   Intento {i}: {desc} -> {kwargs}")
            segments, _info = model.transcribe(ruta_audio, **kwargs)
            texto = " ".join([seg.text for seg in segments]).replace('\x00', ' ').strip()
            if texto:
                print(f"   Transcripción con '{desc}'")
                return texto
            print("   Texto vacío; probando siguiente…")
        except Exception as e:
            print(f"   Falla '{desc}': {e}")
    return ""

def _transcribir_intentos_whisper(modelo, ruta_audio):
    preferidos = _build_intentos_whisper(DECODING_MODE)
    cascada_auto = _build_intentos_whisper("auto")
    intentos = _merge_cascade(preferidos, cascada_auto) if DECODING_MODE != "auto" else preferidos
    for i, (desc, kwargs) in enumerate(intentos, start=1):
        try:
            print(f"   Intento {i} (whisper): {desc} -> {kwargs}")
            res = modelo.transcribe(ruta_audio, **kwargs)
            texto = res.get("text", "").replace('\x00', " ").strip()
            if texto:
                print(f"   Transcripción Whisper '{desc}'")
                return texto
            print("   Texto vacío; probando siguiente…")
        except Exception as e:
            print(f"   Falla Whisper '{desc}': {e}")
    return ""

def transcribir_audio(ruta_audio):
    global FASTER_WHISPER_AVAILABLE
    device = DEVICE

    if FASTER_WHISPER_AVAILABLE:
        print(f"Faster Whisper ({FW_MODEL_SIZE}) en {device.upper()}: {ruta_audio}")
        try:
            model  = WhisperModel(FW_MODEL_SIZE, device=device, compute_type=FW_COMPUTE_TYPE)
            texto = _transcribir_intentos_faster(model, ruta_audio)
            if not texto and AUTO_TRIM_LEADING_SILENCE:
                recortado = _trim_leading_silence(ruta_audio)
                if recortado:
                    texto = _transcribir_intentos_faster(model, recortado)
            if texto:
                return texto
            print("   FW sin texto; paso a Whisper normal…")
            FASTER_WHISPER_AVAILABLE = False
        except Exception as e:
            print(f"Error Faster Whisper: {e} → Whisper normal")
            FASTER_WHISPER_AVAILABLE = False

    try:
        import whisper
        print(f"Whisper ({WHISPER_MODEL_SIZE}) en {device.upper()}: {ruta_audio}")
        modelo = whisper.load_model(WHISPER_MODEL_SIZE, device=device)
        texto = _transcribir_intentos_whisper(modelo, ruta_audio)
        if not texto and AUTO_TRIM_LEADING_SILENCE:
            recortado = _trim_leading_silence(ruta_audio)
            if recortado:
                texto = _transcribir_intentos_whisper(modelo, recortado)
        return texto
    except Exception as e:
        raise Exception(f"Error con Whisper normal: {e}")

# ========================
# Metadatos técnicos (nuevos nombres)
# ========================
def extraer_metadatos_tecnicos(ruta_audio):
    info = mediainfo(ruta_audio) or {}
    dur_val = info.get("duration") or info.get("duration, ")
    try:
        dur_seg = float(dur_val) if dur_val is not None else 0.0
    except Exception:
        dur_seg = 0.0

    tasa_bits = info.get("bit_rate", "")
    tasa_kbps = "No indica"
    try:
        if isinstance(tasa_bits, (int, float)) or (isinstance(tasa_bits, str) and tasa_bits.isdigit()):
            tasa_kbps = str(round(int(tasa_bits) / 1000))
    except Exception:
        tasa_kbps = "No indica"

    format_name = info.get("format_name", "No indica")
    canales = info.get("channels", "No indica")

    return {
        "Formato": format_name,
        "Duración (hh:mm:ss)": _fmt_secs(dur_seg),
        "Tasa de bits (kbps)": tasa_kbps,
        "Canal de audio": _map_canal(canales),
        "Volumen (MB)": _file_size_mb(ruta_audio),
    }

# ========================
# Procesar un archivo (transcribe + API + CSV)
# ========================
def _trim_leading_silence(src_path: str):
    try:
        tmp_dir = (TEMP_DIR if TEMP_DIR else (OUTPUTS_DIR / "tmp"))
        os.makedirs(str(tmp_dir), exist_ok=True)
        base = os.path.splitext(os.path.basename(src_path))[0]
        dst = str((tmp_dir / f"{base}_nosilence.wav").resolve())
        cmd = [
            "ffmpeg", "-y", "-i", src_path,
            "-af", "silenceremove=start_periods=1:start_duration=0.5:start_threshold=-45dB",
            "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
            dst
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if proc.returncode == 0 and os.path.exists(dst):
            print("   Silencio inicial recortado (ffmpeg).")
            return dst
        print("   ffmpeg no pudo recortar silencio automáticamente.")
        return None
    except Exception as e:
        print(f"   Error recortando silencio: {e}")
        return None

def procesar_archivo(audio_path, responsable="No indica"):
    nombre = os.path.basename(audio_path)
    print(f"\nProcesando: {nombre}")

    # Encabezado / defaults (según especificación)
    fila = {
        "Archivo": nombre,
        "Programa": "",
        "Título": "",
        "Fecha": "",
        "Clase documental": "Sonoro",
        "Medio de almacenamiento": "Audio digital",
        "Volumen (MB)": "",
        "Soporte": "Digital",
        "Formato": "",
        "Duración (hh:mm:ss)": "",
        "Tasa de bits (kbps)": "",
        "Canal de audio": "",
        "Producción": "",
        "Conducción": "",
        "Invitados(as)": "",
        "Apoyo técnico": "",
        "Forma de ingreso": "Producido",
        "Contenido": "",
        "Género": "",
        "Condiciones de acceso": "Público",
        "Lengua": "",
        "Palabras clave": "",
        "Número de gestión": "No indica",
        "Información adicional": "No indica",
        "Responsable de la descripción": responsable,
        "Fecha de la descripción": _today_date_iso(),
    }

    try:
        t0 = time.perf_counter()
        transcripcion = transcribir_audio(audio_path)
        t1 = time.perf_counter()
        print(f"   Transcripción lista en {_fmt_hms(t1 - t0)}")

        # Metadatos técnicos
        fila.update(extraer_metadatos_tecnicos(audio_path))

        # Contenido / descriptores vía API o heurísticas
        if transcripcion:
            print("Enviando a la API…")
            t2 = time.perf_counter()
            meta = extraer_metadatos_api(transcripcion) or {}
            t3 = time.perf_counter()
            print(f"   Descripción (API) en {_fmt_hms(t3 - t2)}")

            fila.update({
                "Programa": meta.get("Programa", ""),
                "Título": meta.get("Título", ""),
                "Contenido": meta.get("Contenido", ""),
                "Producción": _norm_lista(meta.get("Producción", ["No indica"])),
                "Conducción": _norm_lista(meta.get("Conducción", [])),
                "Invitados(as)": _norm_lista(meta.get("Invitados(as)", [])),
                "Apoyo técnico": _norm_lista(meta.get("Apoyo técnico", ["No indica"])),
                "Género": meta.get("Género", ""),
                "Lengua": meta.get("Lengua", ""),
                "Palabras clave": (
                    ", ".join(meta.get("Palabras clave", []))
                    if isinstance(meta.get("Palabras clave", []), list) else (meta.get("Palabras clave", "") or "")
                ),
            })
        else:
            print("Transcripción vacía: solo se guardan metadatos técnicos y defaults.")

        return fila, True

    except Exception as e:
        print(f"Error procesando {nombre}: {e}")
        return fila, False

# ========================
# Main por lotes
# ========================
if __name__ == "__main__":
    _resp = input("Responsable de la descripción (Enter para omitir): ").strip()
    responsable = _resp if _resp else "No indica"

    carpeta_audios = str(AUDIOS_DIR.resolve())

    campos = [
        "Archivo", "Programa", "Título", "Fecha",
        "Clase documental", "Medio de almacenamiento", "Volumen (MB)", "Soporte",
        "Formato", "Duración (hh:mm:ss)", "Tasa de bits (kbps)", "Canal de audio",
        "Producción", "Conducción", "Invitados(as)", "Apoyo técnico",
        "Forma de ingreso", "Contenido", "Género", "Condiciones de acceso",
        "Lengua", "Palabras clave", "Número de gestión", "Información adicional",
        "Responsable de la descripción", "Fecha de la descripción",
    ]

    _asegurar_header_csv(campos)

    try:
        archivos = os.listdir(carpeta_audios)
    except FileNotFoundError:
        print(f"Carpeta de audios no encontrada: {carpeta_audios}")
        archivos = []

    audios = [f for f in archivos if f.lower().endswith((".mp3", ".wav", ".m4a", ".flac"))]
    audios = natural_sort(audios)

    total = len(audios)
    exitos = 0
    fallos = 0

    print(f"Iniciando procesamiento por lotes ({total} archivo(s))…")
    t_total = time.perf_counter()

    for idx, archivo in enumerate(audios, start=1):
        t_ini = time.perf_counter()
        ruta = os.path.join(carpeta_audios, archivo)
        fila, ok = procesar_archivo(ruta, responsable)

        try:
            _append_fila_csv(fila, campos)
            print(f"({idx}/{total}) Guardado en CSV: {archivo}")
        except Exception as e:
            ok = False
            print(f"Error al guardar en CSV para {archivo}: {e}")

        if ok: exitos += 1
        else:  fallos += 1

        print(f"Tiempo {archivo}: {_fmt_hms(time.perf_counter() - t_ini)}")

    print("Lote completado.")
    print(f"   Éxitos: {exitos}")
    print(f"   Fallos: {fallos}")
    print(f"   Tiempo total: {_fmt_hms(time.perf_counter() - t_total)}")
    print(f"   Archivo CSV: {_ruta_salida_csv()}")
