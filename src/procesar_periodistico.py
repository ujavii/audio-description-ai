import os
import csv
import time
import sys
from pathlib import Path as _Path
from datetime import datetime

_THIS_DIR = _Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.config import AUDIOS_DIR, OUTPUTS_DIR, configure_pydub_ffmpeg_if_needed
from analisis_periodistico import extraer_metadatos_periodisticos, PROYECTOS
from procesar_audios_batch import transcribir_audio, natural_sort, _fmt_hms

configure_pydub_ffmpeg_if_needed()

# ========================
# Campos por proyecto
# ========================
_CAMPOS_COMUN = [
    "Archivo", "Proyecto", "Título", "Fecha",
    "Tema principal", "Subtemas",
    "Actores y figuras públicas", "Fuentes citadas",
    "Citas textuales", "Datos numéricos",
    "Palabras clave", "Resumen",
    "Responsable de la descripción", "Fecha de la descripción",
]

_CAMPOS_DOBLE_CHECK = [
    "Archivo", "Proyecto", "Título", "Fecha",
    "Tema principal", "Subtemas",
    "Actores y figuras públicas", "Fuentes citadas",
    "Citas textuales", "Afirmaciones verificables", "Datos numéricos",
    "Palabras clave", "Resumen",
    "Responsable de la descripción", "Fecha de la descripción",
]


def _campos(proyecto):
    return _CAMPOS_DOBLE_CHECK if proyecto == "Doble Check" else _CAMPOS_COMUN


def _ruta_csv(proyecto):
    slug = proyecto.lower().replace(" ", "_")
    return str((OUTPUTS_DIR / f"{slug}.csv").resolve())


def _today():
    return datetime.now().date().isoformat()


def _asegurar_header(campos, ruta):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    if not os.path.exists(ruta):
        with open(ruta, "w", encoding="utf-8-sig", newline="") as f:
            csv.DictWriter(f, fieldnames=campos, delimiter=";").writeheader()


def _guardar_fila(fila, campos, ruta):
    with open(ruta, "a", encoding="utf-8-sig", newline="") as f:
        csv.DictWriter(f, fieldnames=campos, delimiter=";").writerow(fila)


def _fila_vacia(nombre, proyecto, responsable):
    fila = {
        "Archivo": nombre,
        "Proyecto": proyecto,
        "Título": "",
        "Fecha": "",
        "Tema principal": "",
        "Subtemas": "",
        "Actores y figuras públicas": "",
        "Fuentes citadas": "",
        "Citas textuales": "",
        "Datos numéricos": "",
        "Palabras clave": "",
        "Resumen": "",
        "Responsable de la descripción": responsable,
        "Fecha de la descripción": _today(),
    }
    if proyecto == "Doble Check":
        fila["Afirmaciones verificables"] = ""
    return fila


# ========================
# Procesamiento
# ========================
def procesar_archivo(audio_path, proyecto, responsable="No indica"):
    nombre = os.path.basename(audio_path)
    print(f"\nProcesando: {nombre}")
    fila = _fila_vacia(nombre, proyecto, responsable)

    try:
        t0 = time.perf_counter()
        transcripcion = transcribir_audio(audio_path)
        print(f"   Transcripción lista en {_fmt_hms(time.perf_counter() - t0)}")

        if transcripcion:
            print("Enviando a la API…")
            t1 = time.perf_counter()
            meta = extraer_metadatos_periodisticos(transcripcion, proyecto) or {}
            print(f"   Análisis (API) en {_fmt_hms(time.perf_counter() - t1)}")
            fila.update(meta)
        else:
            print("Transcripción vacía: no se envía a la API.")

        return fila, True

    except Exception as e:
        print(f"Error procesando {nombre}: {e}")
        return fila, False


# ========================
# Prompts de inicio
# ========================
def _pedir_proyecto():
    print("\nProyecto:")
    for i, p in enumerate(PROYECTOS, start=1):
        print(f"  {i}. {p}")
    while True:
        sel = input("Selecciona (1/2): ").strip()
        if sel.isdigit() and 1 <= int(sel) <= len(PROYECTOS):
            return PROYECTOS[int(sel) - 1]
        print("Opción no válida.")


def _pedir_responsable():
    val = input("Responsable de la descripción (Enter para omitir): ").strip()
    return val if val else "No indica"


# ========================
# Main
# ========================
if __name__ == "__main__":
    proyecto = _pedir_proyecto()
    responsable = _pedir_responsable()

    campos = _campos(proyecto)
    ruta_csv = _ruta_csv(proyecto)
    _asegurar_header(campos, ruta_csv)

    carpeta = str(AUDIOS_DIR.resolve())
    try:
        archivos = os.listdir(carpeta)
    except FileNotFoundError:
        print(f"Carpeta de audios no encontrada: {carpeta}")
        sys.exit(1)

    audios = natural_sort([f for f in archivos if f.lower().endswith((".mp3", ".wav", ".m4a", ".flac"))])
    total = len(audios)

    if not audios:
        print(f"No hay audios en: {carpeta}")
        sys.exit(0)

    print(f"\nProyecto: {proyecto} | Archivos a procesar: {total}")
    t_total = time.perf_counter()
    exitos = fallos = 0

    for idx, archivo in enumerate(audios, start=1):
        ruta = os.path.join(carpeta, archivo)
        fila, ok = procesar_archivo(ruta, proyecto, responsable)

        try:
            _guardar_fila(fila, campos, ruta_csv)
            print(f"({idx}/{total}) Guardado: {archivo}")
        except Exception as e:
            ok = False
            print(f"Error guardando {archivo}: {e}")

        if ok:
            exitos += 1
        else:
            fallos += 1

    print(f"\nLote completado — Éxitos: {exitos} | Fallos: {fallos}")
    print(f"Tiempo total: {_fmt_hms(time.perf_counter() - t_total)}")
    print(f"CSV: {ruta_csv}")
