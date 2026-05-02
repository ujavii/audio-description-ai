GUÍA RÁPIDA — Sistema de Transcripción/Descripción

1) Abrir PowerShell en la carpeta del proyecto (System/).
2) Ejecutar:
   .\setup_env.ps1
   (crea/activa venv, instala dependencias y valida CUDA automáticamente)
3) Colocar audios en la carpeta: System\audios
4) Procesar:
   - Un solo archivo:
       python .\src\procesar_audios_single.py
     (edite AUDIO_PATH dentro del script o déjelo vacío para tomar el primero)
   - Por lotes (todos los audios):
       python .\src\procesar_audios_batch.py
5) Resultados:
   - CSV: System\outputs\resultados_transcripciones.csv (delimitador ;)

Configuración avanzada:
- Editar rutas y opciones en: src\config.py
- Opcional: crear un archivo .env en System\ con variables como:
    AUDIOS_DIR=... 
    OUTPUTS_DIR=...
    OPENAI_API_KEY=...
    OPENAI_MODEL=gpt-4o-mini
    FFMPEG_PATH=C:\ffmpeg\bin\ffmpeg.exe

Atajo:
- .\activar_venv.ps1 → ejecuta setup_env.ps1 para preparar/activar el entorno.