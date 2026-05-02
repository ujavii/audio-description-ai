import os
import json
import re
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL_NAME = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

PROYECTOS = ["Interferencia", "Doble Check"]

_CONTEXTOS = {
    "Interferencia": (
        "Proyecto: INTERFERENCIA — periodismo de investigación y análisis crítico de las "
        "Radioemisoras de la Universidad de Costa Rica.\n"
        "Enfoque: política, coyuntura nacional, temas sociales costarricenses. Contenido de "
        "largo aliento con perspectiva interpretativa y crítica.\n"
        "Prioriza: actores institucionales, argumentos centrales, fuentes y datos que soporten el análisis."
    ),
    "Doble Check": (
        "Proyecto: DOBLE CHECK — verificación de información (fact-checking) de las "
        "Radioemisoras de la Universidad de Costa Rica.\n"
        "Enfoque: comprobar la veracidad de afirmaciones públicas, especialmente de figuras "
        "políticas como el presidente Rodrigo Chaves, y analizar datos y contenido viral.\n"
        "Prioriza: afirmaciones verificables, cifras y estadísticas citadas, fuentes que "
        "respalden o contradigan las declaraciones."
    ),
}

_PROMPT_BASE = """Eres un asistente especializado en análisis periodístico de contenido de radio universitaria costarricense.
Analiza la siguiente transcripción y devuelve únicamente un objeto JSON válido con los campos solicitados.

### INSTRUCCIONES GENERALES
- Devuelve solo JSON válido, sin texto adicional ni bloques Markdown.
- No inventes información que no esté en la transcripción.
- Si un campo no se puede inferir, usa "No indica" para strings o [] para listas.
- Sé preciso y riguroso: prioriza exactitud sobre exhaustividad.

---

### CONTEXTO DEL PROYECTO
{contexto}

---

### CAMPO 1: TÍTULO
- Título del episodio si se menciona explícitamente.
- Si no, genera uno descriptivo de máximo 8 palabras.

### CAMPO 2: TEMA PRINCIPAL
- El tema central abordado, en una frase corta (máx. 10 palabras).

### CAMPO 3: SUBTEMAS
- Lista de temas secundarios o ángulos específicos abordados. Máximo 5.
- Si no hay, [].

### CAMPO 4: ACTORES Y FIGURAS PÚBLICAS
- Lista de personas e instituciones nombradas con relevancia en el contenido.
- Personas: "Nombre Apellido (cargo o institución si se menciona)".
- Instituciones: nombre de la entidad.
- Si no hay, [].

### CAMPO 5: FUENTES CITADAS
- Lista de fuentes referenciadas: estudios, informes, documentos, medios, instituciones como fuente de datos.
- Solo incluir si se menciona explícitamente como fuente.
- Si no hay, [].

### CAMPO 6: CITAS TEXTUALES
- Lista de declaraciones relevantes atribuidas a una persona, textuales o muy cercanas.
- Solo incluir si aportan valor informativo o son noticiables.
- Formato de cada elemento: "Nombre Apellido: \\"texto de la cita\\""
- Máximo 5. Si no hay, [].

### CAMPO 7: DATOS NUMÉRICOS
- Lista de cifras, porcentajes o estadísticas mencionadas con su contexto.
- Formato de cada elemento: "cifra o dato — contexto breve"
- Si no hay, [].
{bloque_verificables}
### CAMPO {n_kw}: PALABRAS CLAVE
- Lista de términos y frases orientados a búsqueda y rastreo léxico futuro.
- Incluir tanto términos simples como frases compuestas relevantes.
- Priorizar expresiones específicas que permitan rastrear temas o actores a lo largo del tiempo.
- Máximo 8, en minúsculas.
- Si no hay, [].

### CAMPO {n_res}: RESUMEN
- Resumen en 3-4 oraciones: argumento central, actores principales y conclusiones si las hay.

---

### ESTRUCTURA DE SALIDA (JSON ÚNICO)
{estructura}
"""

_BLOQUE_VERIFICABLES = """
### CAMPO 8: AFIRMACIONES VERIFICABLES
- Lista de afirmaciones concretas y comprobables hechas por figuras públicas.
- Priorizar declaraciones de políticos o funcionarios que puedan contrastarse con datos.
- Formato de cada elemento: "Nombre Apellido: \\"afirmación textual o parafraseada\\""
- Si no hay, [].

"""

_ESTRUCTURA_BASE = (
    'Devuelve únicamente un objeto JSON con estas claves exactas:\n'
    '- "Título": string\n'
    '- "Tema principal": string\n'
    '- "Subtemas": lista de strings\n'
    '- "Actores y figuras públicas": lista de strings\n'
    '- "Fuentes citadas": lista de strings\n'
    '- "Citas textuales": lista de strings  (formato: "Nombre: \\"cita\\"")\n'
    '- "Datos numéricos": lista de strings  (formato: "dato — contexto")\n'
    '- "Palabras clave": lista de hasta 8 strings en minúsculas\n'
    '- "Resumen": string'
)

_ESTRUCTURA_DC = (
    'Devuelve únicamente un objeto JSON con estas claves exactas:\n'
    '- "Título": string\n'
    '- "Tema principal": string\n'
    '- "Subtemas": lista de strings\n'
    '- "Actores y figuras públicas": lista de strings\n'
    '- "Fuentes citadas": lista de strings\n'
    '- "Citas textuales": lista de strings  (formato: "Nombre: \\"cita\\"")\n'
    '- "Afirmaciones verificables": lista de strings  (formato: "Nombre: \\"afirmación\\"")\n'
    '- "Datos numéricos": lista de strings  (formato: "dato — contexto")\n'
    '- "Palabras clave": lista de hasta 8 strings en minúsculas\n'
    '- "Resumen": string'
)


def _build_prompt(proyecto: str) -> str:
    es_dc = proyecto == "Doble Check"
    return _PROMPT_BASE.format(
        contexto=_CONTEXTOS[proyecto],
        bloque_verificables=_BLOQUE_VERIFICABLES if es_dc else "\n",
        n_kw=9 if es_dc else 8,
        n_res=10 if es_dc else 9,
        estructura=_ESTRUCTURA_DC if es_dc else _ESTRUCTURA_BASE,
    )


def _join(lst, sep=" | "):
    if not lst or not isinstance(lst, list):
        return ""
    return sep.join(str(x).strip() for x in lst if str(x).strip())


def _norm(s, default="No indica"):
    s = (s or "").strip()
    return s if s else default


def extraer_metadatos_periodisticos(transcripcion: str, proyecto: str) -> dict:
    prompt = _build_prompt(proyecto) + f'\n\nTEXTO A ANALIZAR:\n""" {transcripcion} """\n'

    try:
        resp = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        raw = (resp.choices[0].message.content or "").strip()

        if raw.startswith("```"):
            raw = raw.strip("`")
            raw = re.sub(r"^json\s*", "", raw, flags=re.IGNORECASE).strip()

        data = json.loads(raw)

        out = {
            "Título": _norm(data.get("Título")),
            "Tema principal": _norm(data.get("Tema principal")),
            "Subtemas": _join(data.get("Subtemas", [])),
            "Actores y figuras públicas": _join(data.get("Actores y figuras públicas", [])),
            "Fuentes citadas": _join(data.get("Fuentes citadas", [])),
            "Citas textuales": _join(data.get("Citas textuales", [])),
            "Datos numéricos": _join(data.get("Datos numéricos", [])),
            "Palabras clave": _join(data.get("Palabras clave", []), sep=", "),
            "Resumen": _norm(data.get("Resumen")),
        }
        if proyecto == "Doble Check":
            out["Afirmaciones verificables"] = _join(data.get("Afirmaciones verificables", []))

        return out

    except json.JSONDecodeError:
        print("Error: la respuesta de la API no es JSON válido.")
        print("Respuesta (truncada):", (raw[:400] + "…") if "raw" in locals() else "(vacía)")
        return {}
    except Exception as e:
        print("Error en la llamada a la API:", e)
        return {}
