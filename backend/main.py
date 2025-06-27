from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from google.cloud import bigquery
import re
import logging
from openai import AzureOpenAI
import requests
from msal import ConfidentialClientApplication
from fastapi.responses import JSONResponse


# --- Configuración general ---
PROJECT_ID = "advanced-analytics-dev-440814"
TABLE_ID = "comerciales.comerciales_cuentas"

# --- Configuración Azure OpenAI ---
endpoint_llm = "https://prueba-diego-aa.openai.azure.com/"
deployment_llm = "gpt-4o"
api_key_llm = "9ea7440cfca84e5c82d42811be968b34"

client_llm = AzureOpenAI(
    azure_endpoint=endpoint_llm,
    api_key=api_key_llm,
    api_version="2025-01-01-preview"
)

# --- Inicialización ---
app = FastAPI()
origins = ["*"]  # Para desarrollo. En producción, usá ["https://tu-dominio.com"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,           # Qué orígenes están permitidos
    allow_credentials=True,
    allow_methods=["*"],             # GET, POST, PUT, DELETE, etc.
    allow_headers=["*"],             # Content-Type, Authorization, etc.
)
client = bigquery.Client()
logging.basicConfig(level=logging.INFO)

# --- Funciones auxiliares ---
def normalizar_texto(texto: str) -> str:
    return re.sub(r'[^a-zA-Z0-9]', '', texto).lower()

def extraer_marca(pregunta: str) -> str:
    prompt = f"""
Tu tarea es analizar una pregunta de un usuario y extraer con precisión el nombre de la **marca o cuenta comercial** que se menciona.
Lo que tenes que hacer es solamente devolver las marcas que encuentres en los textos, ejemplo: Gafa - Samsung - BGH - electro misiones - BIOGREEN - ABBOTT - CETROGAR, FADECYA, COPCO, NEWSAN, FRAVEGA, DISEÑOJERY, T&H TABACOS, PANALAB, RICHMOND, CHIESA, UPS, THIRD TIME, WOOPY, EMOOD, DABRA, etc. 
Devolvé **solo** el nombre exacto de la marca, sin comillas, sin explicaciones, sin agregar nada más. No devuelvas frases ni textos adicionales.

⚠️ Si la pregunta no menciona ninguna marca, respondé solo: NINGUNA

🧪 Ejemplos:

Pregunta: "¿Quién atiende la cuenta Natura?"
Marca: Natura

Pregunta: "Decime quién es el comercial de Adidas"
Marca: Adidas

Pregunta: "Quiero saber quién lleva la cuenta de Mercado Libre"
Marca: Mercado Libre

Pregunta: "¿Cuál es el ejecutivo asignado a DABRA?"
Marca: DABRA

Pregunta: "Hola, buen día"
Marca: NINGUNA

---

Pregunta: "{pregunta}"
Marca:
"""
    try:
        response = client_llm.chat.completions.create(
            model=deployment_llm,
            messages=[
                {"role": "system", "content": "Sos un extractor de marcas"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )
        marca = response.choices[0].message.content.strip()
        logging.info(f"[Azure OpenAI] Pregunta: '{pregunta}' → Marca detectada: '{marca}'")
        if marca.upper() == "NINGUNA" or not marca:
            return ""
        return marca
    except Exception as e:
        logging.error(f"Error al usar Azure OpenAI: {e}")
        return ""

def buscar_comercial(marca: str) -> dict:
    """
    Devuelve un diccionario con ejecutivo, nombre_fantasia, razon_social y marca_detectada.
    """
    marca_norm = normalizar_texto(marca)

    # --- Primer intento: coincidencia exacta ---
    query_exacta = f"""
        WITH normalizada AS (
          SELECT
            ejecutivo,
            nombre_fantasia,
            razon_social,
            CASE
              WHEN LOWER(REGEXP_REPLACE(nombre_fantasia, r'[^a-zA-Z0-9]', '')) = @marca THEN 0
              ELSE 1
            END AS prioridad
          FROM `{TABLE_ID}`
          WHERE
            LOWER(REGEXP_REPLACE(nombre_fantasia, r'[^a-zA-Z0-9]', '')) = @marca
            OR LOWER(REGEXP_REPLACE(razon_social,   r'[^a-zA-Z0-9]', '')) = @marca
        )
        SELECT ejecutivo, nombre_fantasia, razon_social
        FROM normalizada
        ORDER BY prioridad
        LIMIT 1
    """

    try:
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("marca", "STRING", marca_norm)
            ]
        )
        result = client.query(query_exacta, job_config=job_config).result()
        rows = list(result)
        if rows:
            row = rows[0]
            return {
                "ejecutivo": row["ejecutivo"],
                "nombre_fantasia": row["nombre_fantasia"],
                "razon_social": row["razon_social"],
                "marca_detectada": row["nombre_fantasia"] or row["razon_social"]
            }
    except Exception as e:
        logging.error(f"[BigQuery] Error en intento exacto: {e}")

    # --- Segundo intento con ranking (prioridad) ---
    query_prioridad = f"""
        DECLARE marca_norm STRING DEFAULT @marca;

        WITH base AS (
          SELECT
            ejecutivo,
            nombre_fantasia,
            razon_social,
            LOWER(REGEXP_REPLACE(nombre_fantasia, r'[^a-zA-Z0-9]', '')) AS nf_norm,
            LOWER(REGEXP_REPLACE(razon_social,   r'[^a-zA-Z0-9]', '')) AS rs_norm
          FROM `{TABLE_ID}`
          WHERE
            LOWER(REGEXP_REPLACE(nombre_fantasia, r'[^a-zA-Z0-9]', '')) LIKE CONCAT('%', marca_norm, '%')
            OR LOWER(REGEXP_REPLACE(razon_social,   r'[^a-zA-Z0-9]', '')) LIKE CONCAT('%', marca_norm, '%')
        ),

        scored AS (
          SELECT
            *,
            CASE
              WHEN nf_norm = marca_norm THEN 0
              WHEN rs_norm = marca_norm THEN 1
              WHEN STARTS_WITH(nf_norm, marca_norm) THEN 2
              WHEN STARTS_WITH(rs_norm, marca_norm) THEN 3
              WHEN nf_norm LIKE CONCAT('%', marca_norm, '%') THEN 4
              WHEN rs_norm LIKE CONCAT('%', marca_norm, '%') THEN 5
              ELSE 9
            END AS prioridad,
            LEAST(LENGTH(nf_norm), LENGTH(rs_norm)) AS largo_aprox
          FROM base
        )

        SELECT ejecutivo, nombre_fantasia, razon_social
        FROM scored
        ORDER BY prioridad, largo_aprox
        LIMIT 1
    """

    try:
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("marca", "STRING", marca_norm)
            ]
        )
        result = client.query(query_prioridad, job_config=job_config).result()
        rows = list(result)
        if rows:
            row = rows[0]
            return {
                "ejecutivo": row["ejecutivo"],
                "nombre_fantasia": row["nombre_fantasia"],
                "razon_social": row["razon_social"],
                "marca_detectada": row["nombre_fantasia"] or row["razon_social"]
            }
    except Exception as e:
        logging.error(f"[BigQuery] Error en intento por prioridad: {e}")

    return {}

def generar_respuesta_llm(pregunta_usuario: str, datos: dict) -> str:
    """
    Usa Azure OpenAI para generar una respuesta cálida y humana en base al comercial detectado.
    """
    ejecutivo = datos["ejecutivo"]
    fantasia = datos["nombre_fantasia"]
    razon = datos["razon_social"]

    prompt = f"""
El usuario preguntó: "{pregunta_usuario}"

Respondé de manera cálida, breve y natural, como si fueras un humano que responde por Teams o WhatsApp interno.
Incluí el nombre del ejecutivo asignado a la cuenta, y mencioná el nombre de fantasía y razón social si están disponibles.

Datos extraídos:
- Ejecutivo: {ejecutivo}
- Nombre de fantasía: {fantasia}
- Razón social: {razon}

No repitas textualmente el prompt. Sé humano, no robótico. Variá cómo lo decís.
"""

    try:
        response = client_llm.chat.completions.create(
            model=deployment_llm,
            messages=[
                {"role": "system", "content": "Sos un asistente humano y cálido que ayuda a otros en la empresa a ubicar al comercial de una cuenta."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"[LLM] Error generando respuesta con LLM: {e}")
        return f"{ejecutivo} es quien aparece asignado a la cuenta '{fantasia}' ({razon})."


def analizar_imagen(image_base64: str) -> str:
    """
    Usa Azure OpenAI para interpretar una imagen (base64) y devolver una descripción textual
    con objetos visibles, marcas, etiquetas y textos útiles para inferir la marca.
    """
    payload = {
        "messages": [
            {
                "role": "system",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Sos un asistente visual que describe imágenes logísticas. "
                            "Detectás objetos, marcas visibles, nombres escritos, etiquetas, logos y cualquier dato impreso o pegado. "
                            "Tu tarea es describir de forma clara lo que se ve, para ayudar a identificar una marca o remitente."
                        )
                    }
                ]
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Por favor, describí lo que ves en la imagen siguiente. "
                            "Incluí marcas, nombres, etiquetas, números de envío, textos visibles, códigos o cualquier otro detalle relevante. "
                            "No inventes. Respondé solo con una descripción."
                        )
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{image_base64}"
                        }
                    }
                ]
            }
        ],
        "temperature": 0.3,
        "top_p": 0.9,
        "max_tokens": 800
    }

    try:
        response = requests.post(
            endpoint_llm, headers={
                "Content-Type": "application/json",
                "api-key": api_key_llm
            }, json=payload
        )
        response.raise_for_status()
        descripcion = response.json()["choices"][0]["message"]["content"].strip()
        logging.info(f"[Visión LLM] Descripción generada: {descripcion}")
        return descripcion
    except requests.RequestException as e:
        logging.error(f"[Visión LLM] Error procesando imagen: {e}")
        return "No se pudo interpretar la imagen."



# --- Endpoint principal ---
@app.post("/")
async def consultar_comercial(request: Request):
    data = await request.json()
    pregunta = data.get("pregunta", "")

    if not pregunta:
        return {"respuesta": "No se recibió una pregunta válida."}

    marca = extraer_marca(pregunta)
    
    # Si no hay marca, generá una respuesta amable igual
    if not marca:
        try:
            respuesta_llm = client_llm.chat.completions.create(
                model=deployment_llm,
                messages=[
                    {"role": "system", "content": (
                        "Sos un asistente cordial que responde de forma breve, clara y profesional. "
                        "Tu tarea es ayudar a personas de la empresa a conocer quién es el ejecutivo asignado a una cuenta o marca específica. "
                        "Si el mensaje no tiene una marca conocida, saludá o pedí que reformulen la consulta. "
                        "No prometas gestionar cuentas, facturación, ni brindar promociones."
                        )},
                    {"role": "user", "content": pregunta}
                ],
                temperature=0.6
            )
            return {"respuesta": respuesta_llm.choices[0].message.content.strip()}
        except Exception as e:
            logging.error(f"[LLM] Error generando respuesta sin marca: {e}")
            return {"respuesta": "No entendí tu mensaje, ¿podés reformularlo?"}

    # Proceso normal si hay marca detectada
    resultado = buscar_comercial(marca)
    if not resultado or not resultado.get("ejecutivo"):
        return {"respuesta": f"No se encontró un comercial para la marca '{marca}'"}

    respuesta_generada = generar_respuesta_llm(pregunta, resultado)

    return {
        "marca_detectada": resultado["marca_detectada"],
        "nombre_fantasia": resultado["nombre_fantasia"],
        "razon_social": resultado["razon_social"],
        "ejecutivo": resultado["ejecutivo"],
        "respuesta": respuesta_generada
    }



@app.post("/consulta-con-imagen")
async def consulta_con_imagen(request: Request):
    data = await request.json()
    comentario = data.get("comentario", "")
    imagen_base64 = data.get("imagen", "")

    if not comentario and not imagen_base64:
        return {"respuesta": "Faltan datos para procesar la consulta."}

    descripcion = analizar_imagen(imagen_base64)  # 👈 Acá obtenés el texto

    marca = extraer_marca(descripcion)
    if not marca:
        return {
            "respuesta": "No se detectó ninguna marca en la imagen enviada.",
            "descripcion_imagen": descripcion  # 👈 Agregalo acá para inspección
        }

    resultado = buscar_comercial(marca)
    if not resultado or not resultado.get("ejecutivo"):
        return {
            "respuesta": f"No se encontró un comercial para la marca detectada: '{marca}'",
            "descripcion_imagen": descripcion
        }

    respuesta = generar_respuesta_llm(comentario, resultado)

    return {
        "marca_detectada": resultado["marca_detectada"],
        "nombre_fantasia": resultado["nombre_fantasia"],
        "razon_social": resultado["razon_social"],
        "ejecutivo": resultado["ejecutivo"],
        "descripcion_imagen": descripcion,  # 👈 acá también
        "respuesta": respuesta
    }



# --- Health check ---
@app.get("/")
async def root():
    return {"estado": "ok"}

@app.options("/{path:path}")
async def preflight_handler(path: str, request: Request):
    return JSONResponse(status_code=200, content={})

