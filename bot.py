"""
Bot de ventas - La madurez del discipulo (Santiago)
En Pos de Ti / Ele Media
WhatsApp Cloud API (Meta) + Flask

Embudo:
  Bienvenida + capitulo gratis  ->  Oferta (4h despues)  ->  3 seguimientos
Los seguimientos se cancelan solos si la persona responde o manda comprobante.

Cuando alguien escribe algo que el bot no reconoce, se DETIENE la automatizacion
y se marca para atencion humana (no inventa respuestas).
"""

import os
import time
import threading
import sqlite3
from datetime import datetime, timedelta

import requests
from flask import Flask, request

# ------------------------------------------------------------------
#  CONFIGURACION  (se lee de variables de entorno - se ponen en Render)
# ------------------------------------------------------------------
TOKEN        = os.environ.get("WHATSAPP_TOKEN", "")        # Token permanente de Meta
PHONE_ID     = os.environ.get("WHATSAPP_PHONE_ID", "")     # Identificador del numero remitente
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "enposdeti2026")  # Lo inventas tu, valida el webhook

# media_id del PDF del capitulo de muestra (se sube una vez a Meta, ver guia)
CAPITULO_MEDIA_ID = os.environ.get("CAPITULO_MEDIA_ID", "")

# Datos del producto
PRECIO       = os.environ.get("PRECIO", "99")
LINK_PAGO    = os.environ.get("LINK_PAGO", "")            # Tu link de pago / transferencia

API_URL = f"https://graph.facebook.com/v21.0/{PHONE_ID}/messages"

app = Flask(__name__)

# ------------------------------------------------------------------
#  MENSAJES  (tu voz, tono pastoral cercano)
# ------------------------------------------------------------------
MSG_BIENVENIDA = (
    "Hola! Que gusto saludarte. 🙏\n\n"
    "Te comparto el capitulo de muestra de *La madurez del discipulo*, "
    "un estudio del libro de Santiago para crecer en una fe que se nota en la vida diaria.\n\n"
    "Aqui te lo dejo, leelo con calma."
)

MSG_OFERTA = (
    "Espero que el capitulo te haya hablado al corazon.\n\n"
    "El estudio completo tiene 14 lecciones, con preguntas de reflexion para que no solo lo leas, "
    "sino que lo vivas. Esta pensado para llevarte por todo Santiago, semana a semana.\n\n"
    f"Lo puedes tener hoy por ${PRECIO}. {LINK_PAGO}\n\n"
    "Si tienes alguna duda, escribeme con confianza."
)

MSG_SEG1 = (
    "Hola de nuevo. 🙏 Solo queria saber si pudiste leer el capitulo.\n\n"
    "Santiago tiene una forma muy directa de confrontarnos con amor. "
    f"Si quieres el estudio completo, sigue disponible por ${PRECIO}. {LINK_PAGO}"
)

MSG_SEG2 = (
    "A veces uno lo deja para despues y se pasa el tiempo.\n\n"
    "Si algo te detiene, sea el precio o alguna duda, dimelo y lo platicamos. "
    f"El estudio sigue aqui cuando estes listo. {LINK_PAGO}"
)

MSG_SEG3 = (
    "Esta es mi ultima nota para no incomodarte. 🙏\n\n"
    "Decidas lo que decidas, sigue buscando crecer en tu fe. "
    f"Y si quieres acompanarte de este estudio, aqui estare. {LINK_PAGO}"
)

# Texto que, si la persona lo manda, entendemos como que ya pago
PALABRAS_PAGO = ["comprobante", "ya pague", "ya transferi", "deposite", "listo el pago", "hice el pago"]

# ------------------------------------------------------------------
#  BASE DE DATOS  (sqlite - guarda en que paso va cada contacto)
# ------------------------------------------------------------------
DB = "contactos.db"

def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS contactos (
                telefono       TEXT PRIMARY KEY,
                etapa          TEXT,
                ultimo_envio   TEXT,
                respondio      INTEGER DEFAULT 0,
                pago           INTEGER DEFAULT 0,
                creado         TEXT
            )
        """)
    print("Base de datos lista.")

def get_contacto(tel):
    with db() as conn:
        row = conn.execute("SELECT * FROM contactos WHERE telefono=?", (tel,)).fetchone()
        return dict(row) if row else None

def upsert_contacto(tel, **campos):
    c = get_contacto(tel)
    with db() as conn:
        if c:
            sets = ", ".join(f"{k}=?" for k in campos)
            valores = list(campos.values()) + [tel]
            conn.execute(f"UPDATE contactos SET {sets} WHERE telefono=?", valores)
        else:
            campos["telefono"] = tel
            campos["creado"] = datetime.utcnow().isoformat()
            cols = ", ".join(campos.keys())
            ph = ", ".join("?" for _ in campos)
            conn.execute(f"INSERT INTO contactos ({cols}) VALUES ({ph})", list(campos.values()))

# ------------------------------------------------------------------
#  ENVIO DE MENSAJES
# ------------------------------------------------------------------
def enviar_texto(tel, texto):
    payload = {
        "messaging_product": "whatsapp",
        "to": tel,
        "type": "text",
        "text": {"body": texto},
    }
    _post(payload)

def enviar_documento(tel, media_id, nombre_archivo, caption=""):
    payload = {
        "messaging_product": "whatsapp",
        "to": tel,
        "type": "document",
        "document": {"id": media_id, "filename": nombre_archivo, "caption": caption},
    }
    _post(payload)

def _post(payload):
    headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
    try:
        r = requests.post(API_URL, headers=headers, json=payload, timeout=20)
        if r.status_code >= 400:
            print("Error al enviar:", r.status_code, r.text)
    except Exception as e:
        print("Excepcion al enviar:", e)

# ------------------------------------------------------------------
#  LOGICA DEL EMBUDO
# ------------------------------------------------------------------
def iniciar_embudo(tel):
    """Primer contacto: bienvenida + capitulo gratis."""
    enviar_texto(tel, MSG_BIENVENIDA)
    if CAPITULO_MEDIA_ID:
        enviar_documento(tel, CAPITULO_MEDIA_ID,
                          "La madurez del discipulo - Muestra.pdf",
                          "Capitulo de muestra 🙏")
    upsert_contacto(tel, etapa="muestra_enviada",
                    ultimo_envio=datetime.utcnow().isoformat(),
                    respondio=0, pago=0)

def manejar_respuesta(tel, texto):
    """La persona escribio algo. Decidimos que hacer."""
    c = get_contacto(tel)
    texto_low = texto.lower().strip()

    # Detectar comprobante de pago
    if any(p in texto_low for p in PALABRAS_PAGO):
        upsert_contacto(tel, pago=1, respondio=1, etapa="cerrado")
        enviar_texto(tel, "Mil gracias! 🙏 En cuanto confirme tu pago te envio el estudio completo. "
                          "Dios te bendiga.")
        return

    # Contacto nuevo -> iniciar embudo
    if c is None:
        iniciar_embudo(tel)
        return

    # Ya estaba en el embudo y respondio -> marcar y dejar de auto-seguir
    upsert_contacto(tel, respondio=1)

    # Si es una respuesta simple y positiva, mandamos la oferta de una vez
    palabras_interes = ["si", "sí", "quiero", "info", "informacion", "precio", "cuanto", "como"]
    if any(p in texto_low for p in palabras_interes):
        enviar_texto(tel, MSG_OFERTA)
        upsert_contacto(tel, etapa="oferta_enviada", ultimo_envio=datetime.utcnow().isoformat())
    else:
        # Respuesta que no entendemos -> atencion humana
        upsert_contacto(tel, etapa="atencion_humana")
        print(f"[ATENCION HUMANA] {tel} escribio: {texto}")

# ------------------------------------------------------------------
#  SEGUIMIENTOS AUTOMATICOS  (hilo en segundo plano)
# ------------------------------------------------------------------
def revisar_seguimientos():
    """Cada 30 min revisa quien necesita seguimiento."""
    while True:
        try:
            ahora = datetime.utcnow()
            with db() as conn:
                filas = conn.execute(
                    "SELECT * FROM contactos WHERE pago=0 AND respondio=0 "
                    "AND etapa IN ('muestra_enviada','seguimiento1','seguimiento2')"
                ).fetchall()

            for f in filas:
                c = dict(f)
                ultimo = datetime.fromisoformat(c["ultimo_envio"])
                horas = (ahora - ultimo).total_seconds() / 3600
                tel = c["telefono"]
                etapa = c["etapa"]

                # 4h despues de la muestra -> oferta
                if etapa == "muestra_enviada" and horas >= 4:
                    enviar_texto(tel, MSG_OFERTA)
                    upsert_contacto(tel, etapa="seguimiento1", ultimo_envio=ahora.isoformat())

                # 24h despues -> seguimiento 1
                elif etapa == "seguimiento1" and horas >= 24:
                    enviar_texto(tel, MSG_SEG1)
                    upsert_contacto(tel, etapa="seguimiento2", ultimo_envio=ahora.isoformat())

                # 24h mas -> seguimiento 2
                elif etapa == "seguimiento2" and horas >= 24:
                    enviar_texto(tel, MSG_SEG2)
                    upsert_contacto(tel, etapa="seguimiento3_pendiente", ultimo_envio=ahora.isoformat())

        except Exception as e:
            print("Error en seguimientos:", e)

        time.sleep(1800)  # 30 minutos

# ------------------------------------------------------------------
#  WEBHOOK
# ------------------------------------------------------------------
@app.route("/webhook", methods=["GET"])
def verificar_webhook():
    """Meta llama aqui una vez para verificar que el servidor es tuyo."""
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Token invalido", 403

@app.route("/webhook", methods=["POST"])
def recibir_mensaje():
    """Meta manda aqui cada mensaje entrante."""
    data = request.get_json()
    try:
        entry = data["entry"][0]["changes"][0]["value"]
        if "messages" in entry:
            msg = entry["messages"][0]
            tel = msg["from"]
            texto = ""
            if msg.get("type") == "text":
                texto = msg["text"]["body"]
            manejar_respuesta(tel, texto)
    except Exception as e:
        print("Error procesando mensaje:", e)
    return "OK", 200

@app.route("/")
def home():
    return "Bot En Pos de Ti - Santiago activo", 200

# ------------------------------------------------------------------
#  ARRANQUE
# ------------------------------------------------------------------
init_db()
hilo = threading.Thread(target=revisar_seguimientos, daemon=True)
hilo.start()

if __name__ == "__main__":
    puerto = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=puerto)
