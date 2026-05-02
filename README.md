# Audio Description AI

Herramienta CLI para transcripción automática y descripción archivística de documentos sonoros mediante IA.

Procesa archivos de audio (individualmente o en lote), transcribe su contenido con Whisper y genera automáticamente los campos descriptivos a partir del análisis de la transcripción con un modelo de lenguaje.

---

## Características

- **Transcripción automática** con `faster-whisper` (CTranslate2), con soporte GPU/CPU automático
- **Análisis IA multi-proveedor**: OpenAI, Anthropic/Claude, Google Gemini, o cualquier API compatible con OpenAI (DeepSeek, Groq, Mistral, Ollama, etc.)
- **Extracción de metadatos técnicos** del audio (formato, duración, tasa de bits, canal)
- **Exportación a CSV** con los 26 campos del esquema descriptivo
- **Glosario de entidades** opcional para normalizar nombres en las transcripciones

---

## Requisitos

- **Python 3.11** recomendado
- **FFmpeg** instalado en el sistema (en PATH) o definido en `FFMPEG_PATH` en `.env`
- GPU NVIDIA opcional (para transcripción con CUDA; si no hay, usa CPU automáticamente)
- Una API key del proveedor de IA que desees usar

---

## Instalación / Activación

En PowerShell dentro de la carpeta del proyecto:

```powershell
.\setup_env.ps1
# o
.\activar_venv.ps1
```

El script:
1. Crea/activa el `venv`
2. Instala `requirements.txt` (CPU por defecto)
3. Si detecta `nvidia-smi`, actualiza PyTorch al canal CUDA correcto (cu124/cu121/cu118)
4. Corre una prueba de CUDA y `faster-whisper`

---

## Configuración

### Variables de entorno (`.env`)

Copia `.env.example` como `.env` y completa los valores:

```
# Proveedor de IA (openai por defecto)
AI_PROVIDER=openai

# API key del proveedor elegido
OPENAI_API_KEY=sk-proj-...
```

### Proveedor de IA

| Proveedor | Variable | Ejemplo de modelo |
|---|---|---|
| `openai` | `OPENAI_API_KEY` | `gpt-4o-mini`, `gpt-4o` |
| `anthropic` | `ANTHROPIC_API_KEY` | `claude-sonnet-4-6`, `claude-haiku-4-5-20251001` |
| `gemini` | `GOOGLE_API_KEY` | `gemini-2.0-flash`, `gemini-1.5-pro` |
| `openai_compatible` | `OPENAI_COMPATIBLE_API_KEY` + `OPENAI_COMPATIBLE_BASE_URL` | DeepSeek, Groq, Mistral, Ollama |

Para cambiar de proveedor, modifica `AI_PROVIDER` en `.env`. Para cambiar el modelo específico, usa `AI_MODEL`.

### Rutas personalizadas

Todas las rutas viven en `src/config.py` y se pueden sobrescribir en `.env`:

```
AUDIOS_DIR=C:\...\mis_audios
OUTPUTS_DIR=C:\...\outputs
TRANSCRIPCIONES_DIR=C:\...\transcripciones
FW_MODEL_SIZE=medium
FFMPEG_PATH=C:\ffmpeg\bin\ffmpeg.exe
```

---

## Uso

- **Un solo archivo**: dejar `AUDIO_PATH` vacío en `src/procesar_audios_single.py` para procesar el primero en `audios/`, o indicar la ruta completa:
  ```powershell
  python .\src\procesar_audios_single.py
  ```
- **Por lotes**: procesa todo lo de `audios/` en orden natural:
  ```powershell
  python .\src\procesar_audios_batch.py
  ```

Los resultados se guardan en `outputs/resultados_transcripciones.csv` (delimitador `;`).

---

## Glosario de entidades (opcional)

La herramienta admite un glosario de entidades para mejorar la identificación de nombres de personas y organizaciones en las transcripciones. Cuando una variante (error tipográfico, abreviatura, transliteración) coincide con una entrada del glosario, la herramienta la reemplaza por la forma canónica.

**El glosario real no se incluye en el repositorio** — está pensado para ser creado y adaptado según el contexto de cada implementación, ya que los nombres relevantes varían según la institución, el programa o el acervo que se describe.

Para utilizarlo, copia `data/glosario_nombres.example.json` como `data/glosario_nombres.json` y adapta su contenido:

```json
{
  "Nombre Canónico Completo": ["variante 1", "variante con error", "abreviatura"],
  "Otra Persona u Organización": ["alias", "otra variante"]
}
```

Si el archivo no existe, la herramienta funciona sin él sin ningún error.

---

## Estructura del proyecto

```
audio-description-ai/
├── src/
│   ├── config.py                    # Rutas y ajustes centralizados
│   ├── analisis_api.py              # Análisis IA multi-proveedor
│   ├── procesar_audios_single.py    # Procesamiento de un archivo
│   └── procesar_audios_batch.py     # Procesamiento en lote
├── audios/                          # Coloca aquí los archivos a procesar
├── outputs/                         # CSV y archivos generados
├── transcripciones/                 # Transcripciones en bruto (opcional)
├── data/
│   └── glosario_nombres.example.json
├── .env.example                     # Plantilla de variables de entorno
├── requirements.txt
├── setup_env.ps1
└── activar_venv.ps1
```

---

## Notas

- Si la API key no está configurada o `analisis_api.py` falla, los campos descriptivos quedan vacíos en el CSV — la transcripción y los metadatos técnicos se guardan de todas formas.
- Los modelos de Whisper se descargan automáticamente en la primera ejecución y se almacenan en caché en `models/`.

---

## Solución de problemas

**`torch==...+cuXXX` no se instala** → el script ya usa el índice de PyTorch cuando detecta `+cu`. Alternativamente, agrega en `requirements.txt`:
```
--extra-index-url https://download.pytorch.org/whl/cu121
```
(ajusta a `cu124`/`cu118` según tu driver).

**FFmpeg no encontrado** → instala FFmpeg y ponlo en PATH o define `FFMPEG_PATH` en `.env`.

**GPU no utilizada** → confirma con:
```powershell
nvidia-smi
python -c "import torch; print(torch.version.cuda, torch.cuda.is_available())"
```

**Proveedor `openai_compatible` no conecta** → verifica que `OPENAI_COMPATIBLE_BASE_URL` esté correctamente definido en `.env`.

---

## Licencia

Apache 2.0 — ver [LICENSE](LICENSE)

---

## Crédito

Desarrollado por [Javier Umaña Ureña](https://github.com/ujavii)
