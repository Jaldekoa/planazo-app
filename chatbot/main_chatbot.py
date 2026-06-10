import os
import uuid
import json
import re
import numpy as np
import psycopg2
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import anthropic
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

from dotenv import load_dotenv 
load_dotenv()

app = FastAPI(title="Chatbot Orquestador - Data Science")

# ─────────────────────────────────────────────
# CONFIGURACIÓN DE ANTHROPIC (CLAUDE)
# ─────────────────────────────────────────────
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
MODEL = "claude-sonnet-4-6"

# ─────────────────────────────────────────────
# CONFIGURACIÓN DE POSTGRESQL
# ─────────────────────────────────────────────
DB_CONFIG = {
    "host":     os.getenv("DB_HOST",     "dpg-d8ga02vlk1mc73elmv40-a.frankfurt-postgres.render.com"),
    "port":     os.getenv("DB_PORT",     "5432"),
    "database": os.getenv("DB_NAME",     "recomendador_ds"),
    "user":     os.getenv("DB_USER",     "recomendador_ds_user"),
    "password": os.getenv("DB_PASSWORD", "NJBcVxYoa7SrmDVRpCfmIHCCexWLsbDQ")
}

# ─────────────────────────────────────────────
# MODELO DE EMBEDDINGS
# Se descarga automáticamente la primera vez (~90MB)
# Es multilingüe, funciona bien en español y euskera
# ─────────────────────────────────────────────
print("Cargando modelo de embeddings...")
MODELO_EMBEDDINGS = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
print("Modelo cargado.")

# ─────────────────────────────────────────────
# CACHÉ DE ACTIVIDADES EN MEMORIA
# Se carga al arrancar el servidor y se refresca
# cada vez que llames a /admin/recargar-actividades
# ─────────────────────────────────────────────
CACHE_ACTIVIDADES = []      # Lista de dicts con los datos de cada actividad
CACHE_EMBEDDINGS  = None    # Matriz numpy con los embeddings de cada actividad

# ─────────────────────────────────────────────
# LOS 30 TAGS OFICIALES
# ─────────────────────────────────────────────
TAGS_OFICIALES = [
    "after_party", "after_work", "cuidarme", "brunch", "pelis", "cultura", "deporte",
    "low-cost", "euskaldun", "arte", "party", "gastronomia", "juegos_de_mesa", "mercado",
    "tendencia", "conciertos", "nocturno", "outdoor", "pintxopote", "poteo", "rooftop",
    "talleres", "teatro", "terraceo", "comercio_local", "tradicional", "chill", "putivuelta",
    "deportes_extremos", "caprichos"
]

# ─────────────────────────────────────────────
# MEMORIA TEMPORAL DE CONVERSACIONES
# ─────────────────────────────────────────────
MEMORIA = {}


# ══════════════════════════════════════════════
# FUNCIONES DEL RAG
# ══════════════════════════════════════════════

def conectar_bd():
    """Abre una conexión a PostgreSQL y la devuelve."""
    return psycopg2.connect(**DB_CONFIG)


def actividad_a_texto(actividad: dict) -> str:
    """
    Convierte una fila de la tabla activities en una frase de texto.
    Esta frase es la que se convierte en embedding.
    Cuanto más descriptiva, mejor buscará el RAG.
    """
    partes = []

    if actividad.get("name"):
        partes.append(actividad["name"])

    # Juntamos los tres tags en una frase natural
    tags = [actividad.get("tag_1"), actividad.get("tag_2"), actividad.get("tag_3")]
    tags_limpios = [t for t in tags if t]
    if tags_limpios:
        partes.append("tipo: " + ", ".join(tags_limpios))

    if actividad.get("municipio"):
        partes.append("en " + actividad["municipio"])

    if actividad.get("time_slot"):
        partes.append("horario: " + actividad["time_slot"])

    if actividad.get("price") is not None:
        precio = actividad["price"]
        if precio == 0:
            partes.append("precio: gratuito")
        else:
            partes.append(f"precio: {precio}€")

    if actividad.get("is_indoor") == 1:
        partes.append("actividad en interior")
    else:
        partes.append("actividad al aire libre")

    return ". ".join(partes)


def cargar_actividades_desde_bd():
    """
    Lee todas las actividades activas de PostgreSQL,
    genera sus embeddings y los guarda en el caché.
    Se llama al arrancar y desde /admin/recargar-actividades.
    """
    global CACHE_ACTIVIDADES, CACHE_EMBEDDINGS

    print("Cargando actividades desde PostgreSQL...")
    conn = conectar_bd()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, name, municipio, lat, lng,
               tag_1, tag_2, tag_3,
               time_slot, price, fecha_inicio, fecha_fin,
               horario, is_active, is_indoor
        FROM activities
        WHERE is_active = 1
    """)

    columnas = [desc[0] for desc in cursor.description]
    filas = cursor.fetchall()
    cursor.close()
    conn.close()

    if not filas:
        print("⚠️  No hay actividades activas en la BD.")
        CACHE_ACTIVIDADES = []
        CACHE_EMBEDDINGS = None
        return

    # Convertimos cada fila en un dict
    CACHE_ACTIVIDADES = [dict(zip(columnas, fila)) for fila in filas]

    # Generamos el texto descriptivo de cada actividad
    textos = [actividad_a_texto(a) for a in CACHE_ACTIVIDADES]

    # Generamos los embeddings de todos los textos de golpe (más eficiente)
    print(f"Generando embeddings para {len(textos)} actividades...")
    CACHE_EMBEDDINGS = MODELO_EMBEDDINGS.encode(textos, show_progress_bar=True)

    print(f"✅ {len(CACHE_ACTIVIDADES)} actividades cargadas y vectorizadas.")


def buscar_actividades_relevantes(consulta: str, top_k: int = 5) -> list[dict]:
    """
    Dado el mensaje del usuario, devuelve las top_k actividades
    más relevantes según similitud de coseno entre embeddings.
    """
    if CACHE_EMBEDDINGS is None or len(CACHE_ACTIVIDADES) == 0:
        return []

    # Convertimos la consulta del usuario en un embedding
    embedding_consulta = MODELO_EMBEDDINGS.encode([consulta])

    # Calculamos la similitud entre la consulta y todas las actividades
    similitudes = cosine_similarity(embedding_consulta, CACHE_EMBEDDINGS)[0]

    # Cogemos los índices de las top_k actividades más similares
    indices_top = np.argsort(similitudes)[::-1][:top_k]

    resultados = []
    for idx in indices_top:
        actividad = CACHE_ACTIVIDADES[idx].copy()
        actividad["score_similitud"] = float(similitudes[idx])
        resultados.append(actividad)

    return resultados


def formatear_actividades_para_prompt(actividades: list[dict]) -> str:
    """
    Convierte la lista de actividades relevantes en un texto
    que se inyecta en el system prompt de Claude.
    """
    if not actividades:
        return "No hay actividades disponibles en la base de datos."

    lineas = ["ACTIVIDADES REALES DISPONIBLES EN LA BASE DE DATOS:"]
    lineas.append("(Usa ÚNICAMENTE estas actividades para tus propuestas. No inventes otras.)\n")

    for i, a in enumerate(actividades, 1):
        tags = [a.get("tag_1"), a.get("tag_2"), a.get("tag_3")]
        tags_str = ", ".join(t for t in tags if t)
        precio_str = "Gratis" if a.get("price") == 0 else f"{a.get('price', '?')}€"
        indoor_str = "Interior" if a.get("is_indoor") == 1 else "Exterior"

        lineas.append(
            f"{i}. ID:{a['id']} | {a['name']} | {a.get('municipio', '?')} | "
            f"Tags: {tags_str} | {precio_str} | {indoor_str} | "
            f"Horario: {a.get('time_slot', '?')}"
        )

    return "\n".join(lineas)


# ══════════════════════════════════════════════
# SYSTEM PROMPT (ahora recibe el contexto RAG)
# ══════════════════════════════════════════════

def construir_system_prompt(contexto_actividades: str, municipio: str = "el País Vasco") -> str:
    return f"""
Eres Nora, el agente conversacional de Planazo (una app de ocio para grupos en el País Vasco).
Una dragona urbana que enciende planes. Tu rol no es asistir ni recomendar como motor neutro: transformas intenciones vagas en 
experiencias concretas para hacer con amigos. Eres la chispa que convierte "no sé qué hacer" en "tienes esto montado".
Tu objetivo es proponer planes grupales enlazados: itinerarios de 2 a 4 actividades consecutivas.

== PERSONALIDAD ==
- Divertida, directa, ligeramente canalla
- Impulsora de acción, cero burocrática
- Alta energía, lenguaje visual
- Humor ligero, nunca sarcasmo destructivo

== TONO DE VOZ ==
PERMITIDO:
- Frases cortas y activas
- Imperativos suaves: "vamos", "pruébalo", "lánzate"
- Expresiones energéticas: "esto está que arde", "se viene planazo", "esto pinta fuerte"
- Referencias a cuadrilla, calle, ciudad
- Vocabulario propio: "planazo", "joya", "esto es oro", "te lanzo esto", "esto te va", "olfatear planes"

PROHIBIDO:
- Lenguaje romántico, sexualizado o de dating ("match", "conexión", "química")
- Tono motivacional corporativo ("descubre tu mejor versión")
- Exceso de emoticonos
- Frases tipo "soy tu asistente" o "como asistente puedo ayudarte"
- Paternalismo ("te recomiendo que…")
- Tecnicismos
- Listas largas sin narrativa

== ESTILO DE OUTPUT ==
- Frases cortas + decisión clara
- Priorizar acción sobre exploración
- Alta energía emocional, baja ambigüedad, alta concreción
- Sustituir "según tus preferencias" por "te he encontrado esto", "esto encaja contigo", "te lanzo un plan"

== REGLAS DE LAS PROPUESTAS ==
1. Recomienda únicamente actividades para salir a la calle, nunca planes en casa.
2. Basa tus itinerarios en estos 30 tags oficiales: {', '.join(TAGS_OFICIALES)}.
3. SOLO puedes proponer actividades que aparezcan en la lista de abajo con su ID. Nunca inventes lugares.
4. Si no hay ninguna actividad adecuada en la lista, díselo honestamente y pregunta si quiere ajustar preferencias. NUNCA inventes nombres de lugares.
5. Cuando propongas un itinerario, enuméralo claramente: "Primero... luego... y para terminar..."
6. Siempre pregunta al final si la propuesta les convence o si quieren ajustar algo.

== REGLA ABSOLUTA ==
Si propones una actividad que no aparece en la lista de abajo con su ID, estás cometiendo un error grave.
Ante la duda, no propongas nada y pide al usuario que ajuste sus preferencias.
Nunca menciones un lugar, local, evento o actividad que no esté en la lista. Ni uno.

== BASE DE DATOS DE ACTIVIDADES DISPONIBLES ==
{contexto_actividades}

== GESTIÓN DEL CIERRE DEL PLAN (MUY IMPORTANTE) ==
Cuando el usuario confirme claramente que acepta el plan (frases como "perfecto", "lánzalo",
"nos va bien", "dale", "sí, ese plan", "me quedo con eso"...), debes:

1. Responder con un mensaje de confirmación entusiasta y breve.
2. Incluir AL FINAL de tu respuesta, después de una línea en blanco, el siguiente bloque JSON
   exactamente con este formato, sin comillas adicionales ni texto extra después:

PLAN_CERRADO:
{{
  "itinerario": [
    {{"orden": 1, "activity_id": 123, "nombre_lugar": "Nombre del lugar", "tag_actividad": "tag_oficial", "hora_sugerida": "HH:MM"}},
    {{"orden": 2, "activity_id": 456, "nombre_lugar": "Nombre del lugar", "tag_actividad": "tag_oficial", "hora_sugerida": "HH:MM"}}
  ]
}}

IMPORTANTE: En activity_id pon el ID real que aparece en la lista de actividades (el número después de "ID:").
Usa SOLO tags de la lista oficial. Las horas deben ser coherentes (no pongas cenar a las 12:00).
Si el usuario solo aceptó algunas actividades del plan, incluye solo esas en el itinerario.

Si el usuario NO ha confirmado y solo está negociando o pidiendo cambios, responde con normalidad
y NO incluyas el bloque PLAN_CERRADO.
""".strip()


# ══════════════════════════════════════════════
# FUNCIÓN DE EXTRACCIÓN DEL CIERRE
# ══════════════════════════════════════════════

def extraer_cierre(texto_bot: str) -> tuple[str, bool, list | None]:
    patron = r"PLAN_CERRADO:\s*(\{[\s\S]*\})"
    match = re.search(patron, texto_bot)

    if not match:
        return texto_bot.strip(), False, None

    mensaje_limpio = texto_bot[:match.start()].strip()

    try:
        datos = json.loads(match.group(1))
        itinerario_raw = datos.get("itinerario", [])

        itinerario_final = []
        for item in itinerario_raw:
            itinerario_final.append({
                "orden":         item.get("orden"),
                "activity_id":   item.get("activity_id"),   # ← Ahora viene de la BD real
                "nombre_lugar":  item.get("nombre_lugar"),
                "tag_actividad": item.get("tag_actividad"),
                "hora_sugerida": item.get("hora_sugerida", "")
            })

        return mensaje_limpio, True, itinerario_final

    except json.JSONDecodeError:
        return texto_bot.strip(), False, None


# ══════════════════════════════════════════════
# MODELOS DE ENTRADA
# ══════════════════════════════════════════════

class Location(BaseModel):
    latitud: float
    longitud: float

class IniciarChatRequest(BaseModel):
    user_id: int
    group_id: int
    location: Optional[Location] = None

class MensajeChatRequest(BaseModel):
    conversacion_id: str
    mensaje_usuario: str
    location: Optional[Location] = None


# ══════════════════════════════════════════════
# ARRANQUE DEL SERVIDOR
# Carga las actividades al iniciar
# ══════════════════════════════════════════════

@app.on_event("startup")
async def startup_event():
    cargar_actividades_desde_bd()


# ══════════════════════════════════════════════
# ENDPOINTS
# ══════════════════════════════════════════════

@app.post("/chatbot/iniciar")
async def iniciar_chatbot(request: IniciarChatRequest):
    conv_id = f"chat_{request.user_id}_{request.group_id}_{uuid.uuid4().hex[:6]}"
    MEMORIA[conv_id] = []

    saludo = "Soy Nora 🔥 Aquí no se pierde el tiempo: se hacen planazos. ¿Qué movemos hoy con la cuadrilla?"
    MEMORIA[conv_id].append({"role": "assistant", "content": saludo})

    return {"conversacion_id": conv_id, "mensaje_bot": saludo}


@app.post("/chatbot/mensaje")
async def procesar_mensaje(request: MensajeChatRequest):
    conv_id = request.conversacion_id

    if conv_id not in MEMORIA:
        MEMORIA[conv_id] = []

    # 1. Añadimos el mensaje del usuario al historial
    MEMORIA[conv_id].append({
        "role": "user",
        "content": request.mensaje_usuario
    })

    # 2. RAG: buscamos las actividades más relevantes para este mensaje
    actividades_relevantes = buscar_actividades_relevantes(
        consulta=request.mensaje_usuario,
        top_k=18
    )
    contexto_actividades = formatear_actividades_para_prompt(actividades_relevantes)

    # 3. Llamada a Claude con el contexto RAG inyectado en el system prompt
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1000,
            system=construir_system_prompt(contexto_actividades),
            messages=MEMORIA[conv_id]
        )
    except anthropic.APIError as e:
        raise HTTPException(status_code=502, detail=f"Error llamando a Claude: {str(e)}")

    texto_bot_raw = response.content[0].text

    # 4. Detectamos si la IA cerró el plan
    mensaje_limpio, plan_completado, itinerario_final = extraer_cierre(texto_bot_raw)

    # 5. Guardamos el mensaje limpio en el historial
    MEMORIA[conv_id].append({"role": "assistant", "content": mensaje_limpio})

    return {
        "conversacion_id":  conv_id,
        "mensaje_bot":      mensaje_limpio,
        "plan_completado":  plan_completado,
        "itinerario_final": itinerario_final
    }


@app.post("/admin/recargar-actividades")
async def recargar_actividades():
    """
    Endpoint de administración para recargar el caché de actividades
    sin reiniciar el servidor. Útil cuando se añaden nuevas actividades a la BD.
    """
    cargar_actividades_desde_bd()
    return {"status": "ok", "actividades_cargadas": len(CACHE_ACTIVIDADES)}
