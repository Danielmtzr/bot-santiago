"""
Bot de ventas - Santiago: La madurez del discipulo (KIT COMPLETO)
En Pos de Ti / Ele Media
WhatsApp Cloud API (Meta) + Flask

Embudo:
  Bienvenida + leccion de muestra  ->  Oferta (4h)  ->  3 seguimientos
Los seguimientos se cancelan solos si la persona responde o manda comprobante.

Cuando alguien escribe algo que el bot no reconoce, se DETIENE la automatizacion
y se marca para atencion humana (no inventa respuestas).
"""

import os
import time
import threading
import sqlite3
from datetime import datetime

import requests
from flask import Flask, request

# ------------------------------------------------------------------
#  CONFIGURACION  (se lee de variables de entorno - se ponen en Render)
# ------------------------------------------------------------------
TOKEN        = os.environ.get("WHATSAPP_TOKEN", "")
PHONE_ID     = os.environ.get("WHATSAPP_PHONE_ID", "")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "enposdeti2026")

# URL publica del PDF de la leccion de muestra (Google Drive, descarga directa)
LINK_MUESTRA = os.environ.get("LINK_MUESTRA", "")

PRECIO       = os.environ.get("PRECIO", "299")

API_URL = f"https://graph.facebook.com/v21.0/{PHONE_ID}/messages"

app = Flask(__name__)

# ------------------------------------------------------------------
#  MENSAJES  (tu voz, tono pastoral cercano - producto: KIT completo)
# ------------------------------------------------------------------
MSG_BIENVENIDA = (
    "Hola! Que gusto saludarte. 🙏\n\n"
    "Te comparto una leccion de muestra del curso *Santiago: La madurez del discipulo*, "
    "un estudio completo del libro de Santiago para vivir una fe que se note en la vida diaria.\n\n"
    "Aqui te la dejo, revisala con calma."
)

MSG_OFERTA = (
    "Espero que la leccion te haya hablado al corazon.\n\n"
    "El curso completo no es solo un libro: es un *kit listo para ensenar*, con 14 lecciones "
    "que recorren toda la carta de Santiago. Incluye tres piezas:\n\n"
    "📘 *Manual del Alumno* - el cuaderno que sigue cada persona\n"
    "📗 *Guia del Maestro* - todo para dirigir la clase paso a paso (no necesitas experiencia)\n"
    "📊 *Presentacion* - el curso en diapositivas para proyectar\n\n"
    "Sirve para tu grupo, tu celula, tu clase de iglesia o estudio personal. Lo imprimes y lo usas "
    "las veces que quieras.\n\n"
    f"Todo el kit en PDF por ${PRECIO} MXN.\n\n"
    "Si quieres, te paso las formas de pago. Solo dime."
)

MSG_PAGO = (
    "Con gusto. Te dejo dos opciones de pago, la que se te haga mas comoda:\n\n"
    "🏪 *Deposito en OXXO (Spin)*\n"
    "Codigo: 2242 1701 8225 7045\n"
    "A nombre de Daniel Martinez Ramirez\n\n"
    "💳 *Transferencia o deposito Santander*\n"
    "Daniel Martinez Ramirez\n"
    "CLABE: 014180140135369275\n"
    "Cuenta: 14013536927\n\n"
    "En cuanto hagas tu deposito, mandame tu comprobante por aqui y te envio el kit completo. 🙏"
)

MSG_SEG1 = (
    "Hola de nuevo. 🙏 Solo queria saber si pudiste revisar la leccion de muestra.\n\n"
    "Santiago tiene una forma muy directa de confrontarnos con amor. "
    f"Si quieres el kit completo (Alumno + Maestro + Presentacion), sigue disponible por ${PRECIO} MXN. "
    "Dime y te paso las formas de pago."
)

MSG_SEG2 = (
    "A veces uno lo deja para despues y se pasa el tiempo.\n\n"
    "Si algo te detiene, sea el precio o alguna duda, dimelo y lo platicamos. "
    "El kit sigue aqui cuando estes listo para llevar a tu grupo por toda la carta de Santiago."
)

MSG_SEG3 = (
    "Esta es mi ultima nota para no incomodarte. 🙏\n\n"
    "Decidas lo que decidas, sigue buscando crecer en tu fe y en la de los tuyos. "
    "Y si quieres acompanarte de este curso, aqui estare."
)

MSG_GRACIAS = (
    "Mil gracias! 🙏 En cuanto confirme tu pago te envio el kit completo: "
    "Manual del Alumno, Guia del Maestro y Presentacion. Dios te bendiga."
)

# Texto que, si la persona lo manda, entendemos como que ya pago
PALABRAS_PAGO = ["comprobante", "ya pague", "ya transferi", "deposite", "listo el pago",
                 "hice el pago", "ya hice", "transferencia hecha"]

# Texto que entendemos como interes general
PALABRAS_INTERES = ["si", "sí", "quiero", "info", "informacion", "precio", "cuanto",
                    "como", "me interesa", "dale", "ok"]

# Texto que entendemos como pedir formas de pago
PALABRAS_PIDE_PAGO = ["pago", "formas de pago", "deposito", "transferencia", "comprar", "clabe", "oxxo"]

# ------------------------------------------------------------------
#  BASE DE DATOS
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

def enviar_documento_url(tel, url, nombre_archivo, caption=""):
    payload = {
        "messaging_product": "whatsapp",
        "to": tel,
        "type": "document",
        "document": {"link": url, "filename": nombre_archivo, "caption": caption},
    }
    _post(payload)

def _post(payload):
    headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
    try:
        r = requests.post(API_URL, headers=headers, json=payload, timeout=30)
        if r.status_code >= 400:
            print("Error al enviar:", r.status_code, r.text)
    except Exception as e:
        print("Excepcion al enviar:", e)

# ------------------------------------------------------------------
#  LOGICA DEL EMBUDO
# ------------------------------------------------------------------
def iniciar_embudo(tel):
    enviar_texto(tel, MSG_BIENVENIDA)
    if LINK_MUESTRA:
        enviar_documento_url(tel, LINK_MUESTRA,
                             "Santiago - Leccion de muestra.pdf",
                             "Leccion de muestra 🙏")
    upsert_contacto(tel, etapa="muestra_enviada",
                    ultimo_envio=datetime.utcnow().isoformat(),
                    respondio=0, pago=0)

def manejar_respuesta(tel, texto):
    c = get_contacto(tel)
    texto_low = texto.lower().strip()

    # Detectar comprobante de pago
    if any(p in texto_low for p in PALABRAS_PAGO):
        upsert_contacto(tel, pago=1, respondio=1, etapa="cerrado")
        enviar_texto(tel, MSG_GRACIAS)
        return

    # Contacto nuevo -> iniciar embudo
    if c is None:
        iniciar_embudo(tel)
        return

    # Ya estaba en el embudo y respondio -> marcar (detiene auto-seguimiento)
    upsert_contacto(tel, respondio=1)

    # Si pide formas de pago directamente
    if any(p in texto_low for p in PALABRAS_PIDE_PAGO):
        enviar_texto(tel, MSG_PAGO)
        upsert_contacto(tel, etapa="pago_enviado", ultimo_envio=datetime.utcnow().isoformat())
        return

    # Si muestra interes general -> oferta
    if any(p in texto_low for p in PALABRAS_INTERES):
        enviar_texto(tel, MSG_OFERTA)
        upsert_contacto(tel, etapa="oferta_enviada", ultimo_envio=datetime.utcnow().isoformat())
        return

    # Respuesta que no entendemos -> atencion humana
    upsert_contacto(tel, etapa="atencion_humana")
    print(f"[ATENCION HUMANA] {tel} escribio: {texto}")

# ------------------------------------------------------------------
#  SEGUIMIENTOS AUTOMATICOS  (hilo en segundo plano)
# ------------------------------------------------------------------
def revisar_seguimientos():
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

                if etapa == "muestra_enviada" and horas >= 4:
                    enviar_texto(tel, MSG_OFERTA)
                    upsert_contacto(tel, etapa="seguimiento1", ultimo_envio=ahora.isoformat())

                elif etapa == "seguimiento1" and horas >= 24:
                    enviar_texto(tel, MSG_SEG1)
                    upsert_contacto(tel, etapa="seguimiento2", ultimo_envio=ahora.isoformat())

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
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Token invalido", 403

@app.route("/webhook", methods=["POST"])
def recibir_mensaje():
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
