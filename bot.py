"""
Bot de ventas - Santiago: La madurez del discipulo (KIT COMPLETO)
En Pos de Ti / Ele Media
WhatsApp Cloud API (Meta) + Flask

Mejoras v3:
- Embudo que AVANZA: bienvenida+PDF -> oferta -> pago -> cierre
- Responde SIEMPRE a precio/info/pago sin importar la etapa
- AVISA al dueno por WhatsApp cuando alguien dice algo fuera de guion
- Comando "reiniciar" borra el registro del contacto (para pruebas)
"""

import os
import time
import threading
import sqlite3
from datetime import datetime

import requests
from flask import Flask, request

# ------------------------------------------------------------------
#  CONFIGURACION  (variables de entorno - se ponen en Render)
# ------------------------------------------------------------------
TOKEN        = os.environ.get("WHATSAPP_TOKEN", "")
PHONE_ID     = os.environ.get("WHATSAPP_PHONE_ID", "")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "enposdeti2026")
LINK_MUESTRA = os.environ.get("LINK_MUESTRA", "")
PRECIO       = os.environ.get("PRECIO", "299")

# Numero del DUENO para recibir avisos de atencion humana (formato internacional sin +)
# Ej: 5215579177044
DUENO_TEL    = os.environ.get("DUENO_TEL", "")

API_URL = f"https://graph.facebook.com/v21.0/{PHONE_ID}/messages"

app = Flask(__name__)

# ------------------------------------------------------------------
#  MENSAJES
# ------------------------------------------------------------------
MSG_BIENVENIDA = (
    "Hola! Que gusto saludarte. 🙏\n\n"
    "Te comparto una leccion de muestra del curso *Santiago: La madurez del discipulo*, "
    "un estudio completo del libro de Santiago para vivir una fe que se note en la vida diaria.\n\n"
    "Aqui te la dejo, revisala con calma. En un momento te cuento que incluye el curso completo."
)

MSG_OFERTA = (
    "El curso completo no es solo un libro: es un *kit listo para ensenar*, con 14 lecciones "
    "que recorren toda la carta de Santiago. Incluye tres piezas:\n\n"
    "📘 *Manual del Alumno* - el cuaderno que sigue cada persona\n"
    "📗 *Guia del Maestro* - todo para dirigir la clase paso a paso (no necesitas experiencia)\n"
    "📊 *Presentacion* - el curso en diapositivas para proyectar\n\n"
    "Sirve para tu grupo, tu celula, tu clase de iglesia o estudio personal. Lo imprimes y lo usas "
    "las veces que quieras.\n\n"
    f"Todo el kit en PDF por *${PRECIO} MXN*.\n\n"
    "Si quieres, te paso las formas de pago. Solo dime *pago*."
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

MSG_GRACIAS = (
    "Mil gracias! 🙏 En cuanto confirme tu pago te envio el kit completo: "
    "Manual del Alumno, Guia del Maestro y Presentacion. Dios te bendiga."
)

MSG_NO_ENTIENDO = (
    "Gracias por tu mensaje. 🙏 Permiteme un momento para responderte personalmente, "
    "en breve te contesto."
)

MSG_PRECIO_RAPIDO = (
    f"El curso completo *Santiago: La madurez del discipulo* (kit de 14 lecciones: "
    f"Alumno + Maestro + Presentacion) tiene un costo de *${PRECIO} MXN*.\n\n"
    "Si quieres las formas de pago, escribe *pago*."
)

MSG_SEG1 = (
    "Hola de nuevo. 🙏 Solo queria saber si pudiste revisar la leccion de muestra.\n\n"
    f"Si quieres el kit completo (Alumno + Maestro + Presentacion), sigue disponible por ${PRECIO} MXN. "
    "Escribe *pago* y te paso las formas."
)

MSG_SEG2 = (
    "A veces uno lo deja para despues y se pasa el tiempo.\n\n"
    "Si algo te detiene, sea el precio o alguna duda, dimelo y lo platicamos. "
    "El kit sigue aqui cuando estes listo."
)

# ------------------------------------------------------------------
#  DETECCION DE INTENCIONES (palabras clave)
# ------------------------------------------------------------------
def es_saludo(t):
    return any(p in t for p in ["hola", "buenas", "buenos dias", "buenas tardes",
                                 "buenas noches", "info", "informacion", "me interesa",
                                 "quiero el curso", "santiago", "curso"])

def es_precio(t):
    return any(p in t for p in ["precio", "cuanto", "cuesta", "vale", "costo"])

def es_pide_pago(t):
    return any(p in t for p in ["pago", "pagar", "formas de pago", "como pago",
                                 "deposito", "transferencia", "comprar", "clabe", "oxxo"])

def es_comprobante(t):
    return any(p in t for p in ["comprobante", "ya pague", "ya transferi", "deposite",
                                 "listo el pago", "hice el pago", "ya hice", "transferencia hecha",
                                 "ya deposite"])

def es_si(t):
    return t.strip() in ["si", "sí", "claro", "ok", "va", "dale", "quiero", "sale"]

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

def borrar_contacto(tel):
    with db() as conn:
        conn.execute("DELETE FROM contactos WHERE telefono=?", (tel,))

# ------------------------------------------------------------------
#  ENVIO DE MENSAJES
# ------------------------------------------------------------------
def enviar_texto(tel, texto):
    _post({
        "messaging_product": "whatsapp",
        "to": tel,
        "type": "text",
        "text": {"body": texto},
    })

def enviar_documento_url(tel, url, nombre_archivo, caption=""):
    _post({
        "messaging_product": "whatsapp",
        "to": tel,
        "type": "document",
        "document": {"link": url, "filename": nombre_archivo, "caption": caption},
    })

def _post(payload):
    headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
    try:
        r = requests.post(API_URL, headers=headers, json=payload, timeout=30)
        if r.status_code >= 400:
            print("Error al enviar:", r.status_code, r.text)
    except Exception as e:
        print("Excepcion al enviar:", e)

def avisar_dueno(tel_cliente, texto_cliente):
    """Manda un WhatsApp al dueno avisando que un cliente necesita atencion."""
    if not DUENO_TEL:
        print(f"[ATENCION HUMANA] {tel_cliente} escribio: {texto_cliente}")
        return
    aviso = (f"⚠️ Un cliente necesita tu atencion.\n\n"
             f"Numero: {tel_cliente}\n"
             f"Escribio: {texto_cliente}\n\n"
             f"Entra a responderle personalmente.")
    enviar_texto(DUENO_TEL, aviso)

# ------------------------------------------------------------------
#  LOGICA DEL EMBUDO
# ------------------------------------------------------------------
def iniciar_embudo(tel):
    enviar_texto(tel, MSG_BIENVENIDA)
    if LINK_MUESTRA:
        enviar_documento_url(tel, LINK_MUESTRA,
                             "Santiago - Leccion de muestra.pdf",
                             "Leccion de muestra 🙏")
    # Mandamos la oferta un instante despues para que llegue despues del PDF
    enviar_texto(tel, MSG_OFERTA)
    upsert_contacto(tel, etapa="oferta_enviada",
                    ultimo_envio=datetime.utcnow().isoformat(),
                    respondio=0, pago=0)

def manejar_respuesta(tel, texto):
    texto_low = texto.lower().strip()

    # Comando de prueba: reinicia el contacto desde cero
    if texto_low == "reiniciar":
        borrar_contacto(tel)
        enviar_texto(tel, "(Listo, reinicie tu conversacion. Escribe 'hola' para empezar de nuevo.)")
        return

    c = get_contacto(tel)

    # --- Cosas que respondemos SIEMPRE, sin importar la etapa ---

    # Comprobante de pago
    if es_comprobante(texto_low):
        upsert_contacto(tel, pago=1, respondio=1, etapa="cerrado")
        enviar_texto(tel, MSG_GRACIAS)
        avisar_dueno(tel, f"PAGO RECIBIDO (revisa comprobante): {texto}")
        return

    # Pide formas de pago
    if es_pide_pago(texto_low):
        enviar_texto(tel, MSG_PAGO)
        upsert_contacto(tel, etapa="pago_enviado",
                        ultimo_envio=datetime.utcnow().isoformat(), respondio=1)
        return

    # Pregunta el precio (aunque ya se lo hayamos dado antes)
    if es_precio(texto_low):
        enviar_texto(tel, MSG_PRECIO_RAPIDO)
        if c:
            upsert_contacto(tel, respondio=1)
        else:
            upsert_contacto(tel, etapa="oferta_enviada",
                            ultimo_envio=datetime.utcnow().isoformat(), respondio=1)
        return

    # --- Logica por etapa ---

    # Contacto nuevo -> embudo completo (bienvenida + PDF + oferta)
    if c is None:
        iniciar_embudo(tel)
        return

    # Ya existe: si dice "si" tras ver la oferta -> mandar formas de pago
    if es_si(texto_low):
        enviar_texto(tel, MSG_PAGO)
        upsert_contacto(tel, etapa="pago_enviado",
                        ultimo_envio=datetime.utcnow().isoformat(), respondio=1)
        return

    # Saludo de alguien que ya existe -> reenvia la oferta (sin repetir bienvenida)
    if es_saludo(texto_low):
        enviar_texto(tel, MSG_OFERTA)
        upsert_contacto(tel, etapa="oferta_enviada",
                        ultimo_envio=datetime.utcnow().isoformat(), respondio=1)
        return

    # Cualquier otra cosa -> no entiendo -> aviso al dueno
    enviar_texto(tel, MSG_NO_ENTIENDO)
    upsert_contacto(tel, etapa="atencion_humana", respondio=1)
    avisar_dueno(tel, texto)

# ------------------------------------------------------------------
#  SEGUIMIENTOS AUTOMATICOS
# ------------------------------------------------------------------
def revisar_seguimientos():
    while True:
        try:
            ahora = datetime.utcnow()
            with db() as conn:
                filas = conn.execute(
                    "SELECT * FROM contactos WHERE pago=0 AND respondio=0 "
                    "AND etapa IN ('oferta_enviada','seguimiento1')"
                ).fetchall()

            for f in filas:
                c = dict(f)
                ultimo = datetime.fromisoformat(c["ultimo_envio"])
                horas = (ahora - ultimo).total_seconds() / 3600
                tel = c["telefono"]
                etapa = c["etapa"]

                if etapa == "oferta_enviada" and horas >= 24:
                    enviar_texto(tel, MSG_SEG1)
                    upsert_contacto(tel, etapa="seguimiento1", ultimo_envio=ahora.isoformat())

                elif etapa == "seguimiento1" and horas >= 24:
                    enviar_texto(tel, MSG_SEG2)
                    upsert_contacto(tel, etapa="seguimiento2", ultimo_envio=ahora.isoformat())

        except Exception as e:
            print("Error en seguimientos:", e)

        time.sleep(1800)

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
            else:
                # Si manda imagen/audio/etc (ej. comprobante en foto) -> aviso al dueno
                avisar_dueno(tel, f"[Envio un archivo/imagen tipo: {msg.get('type')}]")
                enviar_texto(tel, MSG_NO_ENTIENDO)
                return "OK", 200
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
