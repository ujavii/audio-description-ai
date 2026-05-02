import os
import json
import re
import unicodedata
from dotenv import load_dotenv

load_dotenv()

AI_PROVIDER = os.getenv("AI_PROVIDER", "openai").lower()
AI_MODEL    = os.getenv("AI_MODEL", "").strip()          # sobreescribe el default del proveedor si se define

# ----------- GLOSARIO DE ENTIDADES (opcional) -----------

import sys
from pathlib import Path

GLOSARIO_PATH = os.getenv(
    "NOMBRES_GLOSARIO_PATH",
    str(Path(__file__).resolve().parents[1] / "data" / "glosario_nombres.json"),
)
_GLOSARIO = None

def _strip_accents(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))

def _load_glosario():
    global _GLOSARIO
    if _GLOSARIO is not None:
        return _GLOSARIO
    try:
        with open(GLOSARIO_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
        glos = {}
        for canon, alias_list in raw.items():
            canon_clean = canon.strip()
            for alias in alias_list:
                key = _strip_accents(alias.strip().lower())
                glos[key] = canon_clean
        _GLOSARIO = glos
    except Exception:
        _GLOSARIO = {}
    return _GLOSARIO

def _apply_glosario_nombres(lista_nombres):
    glos = _load_glosario()
    out, seen = [], set()
    for nombre in lista_nombres:
        base = _strip_accents((nombre or "").strip().lower())
        canon = glos.get(base, nombre)
        if canon and canon not in seen:
            out.append(canon)
            seen.add(canon)
    return out

# ----------- NORMALIZACIÓN POST-API -----------

_TITULOS_REGEX = re.compile(
    r"\b(dr\.?|doctor|lic\.?|licenciado|licenciada|ing\.?|ingeniero|ingeniera|sr\.?|señor|sra\.?|señora|prof\.?|profesor|profesora)\b\.?",
    flags=re.IGNORECASE,
)

def _ensure_list(v, default_list):
    if v is None:
        return list(default_list)
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [str(v).strip()] if str(v).strip() else list(default_list)

def _clean_person_name(name: str) -> str:
    s = _TITULOS_REGEX.sub("", name or "").strip()
    return re.sub(r"\s{2,}", " ", s)

def _dedup_keep_order(seq):
    seen, out = set(), []
    for x in seq:
        if x not in seen:
            out.append(x)
            seen.add(x)
    return out

def _norm_lista_personas(lst, default_if_empty=None):
    lst = _ensure_list(lst, [])
    lst = [_clean_person_name(x) for x in lst if x]
    lst = [x for x in lst if x]
    lst = _dedup_keep_order(lst)
    if not lst and default_if_empty is not None:
        return list(default_if_empty)
    return lst

def _norm_palabras_clave(lst):
    lst = _ensure_list(lst, [])
    lst = [str(x).strip().lower() for x in lst if x]
    return _dedup_keep_order(lst)[:5]

def _norm_str(s, default="No indica"):
    s = (s or "").strip()
    return s if s else default

def _limpiar_json(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```json?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()

# ----------- PROVEEDORES -----------

def _completar_openai(prompt: str, base_url: str = "") -> str:
    from openai import OpenAI
    if AI_PROVIDER == "openai_compatible":
        api_key = os.getenv("OPENAI_COMPATIBLE_API_KEY") or os.getenv("OPENAI_API_KEY", "")
    else:
        api_key = os.getenv("OPENAI_API_KEY", "")
    modelo = AI_MODEL or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    kwargs: dict = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    client = OpenAI(**kwargs)
    resp = client.chat.completions.create(
        model=modelo,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    return (resp.choices[0].message.content or "").strip()

def _completar_anthropic(prompt: str) -> str:
    try:
        from anthropic import Anthropic
    except ImportError as exc:
        raise ImportError(
            "Para usar el proveedor 'anthropic', instala: pip install anthropic"
        ) from exc
    modelo = AI_MODEL or "claude-sonnet-4-6"
    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
    resp = client.messages.create(
        model=modelo,
        max_tokens=2000,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )
    return (resp.content[0].text or "").strip()

def _completar_gemini(prompt: str) -> str:
    try:
        import google.generativeai as genai
    except ImportError as exc:
        raise ImportError(
            "Para usar el proveedor 'gemini', instala: pip install google-generativeai"
        ) from exc
    modelo = AI_MODEL or "gemini-2.0-flash"
    genai.configure(api_key=os.getenv("GOOGLE_API_KEY", ""))
    model = genai.GenerativeModel(modelo)
    resp = model.generate_content(
        prompt,
        generation_config=genai.GenerationConfig(temperature=0, max_output_tokens=2000),
    )
    return (resp.text or "").strip()

def _llamar_proveedor(prompt: str) -> str:
    if AI_PROVIDER == "openai":
        return _completar_openai(prompt)
    if AI_PROVIDER == "openai_compatible":
        base_url = os.getenv("OPENAI_COMPATIBLE_BASE_URL", "").strip()
        if not base_url:
            raise ValueError(
                "AI_PROVIDER='openai_compatible' requiere definir OPENAI_COMPATIBLE_BASE_URL en .env"
            )
        return _completar_openai(prompt, base_url=base_url)
    if AI_PROVIDER == "anthropic":
        return _completar_anthropic(prompt)
    if AI_PROVIDER == "gemini":
        return _completar_gemini(prompt)
    raise ValueError(
        f"Proveedor '{AI_PROVIDER}' no reconocido. "
        "Opciones válidas: openai, openai_compatible, anthropic, gemini"
    )

# ----------- PROMPT -----------

PROMPT_BLOQUES_TEMPLATE = """Eres un asistente especializado en análisis de transcripciones de programas de audio (radio, podcast u otros formatos sonoros).
Analiza el siguiente texto y devuelve únicamente un objeto JSON válido y bien formado con los campos solicitados.

### INSTRUCCIONES GENERALES
- Devuelve solo JSON válido, sin texto adicional ni bloques Markdown.
- No inventes nombres ni datos que no estén en la transcripción.
- Si un nombre coincide con variantes conocidas de un glosario local, usa la forma canónica.
- Si no hay coincidencia clara con el glosario o hay más de una posible corrección, no corrijas y deja el nombre tal cual aparece.
- Si un campo no se puede inferir, usar "No indica" (excepto listas que pueden ser [] cuando se indica).
- No incluir títulos profesionales ("Licenciado", "Doctor", "Ing.", "Sr.", etc.).
- Los campos "Producción", "Conducción", "Invitados(as)" y "Palabras clave" deben ser siempre **listas** JSON.

---

### BLOQUE 1: PROGRAMA
- Nombre oficial del programa (no confundir con la emisora o canal).
- Reglas específicas:
  1. Si se menciona explícitamente el nombre del programa, usarlo exactamente como aparece
  2. Si no se menciona, inferir basado en:
     a) Tipo de contenido (ej: "Entrevista a [invitado]", "Debate sobre [tema]")
     b) Estructura recurrente (ej: "Actualidad Universitaria")
  3. Para entrevistas: Usar formato "Entrevista a [nombre]" (sin títulos)
  4. Para programas temáticos: Usar formato "[Tema principal]"
  5. Conservar nombres propios de programas existentes
- Ejemplos:
  Texto: "Bienvenidos a Ciencia Hoy"
  → "Ciencia Hoy"
  Texto: (Entrevista sin nombre de programa)
  → "Entrevista a Ana Rodríguez"
  Texto: "En nuestro programa de hoy hablaremos de cambio climático"
  → "Debate sobre cambio climático"

---

### BLOQUE 2: TÍTULO
- Si existe un título explícito del episodio, devuélvelo.
- Si no, genera uno breve (máx. 6-8 palabras) que describa el tema principal.

---

### BLOQUE 3: DESCRIPCIÓN
- Breve descripción de máximo 2 oraciones sobre el contenido del episodio.
- (Salida: campo "Contenido")

---

### BLOQUE 4: PRODUCTOR
- Devuelve una lista JSON con todas las entidades responsables de producir el programa, aplicando estas reglas:
1. **Jerarquía de identificación** (evaluar en este orden):
   a) Personas mencionadas explícitamente como: productor, realizador, responsable
   b) Entidades institucionales mencionadas como productoras
   c) Emisora o canal principal (solo si aparece en el texto)
   d) ["No indica"] (último recurso)
2. **Normalización de nombres**:
   - Mantener el nombre exacto como aparece en el texto
   - Otras entidades: mantener nombre exacto del texto
3. **Reglas para personas físicas**:
   - Eliminar títulos (Dr., Lic., Don, etc.) y cargos ("productor", "director")
   - Conservar nombres completos: "Carlos Mora" en vez de "C. Mora"
   - Si aparece solo primer nombre: complementar con apellido si es posible
   - Nunca inferir nombres o apellidos no mencionados explícitamente
4. **Reglas para entidades**:
   - Incluir si aparece con **verbos de producción o de emisión propia**, por ejemplo:
     **"producido por", "realizado por", "presenta", "presentado por", "ofrece", "ofrecido por", "una producción de", "pone al aire"**.
   - Excluir menciones **pasivas** que no implican producción/emisión propia.
   - Priorizar nombres formales completos.
5. **Casos especiales**:
   - Si hay múltiples productores: mantener orden de aparición
   - Si no hay referencias claras: ["No indica"]
6. **Formato requerido**:
   - Siempre lista JSON (incluso con un elemento)
   - Strings entre comillas dobles
- (Salida: campo "Producción")

---

### BLOQUE 5: PRESENTADOR
- Devuelve una lista JSON con los nombres de todas las personas que presentan o conducen el programa.
- Debes incluir:
    - A quienes abren, despiden o conducen segmentos principales del programa.
    - A quienes son mencionados como presentadores, anfitriones u organizadores del programa.
- Puede haber más de un conductor si ambos tienen un rol claro de conducción.
- Solo incluir nombres reales que aparezcan en la transcripción.
- Excluir reporteros que solo leen notas aisladas y no participan en el resto del programa.
- No incluir invitados, entrevistados o personas mencionadas solo en notas externas.
- Si el texto incluye títulos como "Licenciado", "Lic.", "Dr.", "Señor", elimínalos y devuelve solo el nombre y apellidos.
- Si el nombre del productor también participa como presentador o conductor, repite ese nombre en la lista de presentadores.
- Si hay interacción conversacional sin evidencias claras, NO inventes presentadores adicionales.
- Si no hay ningún nombre claro asociado a la conducción, devuelve lista vacía [].
- (Salida: campo "Conducción")

---

### BLOQUE 6: INVITADOS
- Devuelve una lista JSON con los nombres de personas que fueron **invitados** en el programa principal.
- **Por defecto**, la lista debe ser **[]**. Solo agrega nombres si hay evidencia clara de invitación real.
- Para incluir a una persona, deben cumplirse **ambas condiciones**:
    1. **Presentación explícita:** El conductor utiliza expresiones claras como:
       "nuestro invitado", "nuestra invitada", "nos acompaña", "hoy entrevistamos a",
       "hoy está con nosotros", "entrevista a [nombre]", "hoy con la presencia de [nombre]".
    2. **Diálogo en vivo:** Hay conversación directa (preguntas y respuestas) entre el conductor y la persona.
- **Reglas de exclusión absoluta (si se cumple alguna, NO incluir):**
    - La persona es solo mencionada, citada o referida indirectamente.
    - Forma parte de reportajes, paneles externos o notas grabadas sin interacción con el conductor.
- **Regla final prioritaria:**
    - Si tienes duda de que una persona sea un invitado real, **NO la incluyas** y devuelve la lista vacía `[]`.
    - Nunca repitas al productor ni al presentador dentro de la lista de invitados.
- (Salida: campo "Invitados(as)")

---

### BLOQUE 7: CONTROLES
- Devuelve una lista JSON con los nombres de todas las personas a cargo de controles técnicos o locución.
- Incluye tanto a técnicos de sonido como a locutores cuando sean mencionados explícitamente.
- Eliminar títulos profesionales, conservando solo nombres y apellidos.
- Si no se menciona a nadie: ["No indica"].
- (Salida: campo "Apoyo técnico")

---

### BLOQUE 8: GÉNERO
- Una de ["Educativo","Científico","Cultural","Artístico","Académico","Recreativo","Informativo / periodístico","Divulgación / extensión universitaria","Político"].

---

### BLOQUE 9: LENGUA
- Lengua en la que está hablado el programa (ej: "Español", "Inglés", "Portugués").
- Si no se menciona, inferir o colocar "No indica".

---

### BLOQUE 10: ETIQUETAS
- Devuelve una lista JSON con máximo 5 palabras clave relevantes del contenido, siguiendo estas reglas:
1. **Exclusiones obligatorias**:
   - Nunca incluyas nombres propios de personas (excepto figuras históricas reconocidas).
   - Excluye cualquier término presente en los campos: productor/presentador/invitados/controles.
   - Elimina marcas, nombres de instituciones y términos genéricos ("programa", "entrevista", etc.).
2. **Criterios de selección**:
   - Enfócate en conceptos sustantivos del contenido (no en participantes).
   - Prioriza términos compuestos cuando existan ("literatura contemporánea" > "literatura").
   - Selecciona conceptos que representen al menos el 20% del contenido.
   - Usa sustantivos concretos en minúsculas, sin artículos.
3. **Formato**:
   - Lista JSON con máximo 5 elementos
   - Todos los strings en minúsculas
   - Sin repeticiones o variantes del mismo concepto
- (Salida: campo "Palabras clave")

---

### ESTRUCTURA DE SALIDA (JSON ÚNICO)
Devuelve **únicamente** un objeto JSON con estas claves exactas:
- "Programa": string
- "Título": string
- "Contenido": string  (máx. 2 oraciones)
- "Producción": lista de strings (si no hay, ["No indica"])
- "Conducción": lista de strings (si no hay, [])
- "Invitados(as)": lista de strings (si no hay, [])
- "Apoyo técnico": lista de strings (si no hay, ["No indica"])
- "Género": string
- "Lengua": string
- "Palabras clave": lista de hasta 5 strings en minúsculas
"""


def extraer_metadatos_api(transcripcion: str) -> dict:
    """
    Envía la transcripción al proveedor de IA configurado y devuelve un dict
    con los campos descriptivos normalizados.
    El proveedor se controla con AI_PROVIDER en .env (openai por defecto).
    """
    prompt = PROMPT_BLOQUES_TEMPLATE + f'\n\nTEXTO A ANALIZAR:\n""" {transcripcion} """\n'

    try:
        raw = _llamar_proveedor(prompt)
        data = json.loads(_limpiar_json(raw))

        data_out = {
            "Programa":      _norm_str(data.get("Programa", "")),
            "Título":        _norm_str(data.get("Título", "")),
            "Contenido":     _norm_str(data.get("Contenido", "")),
            "Producción":    _norm_lista_personas(data.get("Producción"), default_if_empty=["No indica"]),
            "Conducción":    _norm_lista_personas(data.get("Conducción"), default_if_empty=[]),
            "Invitados(as)": _norm_lista_personas(data.get("Invitados(as)"), default_if_empty=[]),
            "Apoyo técnico": _norm_lista_personas(data.get("Apoyo técnico"), default_if_empty=["No indica"]),
            "Género":        _norm_str(data.get("Género", "")),
            "Lengua":        _norm_str(data.get("Lengua", "")),
            "Palabras clave":_norm_palabras_clave(data.get("Palabras clave")),
        }

        for campo in ["Producción", "Conducción", "Invitados(as)", "Apoyo técnico"]:
            data_out[campo] = _apply_glosario_nombres(data_out.get(campo, []))

        return data_out

    except json.JSONDecodeError:
        raw_local = raw if "raw" in dir() else "(vacía)"
        print("Error: la respuesta de la API no es JSON válido.")
        print("Respuesta recibida (truncada):", (raw_local[:400] + "…") if len(raw_local) > 400 else raw_local)
        return {}
    except Exception as e:
        print(f"Error en la llamada a la API ({AI_PROVIDER}):", e)
        return {}
