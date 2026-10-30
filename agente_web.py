
"""
Agente personal - VERSIÓN WEB (para usar desde el móvil, la tablet o el ordenador)

El ordenador donde se ejecuta hace de "servidor": el móvil solo abre una página en el navegador.
La interfaz (HTML + CSS + JavaScript) va incluida en este mismo archivo, en las constantes HTML,
ESTILOS y SCRIPT, y se sirve con una política de seguridad estricta (sin código incrustado).

REQUISITOS
    pip install flask langchain-google-genai langgraph pypdf python-docx

IMPORTANTE
    Este archivo debe estar en la MISMA carpeta que agente_personal_gemini.py (el motor).
    Comparte las carpetas datos_agente, codigo y documentos con la versión de escritorio,
    así que las conversaciones, tareas y apuntes son los mismos. Usa solo una de las dos
    versiones a la vez.

USO
    python agente_web.py
    Abre http://localhost:8765 en este ordenador e introduce el PIN que aparece en la terminal.

    python agente_web.py --movil
    Para usarlo desde otro dispositivo de la misma wifi, usa esta opción y abre en ese
    dispositivo la dirección de red que aparece en la terminal. Necesitarás el PIN.

OPCIONES (variables de entorno, opcionales)
    AGENTE_PIN      PIN de acceso fijo (si no, se genera uno y se guarda en datos_agente/pin_web.txt)
    AGENTE_PUERTO   puerto (por defecto 8765)
"""

import argparse
import builtins
import importlib
import io
import json
import os
import re
import secrets
import socket
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_file, session

# ----------------------------------------------------------------------------
# Rutas y ajustes
# ----------------------------------------------------------------------------

if getattr(sys, "frozen", False):
    CARPETA_APP = Path(sys.executable).resolve().parent
else:
    CARPETA_APP = Path(__file__).resolve().parent
os.chdir(CARPETA_APP)

CARPETA_DATOS = CARPETA_APP / "datos_agente"
CARPETA_CONVERSACIONES = CARPETA_DATOS / "conversaciones"
CARPETA_DOCS = CARPETA_APP / "documentos"
CONFIG = Path(os.environ.get("APPDATA", str(CARPETA_APP))) / "AgentePersonal" / "config.json"

CARPETA_FOTOS = CARPETA_APP / "fotos"
EXTENSIONES_DOCS = {".pdf", ".docx", ".txt", ".md", ".csv", ".html", ".json", ".xml"}
EXTENSIONES_FOTOS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
PUERTO = int(os.environ.get("AGENTE_PUERTO", "8765"))
TITULO_POR_DEFECTO = "Nuevo chat"
ID_VALIDO = re.compile(r"^[0-9a-f]{12}$")

NOMBRES_HERRAMIENTAS = {
    "fecha_hora_actual": "consultando la fecha",
    "anadir_tarea": "añadiendo una tarea",
    "listar_tareas": "mirando tus tareas",
    "completar_tarea": "completando una tarea",
    "guardar_apunte": "guardando un apunte",
    "leer_apuntes": "leyendo tus apuntes",
    "eliminar_apunte": "eliminando un apunte",
    "guardar_tarjetas": "guardando tarjetas",
    "leer_tarjetas": "leyendo tus tarjetas",
    "listar_archivos_codigo": "mirando la carpeta de código",
    "leer_archivo_codigo": "leyendo tu código",
    "guardar_codigo_corregido": "preparando la corrección",
    "listar_documentos": "mirando tus documentos",
    "leer_documento": "leyendo tu documento",
    "listar_fotos": "mirando tus fotos",
    "redimensionar_foto": "redimensionando una foto",
    "recortar_foto": "recortando una foto",
    "girar_foto": "girando una foto",
    "ajustar_foto": "ajustando una foto",
    "filtro_foto": "aplicando un filtro",
    "anadir_texto_foto": "escribiendo sobre una foto",
    "convertir_foto": "convirtiendo una foto",
}

# Título corto y categoría de cada herramienta, para el panel y los pasos de la interfaz
TITULOS_HERRAMIENTAS = {
    "fecha_hora_actual": ("Consultar la fecha", "General"),
    "anadir_tarea": ("Añadir tarea", "Tareas"),
    "listar_tareas": ("Ver tareas", "Tareas"),
    "completar_tarea": ("Completar tarea", "Tareas"),
    "guardar_apunte": ("Guardar apunte", "Estudio"),
    "leer_apuntes": ("Leer apuntes", "Estudio"),
    "eliminar_apunte": ("Eliminar apunte", "Estudio"),
    "guardar_tarjetas": ("Crear tarjetas", "Estudio"),
    "leer_tarjetas": ("Leer tarjetas", "Estudio"),
    "listar_documentos": ("Ver documentos", "Documentos"),
    "leer_documento": ("Leer documento", "Documentos"),
    "listar_archivos_codigo": ("Ver archivos de código", "Código"),
    "leer_archivo_codigo": ("Leer código", "Código"),
    "guardar_codigo_corregido": ("Corregir código", "Código"),
    "listar_fotos": ("Ver fotos", "Fotos"),
    "redimensionar_foto": ("Redimensionar foto", "Fotos"),
    "recortar_foto": ("Recortar foto", "Fotos"),
    "girar_foto": ("Girar foto", "Fotos"),
    "ajustar_foto": ("Ajustar foto", "Fotos"),
    "filtro_foto": ("Aplicar filtro", "Fotos"),
    "anadir_texto_foto": ("Escribir sobre la foto", "Fotos"),
    "convertir_foto": ("Convertir o comprimir foto", "Fotos"),
}

nucleo = None  # aquí se carga agente_personal_gemini (el motor)


# ----------------------------------------------------------------------------
# Conversaciones (mismo formato que la versión de escritorio)
# ----------------------------------------------------------------------------

def ahora() -> str:
    return datetime.now().isoformat(timespec="milliseconds")  # milisegundos: ordena bien chats creados a la vez


def ruta_conversacion(id_conv: str) -> Path:
    return CARPETA_CONVERSACIONES / f"{id_conv}.json"


def guardar_conversacion(conv: dict) -> None:
    CARPETA_CONVERSACIONES.mkdir(parents=True, exist_ok=True)
    ruta_conversacion(conv["id"]).write_text(
        json.dumps(conv, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def cargar_conversacion(id_conv: str) -> dict | None:
    if not ID_VALIDO.match(id_conv or ""):
        return None
    try:
        return json.loads(ruta_conversacion(id_conv).read_text(encoding="utf-8"))
    except Exception:
        return None


def cargar_indice() -> list:
    indice = []
    if CARPETA_CONVERSACIONES.exists():
        for archivo in CARPETA_CONVERSACIONES.glob("*.json"):
            try:
                d = json.loads(archivo.read_text(encoding="utf-8"))
                indice.append({
                    "id": d["id"],
                    "titulo": d.get("titulo") or TITULO_POR_DEFECTO,
                    "actualizada": d.get("actualizada", ""),
                })
            except Exception:
                continue
    indice.sort(key=lambda c: c["actualizada"], reverse=True)
    return indice


def nueva_conversacion() -> dict:
    momento = ahora()
    return {
        "id": uuid.uuid4().hex[:12], "titulo": TITULO_POR_DEFECTO, "titulo_auto": True,
        "creada": momento, "actualizada": momento, "mensajes": [],
    }


def resumen_titulo(texto: str) -> str:
    limpio = re.sub(r"\s+", " ", texto).strip()
    return limpio if len(limpio) <= 40 else limpio[:39] + "…"


def historial_desde_mensajes(mensajes: list) -> list:
    """Reconstruye lo que ve el agente; descarta preguntas que acabaron en error."""
    historial, pendiente = [], None
    for m in mensajes:
        if m["rol"] == "usuario":
            pendiente = m["texto"]
        elif m["rol"] == "agente" and pendiente is not None:
            historial += [("user", pendiente), ("assistant", m["texto"])]
            pendiente = None
        elif m["rol"] == "error":
            pendiente = None
    return historial


def traducir_error(mensaje: str) -> str:
    m = mensaje.lower()
    if "429" in mensaje or "quota" in m or "resource_exhausted" in m:
        texto = "Has llegado al límite gratuito de Gemini. Espera unos minutos y vuelve a intentarlo."
    elif "api key" in m or "api_key" in m or "permission_denied" in m or "401" in mensaje or "403" in mensaje:
        texto = "Google ha rechazado la clave de Gemini. Abre «Clave de Gemini» en el menú para cambiarla."
    elif "not_found" in m or "404" in mensaje:
        texto = "El modelo de Gemini no está disponible. Cambia su nombre en agente_personal_gemini.py."
    elif "recursion" in m:
        texto = "El agente ha dado demasiadas vueltas. Prueba a pedirlo de forma más sencilla."
    else:
        texto = "Ha ocurrido un error inesperado."
    return f"{texto}\n\nDetalle técnico: {mensaje[:300]}"


# ----------------------------------------------------------------------------
# Trabajo del agente (un único trabajo a la vez) y confirmaciones
# ----------------------------------------------------------------------------

LOCK = threading.Lock()
JOB = {"ocupado": False, "estado": "", "confirmacion": None, "chat_id": None, "pasos": []}
CANCELAR = threading.Event()  # el usuario pulsó "Detener"


class Detenido(Exception):
    """El usuario detuvo la respuesta."""
CONFIRMACION = {"evento": None, "si": False}
LOCAL = threading.local()


class Capturador:
    """Recoge lo que imprimen las herramientas del agente SOLO en el hilo de trabajo
    (por ejemplo, los cambios propuestos en un archivo) para enseñarlo en el móvil."""

    def __init__(self, real):
        self.real = real
        self.buffer = io.StringIO()

    def write(self, texto):
        if getattr(LOCAL, "capturando", False):
            return self.buffer.write(texto)
        return self.real.write(texto)

    def flush(self):
        self.real.flush()

    def vaciar(self) -> str:
        texto = self.buffer.getvalue().strip()
        self.buffer.seek(0)
        self.buffer.truncate(0)
        return texto

    def __getattr__(self, nombre):
        return getattr(self.real, nombre)


CAPTURA = None


def input_web(pregunta: str = "") -> str:
    """Sustituye al input() de las herramientas: pide la confirmación en el navegador."""
    texto = (CAPTURA.vaciar() if CAPTURA else "") or pregunta
    evento = threading.Event()
    with LOCK:
        CONFIRMACION["evento"] = evento
        CONFIRMACION["si"] = False
        JOB["confirmacion"] = texto
    respondido = evento.wait(timeout=300)  # si nadie contesta en 5 minutos, se cancela
    with LOCK:
        JOB["confirmacion"] = None
        aceptado = CONFIRMACION["si"]
    return "s" if respondido and aceptado else "n"


def trabajar(chat_id: str, texto: str):
    LOCAL.capturando = True
    rol, resultado = "error", "Error desconocido."
    try:
        conv = cargar_conversacion(chat_id)
        historial = historial_desde_mensajes(conv["mensajes"][:-1]) + [("user", texto)]
        estado_final = None
        for estado in nucleo.agente.stream(
            {"messages": historial}, config={"recursion_limit": 15}, stream_mode="values"
        ):
            if CANCELAR.is_set():  # solo se puede parar entre un paso y el siguiente
                raise Detenido()
            estado_final = estado
            llamadas = getattr(estado["messages"][-1], "tool_calls", None)
            if llamadas:
                nombres = ", ".join(NOMBRES_HERRAMIENTAS.get(c["name"], c["name"]) for c in llamadas)
                with LOCK:
                    JOB["estado"] = f"Agente {nombres}..."
                    JOB["pasos"] += [TITULOS_HERRAMIENTAS.get(c["name"], (c["name"],))[0] for c in llamadas]
        if CANCELAR.is_set():
            raise Detenido()
        if estado_final is None:
            raise RuntimeError("El agente no devolvió ninguna respuesta.")
        rol = "agente"
        resultado = nucleo.a_texto(estado_final["messages"][-1].content) or "(sin respuesta)"
    except Detenido:
        rol, resultado = "error", "Respuesta detenida por ti. Puedes volver a preguntar cuando quieras."
    except Exception as error:
        rol, resultado = "error", traducir_error(str(error))
    finally:
        try:
            conv = cargar_conversacion(chat_id)
            if conv is not None:
                conv["mensajes"].append({"rol": rol, "texto": resultado})
                conv["actualizada"] = ahora()
                guardar_conversacion(conv)
        except Exception:
            pass
        with LOCK:
            JOB.update(ocupado=False, estado="", confirmacion=None)
            CANCELAR.clear()


# ----------------------------------------------------------------------------
# Acceso: PIN y sesión
# ----------------------------------------------------------------------------

def leer_o_crear(nombre: str, generar) -> str:
    CARPETA_DATOS.mkdir(exist_ok=True)
    ruta = CARPETA_DATOS / nombre
    try:
        valor = ruta.read_text(encoding="utf-8").strip()
        if valor:
            return valor
    except OSError:
        pass
    valor = generar()
    ruta.write_text(valor, encoding="utf-8")
    return valor


def obtener_pin() -> str:
    return os.environ.get("AGENTE_PIN") or leer_o_crear("pin_web.txt", lambda: f"{secrets.randbelow(10**6):06d}")


app = Flask(__name__, static_folder=None)
app.json.ensure_ascii = False
app.config.update(
    MAX_CONTENT_LENGTH=60 * 1024 * 1024,   # máximo 60 MB por subida (las fotos del móvil pesan)
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_HTTPONLY=True,
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)
POLITICA_CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; font-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)
INTENTOS: dict = {}  # ip -> [fallos, bloqueado_hasta]


def requiere_login(funcion):
    @wraps(funcion)
    def envoltorio(*args, **kwargs):
        if not session.get("ok"):
            return jsonify(error="Necesitas el PIN."), 401
        return funcion(*args, **kwargs)
    return envoltorio


@app.after_request
def cabeceras_seguridad(respuesta):
    """Sin caché y con una política que solo permite código y estilos de este mismo servidor."""
    respuesta.headers["Cache-Control"] = "no-store"
    respuesta.headers.setdefault("Content-Security-Policy", POLITICA_CSP)
    respuesta.headers.setdefault("X-Content-Type-Options", "nosniff")
    respuesta.headers.setdefault("Referrer-Policy", "no-referrer")
    respuesta.headers.setdefault("X-Frame-Options", "DENY")
    respuesta.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    return respuesta


@app.get("/api/sesion")
def sesion_actual():
    """Dice si hay sesión iniciada. Responde siempre 200, para que el navegador no registre errores."""
    return jsonify(autenticado=bool(session.get("ok")))


@app.post("/api/login")
def login():
    ip = request.remote_addr or "?"
    fallos, bloqueado = INTENTOS.get(ip, [0, 0])
    if time.time() < bloqueado:
        return jsonify(error="Demasiados intentos. Espera un minuto."), 429
    pin = str((request.get_json(silent=True) or {}).get("pin", "")).strip()
    if secrets.compare_digest(pin, PIN):
        INTENTOS.pop(ip, None)
        session.permanent = True
        session["ok"] = True
        return jsonify(ok=True)
    fallos += 1
    INTENTOS[ip] = [fallos, time.time() + 60 if fallos >= 5 else 0]
    if fallos >= 5:
        INTENTOS[ip][0] = 0
    return jsonify(error="PIN incorrecto."), 403


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@app.get("/api/configuracion")
@requiere_login
def configuracion():
    return jsonify(clave_configurada=bool(nucleo is not None and hay_clave()))


def cargar_motor():
    global nucleo
    if nucleo is None:
        nucleo = importlib.import_module("agente_personal")
    else:
        nucleo = importlib.reload(nucleo)
    return nucleo


class ClaveEnUso(Exception):
    pass


class ErrorGuardarClave(Exception):
    pass


def restaurar_clave(google_anterior, gemini_anterior, motor_anterior, modulo_en_cache):
    global nucleo
    if google_anterior is None:
        os.environ.pop("GOOGLE_API_KEY", None)
    else:
        os.environ["GOOGLE_API_KEY"] = google_anterior
    if gemini_anterior is None:
        os.environ.pop("GEMINI_API_KEY", None)
    else:
        os.environ["GEMINI_API_KEY"] = gemini_anterior
    if motor_anterior is not None:
        nucleo = importlib.reload(motor_anterior)
    elif modulo_en_cache is None:
        sys.modules.pop("agente_personal", None)
        nucleo = None


def configurar_clave(clave):
    global nucleo
    google_anterior = os.environ.get("GOOGLE_API_KEY")
    gemini_anterior = os.environ.get("GEMINI_API_KEY")
    motor_anterior = nucleo
    modulo_en_cache = sys.modules.get("agente_personal")
    archivo_temporal = CONFIG.with_name(CONFIG.name + ".tmp")

    with LOCK:
        if JOB["ocupado"]:
            raise ClaveEnUso("Espera a que termine el trabajo actual para cambiar la clave.")
        JOB.update(ocupado=True, estado="Comprobando la clave de Gemini...", confirmacion=None)

    try:
        os.environ["GOOGLE_API_KEY"] = clave
        os.environ.pop("GEMINI_API_KEY", None)
        motor = cargar_motor()
        motor.modelo.invoke("Responde únicamente con OK.")

        try:
            CONFIG.parent.mkdir(parents=True, exist_ok=True)
            archivo_temporal.write_text(
                json.dumps({"clave": clave}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(archivo_temporal, CONFIG)
        except OSError as error:
            raise ErrorGuardarClave(
                "Gemini aceptó la clave, pero no se pudo guardar en la configuración de este ordenador. "
                "Revisa los permisos de la carpeta de usuario."
            ) from error
    except Exception:
        restaurar_clave(google_anterior, gemini_anterior, motor_anterior, modulo_en_cache)
        try:
            archivo_temporal.unlink()
        except FileNotFoundError:
            pass
        raise
    finally:
        with LOCK:
            JOB.update(ocupado=False, estado="", confirmacion=None)


def error_configurar_clave(error, clave):
    detalle = str(error).replace(clave, "[oculta]")
    normalizado = detalle.lower()
    if "api_key_invalid" in normalizado or "api key not valid" in normalizado:
        return "Google no acepta esa clave. Revisa que la hayas copiado completa desde Google AI Studio."
    if "429" in detalle or "quota" in normalizado or "resource_exhausted" in normalizado:
        return "Gemini no pudo comprobar la clave porque se alcanzó un límite o cuota. Revisa tu cuota e inténtalo de nuevo."
    if "permission_denied" in normalizado or "403" in detalle:
        return "Google no autorizó la clave para este modelo. Revisa la clave y su acceso en Google AI Studio."
    if isinstance(error, ErrorGuardarClave):
        return str(error)
    return "No se pudo comprobar la clave. Revisa tu conexión e inténtalo de nuevo. Detalle: " + detalle[:240]


@app.post("/api/configuracion/clave")
@requiere_login
def guardar_clave():
    if request.remote_addr not in {"127.0.0.1", "::1"}:
        return jsonify(error="Por seguridad, configura la clave desde el navegador del ordenador donde se ejecuta el agente."), 403
    datos = request.get_json(silent=True)
    clave = datos.get("clave") if isinstance(datos, dict) else None
    if not isinstance(clave, str):
        return jsonify(error="Escribe una clave de Gemini válida."), 400
    clave = clave.strip()
    if not clave or len(clave) > 2048:
        return jsonify(error="Escribe una clave de Gemini válida."), 400
    try:
        configurar_clave(clave)
    except ClaveEnUso as error:
        return jsonify(error=str(error)), 409
    except ErrorGuardarClave as error:
        return jsonify(error=str(error)), 500
    except Exception as error:
        return jsonify(error=error_configurar_clave(error, clave)), 502
    return jsonify(ok=True)


# ----------------------------------------------------------------------------
# API
# ----------------------------------------------------------------------------

@app.get("/api/chats")
@requiere_login
def listar_chats():
    return jsonify(cargar_indice())


@app.get("/api/chats/<id_conv>")
@requiere_login
def ver_chat(id_conv):
    conv = cargar_conversacion(id_conv)
    if conv is None:
        return jsonify(error="No existe esa conversación."), 404
    return jsonify(id=conv["id"], titulo=conv["titulo"], mensajes=conv["mensajes"])


@app.patch("/api/chats/<id_conv>")
@requiere_login
def renombrar_chat(id_conv):
    conv = cargar_conversacion(id_conv)
    titulo = re.sub(r"\s+", " ", str((request.get_json(silent=True) or {}).get("titulo", ""))).strip()[:60]
    if conv is None or not titulo:
        return jsonify(error="Datos no válidos."), 400
    conv["titulo"] = titulo
    conv["titulo_auto"] = False
    guardar_conversacion(conv)
    return jsonify(ok=True)


@app.delete("/api/chats/<id_conv>")
@requiere_login
def borrar_chat(id_conv):
    if not ID_VALIDO.match(id_conv):
        return jsonify(error="Id no válido."), 400
    with LOCK:
        if JOB["ocupado"] and JOB["chat_id"] == id_conv:
            return jsonify(error="El agente está trabajando en esta conversación."), 409
    try:
        ruta_conversacion(id_conv).unlink()
    except OSError:
        pass
    return jsonify(ok=True)


@app.post("/api/enviar")
@requiere_login
def enviar():
    if nucleo is None:
        return jsonify(error="Primero configura tu clave de Gemini con el botón «Clave de Gemini»."), 503
    datos = request.get_json(silent=True) or {}
    texto = str(datos.get("texto") or "").strip()
    chat_id = datos.get("chat_id")
    if not texto or len(texto) > 8000:
        return jsonify(error="Escribe un mensaje (máximo 8000 caracteres)."), 400
    with LOCK:
        if JOB["ocupado"]:
            return jsonify(error="El agente está ocupado con otra petición."), 409
        conv = None
        if chat_id:
            conv = cargar_conversacion(str(chat_id))
            if conv is None:
                return jsonify(error="No existe esa conversación."), 404
        if conv is None:
            conv = nueva_conversacion()
        if not conv["mensajes"] and conv.get("titulo_auto", True):
            conv["titulo"] = resumen_titulo(texto)
        conv["mensajes"].append({"rol": "usuario", "texto": texto})
        conv["actualizada"] = ahora()
        guardar_conversacion(conv)
        CANCELAR.clear()
        JOB.update(ocupado=True, estado="Pensando...", confirmacion=None, chat_id=conv["id"], pasos=[])
    threading.Thread(target=trabajar, args=(conv["id"], texto), daemon=True).start()
    return jsonify(chat_id=conv["id"])


@app.get("/api/estado")
@requiere_login
def estado():
    with LOCK:
        return jsonify(
            ocupado=JOB["ocupado"], estado=JOB["estado"],
            confirmacion=JOB["confirmacion"], chat_id=JOB["chat_id"], pasos=list(JOB["pasos"]),
        )


@app.post("/api/confirmar")
@requiere_login
def confirmar():
    si = bool((request.get_json(silent=True) or {}).get("si"))
    with LOCK:
        evento = CONFIRMACION["evento"]
        if evento is None or JOB["confirmacion"] is None:
            return jsonify(error="No hay nada que confirmar."), 409
        CONFIRMACION["si"] = si
    evento.set()
    return jsonify(ok=True)


def limpiar_nombre(nombre: str) -> str:
    nombre = Path(nombre.replace("\\", "/")).name
    nombre = re.sub(r"[^\w.\- ()]", "_", nombre).strip(" .")
    return nombre[:120]


@app.post("/api/subir")
@requiere_login
def subir():
    """Las fotos van a la carpeta 'fotos' y el resto de archivos a 'documentos'."""
    subidos, fotos, rechazados = [], [], []
    for archivo in request.files.getlist("archivos"):
        nombre = limpiar_nombre(archivo.filename or "")
        extension = Path(nombre).suffix.lower()
        if nombre and extension in EXTENSIONES_FOTOS:
            carpeta, lista = CARPETA_FOTOS, fotos
        elif nombre and extension in EXTENSIONES_DOCS:
            carpeta, lista = CARPETA_DOCS, subidos
        else:
            rechazados.append(archivo.filename or "(sin nombre)")
            continue
        carpeta.mkdir(exist_ok=True)
        destino = carpeta / nombre
        contador = 2
        while destino.exists():  # no se sobrescribe nada
            destino = carpeta / f"{Path(nombre).stem}_{contador}{Path(nombre).suffix}"
            contador += 1
        archivo.save(destino)
        lista.append(destino.name)
    return jsonify(subidos=subidos, fotos=fotos, rechazados=rechazados)


@app.get("/api/foto/<path:nombre>")
@requiere_login
def ver_foto(nombre):
    """Sirve una foto (primero entre las editadas y luego entre las originales)."""
    limpio = Path(nombre).name
    if Path(limpio).suffix.lower() in EXTENSIONES_FOTOS:
        for carpeta in (CARPETA_FOTOS / "editadas", CARPETA_FOTOS):
            ruta = carpeta / limpio
            if ruta.is_file():
                return send_file(ruta, conditional=False)
    return jsonify(error="No existe esa foto."), 404


@app.post("/api/detener")
@requiere_login
def detener():
    """Pide parar la respuesta. El agente se detiene al terminar el paso que está haciendo."""
    with LOCK:
        if not JOB["ocupado"]:
            return jsonify(error="No hay nada que detener."), 409
        CANCELAR.set()
        JOB["estado"] = "Deteniendo..."
        evento = CONFIRMACION["evento"]
        esperando = JOB["confirmacion"] is not None
        if esperando:
            CONFIRMACION["si"] = False  # una confirmación pendiente se da por rechazada
    if esperando and evento is not None:
        evento.set()
    return jsonify(ok=True)


def _leer_lista(nombre: str) -> list:
    try:
        datos = json.loads((CARPETA_DATOS / nombre).read_text(encoding="utf-8"))
        return datos if isinstance(datos, list) else []
    except Exception:
        return []


def _archivos(carpeta: Path, extensiones: set, editadas: bool = False) -> list:
    salida = []
    if carpeta.is_dir():
        for f in sorted(carpeta.iterdir()):
            if f.is_file() and f.suffix.lower() in extensiones:
                salida.append({"nombre": f.name, "kb": max(1, f.stat().st_size // 1024), "editada": editadas})
    return salida[:60]


def _descripcion(nombre: str) -> str:
    """Primera frase de la descripción que el propio agente lee de cada herramienta."""
    herramienta = getattr(nucleo, nombre, None)
    texto = getattr(herramienta, "description", None) or getattr(herramienta, "__doc__", None) or ""
    texto = " ".join(str(texto).split())
    return re.split(r"(?<=[.!?])\s", texto)[0][:170] if texto else "Sin descripción."


@app.get("/api/contexto")
@requiere_login
def contexto():
    """Datos reales del agente: lo que tiene guardado y las herramientas que puede usar."""
    tareas = [t for t in _leer_lista("tareas.json") if isinstance(t, dict)]
    pendientes = sorted((t for t in tareas if not t.get("hecha")), key=lambda t: t.get("fecha_limite") or "9999-99-99")
    return jsonify(
        resumen={
            "tareas_pendientes": len(pendientes),
            "apuntes": len(_leer_lista("apuntes.json")),
            "tarjetas": len(_leer_lista("tarjetas.json")),
        },
        proximas=[{"id": t.get("id"), "titulo": str(t.get("titulo", "")), "fecha_limite": t.get("fecha_limite", "")} for t in pendientes[:5]],
        documentos=_archivos(CARPETA_DOCS, EXTENSIONES_DOCS),
        fotos=_archivos(CARPETA_FOTOS, EXTENSIONES_FOTOS) + _archivos(CARPETA_FOTOS / "editadas", EXTENSIONES_FOTOS, True),
        herramientas=[
            {"nombre": n, "titulo": titulo, "categoria": categoria, "descripcion": _descripcion(n)}
            for n, (titulo, categoria) in TITULOS_HERRAMIENTAS.items()
            if nucleo is not None and getattr(nucleo, n, None) is not None
        ],
    )


FAVICON = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="16" fill="#4f46e5"/>'
    '<path d="M32 12l5.5 15.5L53 33l-15.5 5.5L32 54l-5.5-15.5L11 33l15.5-5.5z" fill="#fff"/></svg>'
)


@app.get("/")
def pagina():
    return Response(HTML, mimetype="text/html")


@app.get("/static/estilos.css")
def recurso_estilos():
    return Response(ESTILOS, mimetype="text/css")


@app.get("/static/app.js")
def recurso_script():
    return Response(SCRIPT, mimetype="text/javascript")


@app.get("/favicon.svg")
def recurso_icono():
    return Response(FAVICON, mimetype="image/svg+xml")


# ----------------------------------------------------------------------------
# Interfaz: tres recursos independientes (estructura, estilos y comportamiento)
# ----------------------------------------------------------------------------

HTML = r"""<!doctype html>
<html lang="es" data-tema="auto">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<meta name="theme-color" content="#0a0c11">
<meta name="robots" content="noindex">
<title>Mi agente</title>
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="/static/estilos.css">
<script src="/static/app.js" defer></script>
</head>
<body>
<a class="salto" href="#entrada">Saltar al cuadro de mensaje</a>

<svg class="sprite" aria-hidden="true" focusable="false" width="0" height="0">
  <symbol id="i-spark" viewBox="0 0 24 24"><path d="M12 2.5l2.2 6.3 6.3 2.2-6.3 2.2L12 19.5l-2.2-6.3L3.5 11l6.3-2.2z"/><path d="M19 15.5l.8 2.2 2.2.8-2.2.8L19 21.5l-.8-2.2-2.2-.8 2.2-.8z"/></symbol>
  <symbol id="i-plus" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></symbol>
  <symbol id="i-menu" viewBox="0 0 24 24"><path d="M4 6h16M4 12h16M4 18h16"/></symbol>
  <symbol id="i-x" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></symbol>
  <symbol id="i-send" viewBox="0 0 24 24"><path d="M12 19V5M5 12l7-7 7 7"/></symbol>
  <symbol id="i-stop" viewBox="0 0 24 24"><rect x="5" y="5" width="14" height="14" rx="3"/></symbol>
  <symbol id="i-clip" viewBox="0 0 24 24"><path d="M21.4 11.05l-9.2 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></symbol>
  <symbol id="i-trash" viewBox="0 0 24 24"><path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14M10 10v6M14 10v6"/></symbol>
  <symbol id="i-pencil" viewBox="0 0 24 24"><path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></symbol>
  <symbol id="i-copy" viewBox="0 0 24 24"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1"/></symbol>
  <symbol id="i-check" viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7"/></symbol>
  <symbol id="i-sun" viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></symbol>
  <symbol id="i-moon" viewBox="0 0 24 24"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></symbol>
  <symbol id="i-monitor" viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/></symbol>
  <symbol id="i-logout" viewBox="0 0 24 24"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/></symbol>
  <symbol id="i-refresh" viewBox="0 0 24 24"><path d="M20 11a8 8 0 0 0-14.9-3M4 5v4h4M4 13a8 8 0 0 0 14.9 3M20 19v-4h-4"/></symbol>
  <symbol id="i-doc" viewBox="0 0 24 24"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h6"/></symbol>
  <symbol id="i-image" viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="1.6"/><path d="M21 16l-5-5-8 9"/></symbol>
  <symbol id="i-code" viewBox="0 0 24 24"><path d="M8 8l-4 4 4 4M16 8l4 4-4 4M14 5l-4 14"/></symbol>
  <symbol id="i-tasks" viewBox="0 0 24 24"><path d="M10 6h10M10 12h10M10 18h10M3.5 6.5l1.5 1.5 2.5-3M3.5 12.5l1.5 1.5 2.5-3M3.5 18.5l1.5 1.5 2.5-3"/></symbol>
  <symbol id="i-book" viewBox="0 0 24 24"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5z"/><path d="M4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5"/></symbol>
  <symbol id="i-cards" viewBox="0 0 24 24"><path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/></symbol>
  <symbol id="i-calendar" viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 10h18"/></symbol>
  <symbol id="i-tool" viewBox="0 0 24 24"><path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-.6-.6-2.4z"/></symbol>
  <symbol id="i-down" viewBox="0 0 24 24"><path d="M12 5v14M5 12l7 7 7-7"/></symbol>
  <symbol id="i-alert" viewBox="0 0 24 24"><path d="M12 3l10 18H2z"/><path d="M12 10v5M12 18h.01"/></symbol>
  <symbol id="i-search" viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></symbol>
  <symbol id="i-panel" viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16"/></symbol>
  <symbol id="i-chevrons" viewBox="0 0 24 24"><path d="M11 17l-5-5 5-5M18 17l-5-5 5-5"/></symbol>
  <symbol id="i-retry" viewBox="0 0 24 24"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/></symbol>
</svg>

<noscript><p class="aviso mal">Esta aplicación necesita JavaScript para funcionar.</p></noscript>

<div id="app" class="app">
  <div id="velo" class="velo" hidden></div>

  <!-- ===================== Barra lateral ===================== -->
  <aside id="lado" class="lado" aria-label="Menú lateral">
    <div class="lado-cab">
      <div class="marca">
        <span class="logo" aria-hidden="true"><svg class="ic"><use href="#i-spark"/></svg></span>
        <span class="marca-texto"><strong>Mi agente</strong><small>Organización y estudio</small></span>
      </div>
      <button id="btnColapsar" class="icono" type="button" aria-label="Contraer menú" aria-expanded="true" title="Contraer menú"><svg class="ic"><use href="#i-chevrons"/></svg></button>
      <button id="btnCerrarLado" class="icono cierre-lado solo-movil" type="button" aria-label="Cerrar menú"><svg class="ic"><use href="#i-x"/></svg></button>
    </div>

    <button id="btnNuevo" class="boton primario ancho" type="button" title="Nuevo chat">
      <svg class="ic"><use href="#i-plus"/></svg><span class="etq">Nuevo chat</span>
    </button>

    <div class="buscar">
      <label class="solo-lectores" for="buscar">Buscar conversaciones</label>
      <svg class="ic" aria-hidden="true"><use href="#i-search"/></svg>
      <input id="buscar" type="search" placeholder="Buscar conversaciones" autocomplete="off">
    </div>

    <nav id="lista" class="lista" aria-label="Historial de conversaciones"></nav>

    <div class="lado-pie">
      <button id="btnPanelLado" class="enlace" type="button" aria-controls="panel" title="Herramientas y contexto">
        <svg class="ic"><use href="#i-tool"/></svg><span class="etq">Herramientas y contexto</span>
      </button>
      <button id="btnClave" class="enlace" type="button" title="Configurar o cambiar la clave de Gemini">
        <svg class="ic"><use href="#i-spark"/></svg><span class="etq">Clave de Gemini</span>
      </button>
      <div class="tema" role="group" aria-label="Apariencia">
        <button type="button" data-tema="auto" aria-pressed="true" aria-label="Apariencia automática (según el sistema)" title="Automática"><svg class="ic"><use href="#i-monitor"/></svg><span>Auto</span></button>
        <button type="button" data-tema="claro" aria-pressed="false" aria-label="Apariencia clara" title="Clara"><svg class="ic"><use href="#i-sun"/></svg><span>Claro</span></button>
        <button type="button" data-tema="oscuro" aria-pressed="false" aria-label="Apariencia oscura" title="Oscura"><svg class="ic"><use href="#i-moon"/></svg><span>Oscuro</span></button>
      </div>
      <button id="btnSalir" class="enlace" type="button" title="Cerrar sesión">
        <svg class="ic"><use href="#i-logout"/></svg><span class="etq">Cerrar sesión</span>
      </button>
    </div>
  </aside>

  <!-- ===================== Zona principal ===================== -->
  <main id="principal" class="principal">
    <header class="cab">
      <button id="btnMenu" class="icono solo-movil" type="button" aria-label="Abrir menú" aria-controls="lado" aria-expanded="false"><svg class="ic"><use href="#i-menu"/></svg></button>
      <h1 id="titulo">Nuevo chat</h1>
      <div id="pill" class="pill" data-tipo="listo" role="status" aria-live="polite"><span class="punto" aria-hidden="true"></span><span id="pillTexto">Conectando…</span></div>
      <button id="btnPanel" class="icono" type="button" aria-label="Herramientas y contexto" aria-controls="panel" aria-expanded="false" title="Herramientas y contexto"><svg class="ic"><use href="#i-panel"/></svg></button>
    </header>

    <section id="conversacion" class="conversacion" aria-label="Conversación" tabindex="-1">
      <div class="carril">
        <div id="bienvenida" class="bienvenida" hidden>
          <span class="logo grande" aria-hidden="true"><svg class="ic"><use href="#i-spark"/></svg></span>
          <h2>Hola, soy tu agente personal</h2>
          <p>Te ayudo a organizar tu día, estudiar, entender documentos, revisar código y editar fotos. Elige una sugerencia o escríbeme lo que necesites.</p>
          <div id="sugerencias" class="sugerencias"></div>
        </div>
        <div id="mensajes" role="log" aria-live="polite" aria-relevant="additions" aria-label="Mensajes"></div>
      </div>
    </section>
    <button id="btnFinal" class="flotante" type="button" aria-label="Ir al último mensaje" hidden><svg class="ic"><use href="#i-down"/></svg></button>

    <footer class="compositor">
      <div id="subida" class="subida" role="status" hidden>
        <span id="subidaTexto">Subiendo…</span>
        <div class="barra" aria-hidden="true"><i id="subidaBarra"></i></div>
      </div>
      <form id="formulario" class="entrada-caja" autocomplete="off">
        <button id="btnAdjuntar" class="icono" type="button" aria-label="Adjuntar documentos o fotos" title="Adjuntar documentos o fotos"><svg class="ic"><use href="#i-clip"/></svg></button>
        <label class="solo-lectores" for="entrada">Mensaje para el agente</label>
        <textarea id="entrada" rows="1" maxlength="8000" placeholder="Escribe un mensaje…" enterkeyhint="send"></textarea>
        <span id="contador" class="contador" hidden></span>
        <button id="btnDetener" class="boton-redondo detener" type="button" aria-label="Detener la respuesta" title="Detener la respuesta" hidden><svg class="ic"><use href="#i-stop"/></svg></button>
        <button id="btnEnviar" class="boton-redondo enviar" type="submit" aria-label="Enviar mensaje" title="Enviar" disabled><svg class="ic"><use href="#i-send"/></svg></button>
      </form>
      <p class="nota"><span class="solo-puntero">Enter envía · Mayús+Enter hace un salto de línea · </span>El agente puede equivocarse: revisa lo importante.</p>
      <input id="archivo" type="file" multiple hidden tabindex="-1" aria-label="Elegir documentos o fotos">
    </footer>
  </main>

  <!-- ===================== Panel de herramientas y contexto ===================== -->
  <aside id="panel" class="panel" aria-label="Herramientas y contexto">
    <div class="panel-cab">
      <h2>Herramientas y contexto</h2>
      <button id="btnPanelRefrescar" class="icono" type="button" aria-label="Actualizar" title="Actualizar"><svg class="ic"><use href="#i-refresh"/></svg></button>
      <button id="btnPanelCerrar" class="icono" type="button" aria-label="Cerrar panel"><svg class="ic"><use href="#i-x"/></svg></button>
    </div>
    <div class="pestanas" role="tablist" aria-label="Secciones del panel">
      <button id="tabContexto" type="button" role="tab" aria-selected="true" aria-controls="cuerpoPanel" data-pestana="contexto">Contexto</button>
      <button id="tabHerramientas" type="button" role="tab" aria-selected="false" aria-controls="cuerpoPanel" data-pestana="herramientas" tabindex="-1">Herramientas</button>
    </div>
    <div id="cuerpoPanel" class="panel-cuerpo" role="tabpanel" aria-live="polite"></div>
  </aside>
</div>

<div id="soltar" class="soltar" hidden>Suelta los archivos para subirlos</div>
<div id="avisos" class="avisos" role="status" aria-live="polite"></div>

<!-- ===================== Diálogos ===================== -->
<dialog id="dlgConfirmar" class="ancho" aria-labelledby="dlgConfirmarTitulo">
  <form method="dialog" class="dlg-cuerpo">
    <h2 id="dlgConfirmarTitulo">Revisa esto antes de aceptar</h2>
    <p class="suave">El agente quiere hacer un cambio. No se aplicará nada hasta que lo aceptes. En verde, lo que se añade; en rojo, lo que se quita.</p>
    <div id="dlgConfirmarTexto" class="diff" tabindex="0" role="region" aria-label="Cambios propuestos"></div>
    <div class="dlg-pie">
      <button class="boton" value="no" autofocus>No, cancelar</button>
      <button class="boton primario" value="si">Sí, aplicar</button>
    </div>
  </form>
</dialog>

<dialog id="dlgTexto" aria-labelledby="dlgTextoTitulo">
  <form id="formTexto" method="dialog" class="dlg-cuerpo">
    <h2 id="dlgTextoTitulo">Renombrar conversación</h2>
    <label class="solo-lectores" for="dlgTextoCampo">Nuevo nombre</label>
    <input id="dlgTextoCampo" type="text" maxlength="60" autocomplete="off">
    <div class="dlg-pie">
      <button class="boton" value="no" formnovalidate>Cancelar</button>
      <button class="boton primario" value="si">Guardar</button>
    </div>
  </form>
</dialog>

<dialog id="dlgBorrar" aria-labelledby="dlgBorrarTitulo">
  <form method="dialog" class="dlg-cuerpo">
    <h2 id="dlgBorrarTitulo">Eliminar conversación</h2>
    <p id="dlgBorrarTexto" class="suave"></p>
    <div class="dlg-pie">
      <button class="boton" value="no" autofocus>Cancelar</button>
      <button class="boton peligro" value="si">Sí, eliminar</button>
    </div>
  </form>
</dialog>

<dialog id="dlgLogin" aria-labelledby="dlgLoginTitulo">
  <form id="formLogin" class="dlg-cuerpo">
    <span class="logo" aria-hidden="true"><svg class="ic"><use href="#i-spark"/></svg></span>
    <h2 id="dlgLoginTitulo">Introduce tu PIN</h2>
    <p class="suave">Es el que aparece en la ventana del ordenador donde está abierto el agente.</p>
    <label class="solo-lectores" for="pin">PIN de acceso</label>
    <input id="pin" type="password" inputmode="numeric" autocomplete="current-password" placeholder="PIN">
    <div id="loginError" class="dlg-error" role="alert"></div>
    <div class="dlg-pie"><button id="btnLogin" class="boton primario" type="submit">Entrar</button></div>
  </form>
</dialog>

<dialog id="dlgClave" aria-labelledby="dlgClaveTitulo">
  <form id="formClave" class="dlg-cuerpo">
    <span class="logo" aria-hidden="true"><svg class="ic"><use href="#i-spark"/></svg></span>
    <h2 id="dlgClaveTitulo">Configura tu clave de Gemini</h2>
    <p class="suave">Crea una clave personal gratuita en <a href="https://aistudio.google.com/app/apikey" target="_blank" rel="noopener noreferrer">Google AI Studio</a> y pégala aquí. Solo se guarda en este ordenador.</p>
    <label for="claveApi">Clave de API de Google</label>
    <input id="claveApi" type="password" maxlength="2048" autocomplete="new-password" spellcheck="false" required>
    <p class="suave">Se enviará una prueba breve a Gemini para comprobarla. No se guardará si Google la rechaza.</p>
    <div id="claveError" class="dlg-error" role="alert"></div>
    <div class="dlg-pie">
      <button id="btnClaveCancelar" class="boton" type="button">Ahora no</button>
      <button id="btnGuardarClave" class="boton primario" type="submit">Comprobar y guardar</button>
    </div>
  </form>
</dialog>
</body>
</html>
"""

ESTILOS = r"""/* ==========================================================================
   Mi agente · estilos
   1 Tokens · 2 Base · 3 Layout · 4 Barra lateral · 5 Conversación · 6 Mensajes
   7 Compositor · 8 Panel · 9 Diálogos y avisos · 10 Utilidades y responsive
   ========================================================================== */

/* ---------- 1. Tokens (tema claro por defecto) ---------- */
:root {
  color-scheme: light;
  --fuente: Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  --mono: ui-monospace, "SF Mono", SFMono-Regular, Consolas, "Liberation Mono", monospace;

  --bg: #f5f6fa;
  --sup: #ffffff;
  --sup2: #eef0f6;
  --sup3: #e3e6f0;
  --borde: #dfe2ec;
  --borde-fuerte: #c6cbdb;
  --texto: #141824;
  --suave: #566077;

  --acento: #4f46e5;
  --acento-hover: #4338ca;
  --acento-txt: #ffffff;
  --acento-link: #4338ca;
  --acento-fondo: #ecebfd;
  --halo: rgba(79, 70, 229, .28);

  --burbuja: #4f46e5;
  --burbuja-txt: #ffffff;

  --ok: #047857;
  --aviso: #b45309;
  --peligro: #b91c1c;
  --peligro-fondo: #fdecec;
  --codigo-bg: #0f1320;
  --codigo-txt: #e6e9f5;

  --sombra: 0 1px 2px rgba(20, 24, 36, .06), 0 10px 30px rgba(20, 24, 36, .08);
  --sombra-peq: 0 1px 2px rgba(20, 24, 36, .08);
  --r: 16px;
  --r-sm: 10px;
  --lado: 288px;
  --lado-col: 68px;
  --panel: 348px;
  --t: .18s;
}

@media (prefers-color-scheme: dark) {
  :root[data-tema="auto"] {
    color-scheme: dark;
    --bg: #0a0c11; --sup: #11141b; --sup2: #171b24; --sup3: #1f2432;
    --borde: #242a38; --borde-fuerte: #343c50;
    --texto: #e9ecf4; --suave: #9aa3b8;
    --acento: #5b63f2; --acento-hover: #7078ff; --acento-txt: #ffffff; --acento-link: #a9afff;
    --acento-fondo: #1c2040; --halo: rgba(112, 120, 255, .35);
    --burbuja: #2a2f6b; --burbuja-txt: #ffffff;
    --ok: #34d399; --aviso: #fbbf24; --peligro: #f87171; --peligro-fondo: #2a1418;
    --codigo-bg: #070910; --codigo-txt: #e6e9f5;
    --sombra: 0 1px 2px rgba(0, 0, 0, .4), 0 12px 34px rgba(0, 0, 0, .35);
    --sombra-peq: 0 1px 2px rgba(0, 0, 0, .4);
  }
}
:root[data-tema="oscuro"] {
  color-scheme: dark;
  --bg: #0a0c11; --sup: #11141b; --sup2: #171b24; --sup3: #1f2432;
  --borde: #242a38; --borde-fuerte: #343c50;
  --texto: #e9ecf4; --suave: #9aa3b8;
  --acento: #5b63f2; --acento-hover: #7078ff; --acento-txt: #ffffff; --acento-link: #a9afff;
  --acento-fondo: #1c2040; --halo: rgba(112, 120, 255, .35);
  --burbuja: #2a2f6b; --burbuja-txt: #ffffff;
  --ok: #34d399; --aviso: #fbbf24; --peligro: #f87171; --peligro-fondo: #2a1418;
  --codigo-bg: #070910; --codigo-txt: #e6e9f5;
  --sombra: 0 1px 2px rgba(0, 0, 0, .4), 0 12px 34px rgba(0, 0, 0, .35);
  --sombra-peq: 0 1px 2px rgba(0, 0, 0, .4);
}

/* ---------- 2. Base ---------- */
*, *::before, *::after { box-sizing: border-box; }
html, body { height: 100%; margin: 0; }
body {
  background: var(--bg); color: var(--texto);
  font-family: var(--fuente); font-size: 16px; line-height: 1.5;
  -webkit-font-smoothing: antialiased; text-rendering: optimizeLegibility;
  overflow: hidden;
}
button, input, textarea { font: inherit; color: inherit; }
button { cursor: pointer; }
button:disabled { cursor: not-allowed; }
h1, h2, h3, h4, h5, h6, p { margin: 0; }
[hidden] { display: none !important; }
:focus-visible { outline: 2px solid var(--acento-link); outline-offset: 2px; border-radius: 6px; }
::selection { background: var(--halo); }

.ic { width: 20px; height: 20px; flex: none; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
.sprite { position: absolute; width: 0; height: 0; overflow: hidden; }
.solo-lectores { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
.salto { position: absolute; left: 12px; top: -60px; z-index: 100; background: var(--acento); color: var(--acento-txt); padding: 10px 14px; border-radius: var(--r-sm); text-decoration: none; transition: top var(--t); }
.salto:focus { top: 12px; }
.suave { color: var(--suave); }

/* Botones */
.icono {
  display: inline-grid; place-items: center; width: 40px; height: 40px; flex: none;
  background: transparent; border: 1px solid transparent; border-radius: var(--r-sm); color: var(--suave);
  transition: background var(--t), color var(--t), border-color var(--t);
}
.icono:hover { background: var(--sup2); color: var(--texto); }
.icono:active { background: var(--sup3); }
.icono:disabled { opacity: .45; background: transparent; color: var(--suave); }
.boton {
  display: inline-flex; align-items: center; justify-content: center; gap: 8px; min-height: 42px; padding: 0 16px;
  border-radius: var(--r-sm); border: 1px solid var(--borde-fuerte); background: var(--sup); color: var(--texto); font-weight: 600;
  transition: background var(--t), border-color var(--t), transform var(--t), box-shadow var(--t);
}
.boton:hover { background: var(--sup2); }
.boton:active { transform: translateY(1px); }
.boton:disabled { opacity: .5; transform: none; }
.boton.primario { background: var(--acento); border-color: var(--acento); color: var(--acento-txt); box-shadow: var(--sombra-peq); }
.boton.primario:hover { background: var(--acento-hover); border-color: var(--acento-hover); }
.boton.peligro { background: var(--peligro); border-color: var(--peligro); color: #fff; }
.boton.peligro:hover { filter: brightness(1.08); }
.boton.ancho { width: 100%; }
.boton.pequeno { min-height: 32px; padding: 0 12px; font-size: 14px; }
.enlace {
  display: flex; align-items: center; gap: 10px; width: 100%; min-height: 40px; padding: 0 12px; background: transparent; border: 0;
  border-radius: var(--r-sm); color: var(--suave); text-align: left; transition: background var(--t), color var(--t);
}
.enlace:hover { background: var(--sup2); color: var(--texto); }
.logo { display: inline-grid; place-items: center; width: 36px; height: 36px; flex: none; border-radius: 11px; background: var(--acento); color: var(--acento-txt); box-shadow: var(--sombra-peq); }
.logo .ic { width: 20px; height: 20px; fill: currentColor; stroke: none; }
.logo.grande { width: 60px; height: 60px; border-radius: 18px; }
.logo.grande .ic { width: 32px; height: 32px; }

/* ---------- 3. Layout ---------- */
.app { display: grid; grid-template-columns: var(--lado) minmax(0, 1fr); grid-template-rows: minmax(0, 1fr); height: 100dvh; overflow: hidden; transition: grid-template-columns .22s ease; }
.app.colapsado { grid-template-columns: var(--lado-col) minmax(0, 1fr); }
.principal { position: relative; display: flex; flex-direction: column; min-width: 0; min-height: 0; height: 100dvh; background: var(--bg); }
.velo { position: fixed; inset: 0; background: rgba(5, 7, 12, .55); z-index: 30; }

/* ---------- 4. Barra lateral ---------- */
.lado {
  display: flex; flex-direction: column; gap: 12px; min-height: 0; background: var(--sup); border-right: 1px solid var(--borde);
  padding: 14px 12px; padding-top: max(14px, env(safe-area-inset-top)); padding-bottom: max(14px, env(safe-area-inset-bottom)); z-index: 35;
}
.lado-cab { display: flex; align-items: center; gap: 8px; min-height: 40px; }
.marca { display: flex; align-items: center; gap: 10px; flex: 1; min-width: 0; }
.marca-texto { display: flex; flex-direction: column; min-width: 0; line-height: 1.2; }
.marca-texto strong { font-size: 17px; letter-spacing: -.01em; }
.marca-texto small { color: var(--suave); font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.buscar { position: relative; }
.buscar .ic { position: absolute; left: 12px; top: 50%; transform: translateY(-50%); width: 18px; height: 18px; color: var(--suave); pointer-events: none; }
.buscar input {
  width: 100%; min-height: 40px; padding: 0 12px 0 38px; background: var(--sup2); border: 1px solid transparent; border-radius: var(--r-sm);
  transition: border-color var(--t), background var(--t);
}
.buscar input::placeholder { color: var(--suave); }
.buscar input:focus-visible { outline: none; border-color: var(--acento-link); background: var(--sup); box-shadow: 0 0 0 3px var(--halo); }
.lista { flex: 1; min-height: 0; overflow-y: auto; margin: 0 -4px; padding: 0 4px; scrollbar-width: thin; scrollbar-color: var(--borde-fuerte) transparent; }
.grupo { padding: 14px 10px 6px; font-size: 12px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; color: var(--suave); }
.chat-item { position: relative; display: flex; align-items: center; border-radius: var(--r-sm); transition: background var(--t); }
.chat-item:hover, .chat-item:focus-within { background: var(--sup2); }
.chat-item.activo { background: var(--acento-fondo); }
.chat-titulo { flex: 1; min-width: 0; min-height: 40px; padding: 0 12px; background: none; border: 0; text-align: left; color: var(--texto); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; border-radius: var(--r-sm); }
.chat-item.activo .chat-titulo { font-weight: 600; color: var(--acento-link); }
.chat-acciones {
  position: absolute; top: 0; right: 0; bottom: 0; display: flex; align-items: center; padding: 0 4px 0 22px;
  border-radius: 0 var(--r-sm) var(--r-sm) 0; background: linear-gradient(to right, transparent, var(--sup2) 40%);
  opacity: 0; pointer-events: none; transition: opacity var(--t);
}
.chat-item.activo .chat-acciones { background: linear-gradient(to right, transparent, var(--acento-fondo) 40%); }
.chat-item:hover .chat-acciones, .chat-item:focus-within .chat-acciones { opacity: 1; pointer-events: auto; }
.chat-acciones .icono { width: 32px; height: 32px; }
.chat-acciones .ic { width: 16px; height: 16px; }
.vacio { padding: 24px 12px; text-align: center; color: var(--suave); font-size: 14px; }
.lado-pie { display: flex; flex-direction: column; gap: 4px; padding-top: 10px; border-top: 1px solid var(--borde); }
.tema { display: flex; gap: 4px; padding: 4px; background: var(--sup2); border-radius: var(--r-sm); }
.tema button { flex: 1; display: inline-flex; align-items: center; justify-content: center; gap: 6px; min-height: 34px; background: transparent; border: 0; border-radius: 8px; color: var(--suave); font-size: 13px; transition: background var(--t), color var(--t); }
.tema button:hover { color: var(--texto); }
.tema button[aria-pressed="true"] { background: var(--sup); color: var(--texto); box-shadow: var(--sombra-peq); font-weight: 600; }
.tema .ic { width: 16px; height: 16px; }
.cierre-lado { display: none; }

/* Barra lateral contraída (solo escritorio) */
.app.colapsado .lado { padding-left: 14px; padding-right: 14px; align-items: center; }
.app.colapsado .lado-cab { flex-direction: column; }
.app.colapsado .marca-texto, .app.colapsado .etq, .app.colapsado .buscar, .app.colapsado .lista, .app.colapsado .tema { display: none; }
.app.colapsado .marca { flex: none; }
.app.colapsado .boton.ancho { width: 40px; padding: 0; }
.app.colapsado .enlace { width: 40px; padding: 0; justify-content: center; }
.app.colapsado .lado-pie { align-items: center; margin-top: auto; }
.app.colapsado #btnColapsar .ic { transform: rotate(180deg); }

/* ---------- 5. Cabecera y conversación ---------- */
.cab {
  display: flex; align-items: center; gap: 10px; min-height: 60px; padding: 8px 16px; padding-top: max(8px, env(safe-area-inset-top));
  border-bottom: 1px solid var(--borde); background: color-mix(in srgb, var(--bg) 88%, transparent); backdrop-filter: blur(10px);
}
.cab h1 { flex: 1; min-width: 0; font-size: 17px; font-weight: 650; letter-spacing: -.01em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pill { display: inline-flex; align-items: center; gap: 8px; max-width: 46vw; padding: 5px 12px; border: 1px solid var(--borde); border-radius: 999px; background: var(--sup); font-size: 13px; color: var(--suave); }
.pill span:last-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.punto { width: 8px; height: 8px; flex: none; border-radius: 50%; background: var(--ok); }
.pill[data-tipo="trabajando"] .punto { background: var(--aviso); animation: pulso 1.2s ease-in-out infinite; }
.pill[data-tipo="error"] .punto, .pill[data-tipo="offline"] .punto { background: var(--peligro); }
@keyframes pulso { 0%, 100% { opacity: 1; } 50% { opacity: .35; } }

.conversacion { position: relative; flex: 1; min-height: 0; overflow-y: auto; scroll-behavior: smooth; overscroll-behavior: contain; scrollbar-width: thin; scrollbar-color: var(--borde-fuerte) transparent; }
.conversacion:focus { outline: none; }
.carril { width: min(100%, 840px); margin: 0 auto; padding: 24px 20px 12px; }
.flotante {
  position: absolute; right: 20px; bottom: 150px; z-index: 5; display: inline-grid; place-items: center; width: 42px; height: 42px;
  border-radius: 50%; border: 1px solid var(--borde-fuerte); background: var(--sup); color: var(--texto); box-shadow: var(--sombra);
  transition: transform var(--t), background var(--t);
}
.flotante:hover { background: var(--sup2); transform: translateY(-2px); }

.bienvenida { display: flex; flex-direction: column; align-items: center; text-align: center; gap: 14px; padding: clamp(16px, 7vh, 64px) 0 12px; animation: aparece .4s ease both; }
.bienvenida h2 { font-size: clamp(24px, 4vw, 32px); letter-spacing: -.02em; line-height: 1.15; }
.bienvenida p { max-width: 560px; color: var(--suave); }
.sugerencias { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 12px; width: 100%; margin-top: 14px; text-align: left; }
.sugerencia {
  display: flex; gap: 12px; align-items: flex-start; padding: 14px; background: var(--sup); border: 1px solid var(--borde); border-radius: var(--r);
  text-align: left; transition: border-color var(--t), transform var(--t), box-shadow var(--t), background var(--t);
}
.sugerencia:hover { border-color: var(--acento-link); transform: translateY(-2px); box-shadow: var(--sombra); }
.sugerencia:active { transform: translateY(0); }
.sugerencia .ic-caja { display: inline-grid; place-items: center; width: 38px; height: 38px; flex: none; border-radius: 11px; background: var(--acento-fondo); color: var(--acento-link); }
.sugerencia strong { display: block; font-size: 15px; }
.sugerencia span.desc { display: block; font-size: 13px; color: var(--suave); line-height: 1.35; }
@keyframes aparece { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }

/* ---------- 6. Mensajes ---------- */
.msg { display: flex; gap: 12px; margin: 22px 0; animation: aparece .25s ease both; }
.msg.usuario { justify-content: flex-end; }
.msg.usuario .cuerpo {
  max-width: min(85%, 640px); padding: 10px 16px; background: var(--burbuja); color: var(--burbuja-txt); border-radius: 20px 20px 6px 20px;
  white-space: pre-wrap; overflow-wrap: anywhere; box-shadow: var(--sombra-peq);
}
.msg.agente .avatar { margin-top: 2px; width: 32px; height: 32px; border-radius: 10px; }
.msg.agente .avatar .ic { width: 17px; height: 17px; }
.msg.agente .contenido { flex: 1; min-width: 0; }
.acciones { display: flex; gap: 4px; margin-top: 6px; margin-left: -8px; }
.acciones .icono { width: 34px; height: 34px; }
.acciones .ic { width: 17px; height: 17px; }

.msg.error .tarjeta-error {
  flex: 1; min-width: 0; padding: 14px 16px; background: var(--peligro-fondo); border: 1px solid color-mix(in srgb, var(--peligro) 45%, transparent);
  border-radius: var(--r); color: var(--texto);
}
.msg.error .cab-error { display: flex; align-items: center; gap: 8px; font-weight: 650; color: var(--peligro); margin-bottom: 4px; }
.msg.error.detenido .tarjeta-error { background: var(--sup2); border-color: var(--borde); }
.msg.error.detenido .cab-error { color: var(--suave); }
.tarjeta-error p { white-space: pre-wrap; overflow-wrap: anywhere; }
.tarjeta-error details { margin-top: 8px; font-size: 13px; color: var(--suave); }
.tarjeta-error summary { cursor: pointer; }
.tarjeta-error pre { margin: 6px 0 0; padding: 10px; background: var(--sup); border-radius: var(--r-sm); white-space: pre-wrap; overflow-wrap: anywhere; font-family: var(--mono); font-size: 12px; }
.tarjeta-error .boton { margin-top: 12px; }

/* Texto con formato (respuestas del agente) */
.prosa { overflow-wrap: anywhere; }
.prosa > * + * { margin-top: .75em; }
.prosa h3, .prosa h4, .prosa h5, .prosa h6 { margin-top: 1.1em; font-weight: 650; letter-spacing: -.01em; line-height: 1.3; }
.prosa h3 { font-size: 1.25em; } .prosa h4 { font-size: 1.12em; } .prosa h5, .prosa h6 { font-size: 1em; }
.prosa ul, .prosa ol { padding-left: 1.4em; }
.prosa li + li { margin-top: .3em; }
.prosa li::marker { color: var(--suave); }
.prosa blockquote { margin-left: 0; padding: 2px 0 2px 14px; border-left: 3px solid var(--acento); color: var(--suave); }
.prosa hr { border: 0; border-top: 1px solid var(--borde); margin: 1.2em 0; }
.prosa a { color: var(--acento-link); text-underline-offset: 3px; }
.prosa code { padding: 2px 6px; border-radius: 6px; background: var(--sup3); font-family: var(--mono); font-size: .88em; }
.codigo { overflow: hidden; border-radius: var(--r-sm); background: var(--codigo-bg); border: 1px solid var(--borde); }
.codigo-cab { display: flex; align-items: center; justify-content: space-between; padding: 4px 6px 4px 14px; background: rgba(255, 255, 255, .05); color: #aab2c8; font-size: 12px; }
.codigo-cab .boton { min-height: 28px; padding: 0 10px; background: transparent; border-color: transparent; color: #aab2c8; font-weight: 500; font-size: 12px; }
.codigo-cab .boton:hover { background: rgba(255, 255, 255, .08); color: #fff; }
.codigo pre { margin: 0; padding: 14px; overflow-x: auto; color: var(--codigo-txt); font-family: var(--mono); font-size: 13.5px; line-height: 1.55; }
.codigo pre code { padding: 0; background: none; font-size: inherit; }
.tabla-scroll { overflow-x: auto; border: 1px solid var(--borde); border-radius: var(--r-sm); }
.prosa table { width: 100%; border-collapse: collapse; font-size: .94em; }
.prosa th, .prosa td { padding: 9px 14px; border-bottom: 1px solid var(--borde); }
.prosa th { background: var(--sup2); font-weight: 650; white-space: nowrap; }
.prosa tr:last-child td { border-bottom: 0; }
.foto { margin: 0; }
.foto img { display: block; max-width: min(100%, 520px); max-height: 60dvh; border-radius: var(--r-sm); border: 1px solid var(--borde); background: var(--sup2); }
.foto figcaption { display: flex; gap: 14px; margin-top: 6px; font-size: 13px; color: var(--suave); }
.foto a { color: var(--acento-link); }

/* Indicador de procesamiento */
.pensando { display: flex; gap: 12px; margin: 22px 0; animation: aparece .25s ease both; }
.pensando .tarjeta { flex: 1; max-width: 560px; padding: 14px 16px; background: var(--sup); border: 1px solid var(--borde); border-radius: var(--r); box-shadow: var(--sombra-peq); }
.pensando .fila { display: flex; align-items: center; gap: 12px; }
.pensando .fila > span { flex: 1; min-width: 0; font-weight: 550; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.progreso { position: relative; height: 4px; margin-top: 12px; overflow: hidden; border-radius: 4px; background: var(--sup3); }
.progreso::after { content: ""; position: absolute; inset: 0 auto 0 0; width: 35%; border-radius: 4px; background: var(--acento); animation: barrido 1.3s ease-in-out infinite; }
@keyframes barrido { 0% { transform: translateX(-100%); } 100% { transform: translateX(300%); } }
.pasos { display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0 0; padding: 0; list-style: none; }
.pasos li { display: inline-flex; align-items: center; gap: 6px; padding: 3px 10px; border-radius: 999px; background: var(--acento-fondo); color: var(--acento-link); font-size: 12.5px; }
.pasos .ic { width: 13px; height: 13px; stroke-width: 2.4; }
.esqueleto { height: 14px; margin: 14px 0; border-radius: 7px; background: linear-gradient(90deg, var(--sup2), var(--sup3), var(--sup2)); background-size: 200% 100%; animation: brillo 1.4s linear infinite; }
.esqueleto.corto { width: 55%; }
@keyframes brillo { to { background-position: -200% 0; } }

/* ---------- 7. Compositor ---------- */
.compositor { padding: 6px 16px; padding-bottom: max(10px, env(safe-area-inset-bottom)); background: linear-gradient(to top, var(--bg) 70%, transparent); }
.compositor > * { width: min(100%, 808px); margin-left: auto; margin-right: auto; }
.entrada-caja {
  display: flex; align-items: flex-end; gap: 6px; padding: 8px; background: var(--sup); border: 1px solid var(--borde-fuerte);
  border-radius: 22px; box-shadow: var(--sombra); transition: border-color var(--t), box-shadow var(--t);
}
.entrada-caja:focus-within { border-color: var(--acento-link); box-shadow: 0 0 0 3px var(--halo), var(--sombra); }
.entrada-caja textarea {
  flex: 1; min-width: 0; max-height: 200px; min-height: 40px; padding: 9px 6px; resize: none; background: transparent; border: 0; outline: none;
  font-size: 16px; line-height: 1.45; overflow-y: auto; scrollbar-width: thin;
}
.entrada-caja textarea::placeholder { color: var(--suave); }
.contador { align-self: center; font-size: 12px; color: var(--suave); }
.contador.alerta { color: var(--peligro); font-weight: 600; }
.boton-redondo { display: inline-grid; place-items: center; width: 40px; height: 40px; flex: none; border-radius: 50%; border: 0; transition: background var(--t), transform var(--t), opacity var(--t); }
.boton-redondo.enviar { background: var(--acento); color: var(--acento-txt); }
.boton-redondo.enviar:hover:not(:disabled) { background: var(--acento-hover); transform: scale(1.05); }
.boton-redondo.enviar:disabled { background: var(--sup3); color: var(--suave); }
.boton-redondo.detener { background: var(--texto); color: var(--bg); }
.boton-redondo.detener .ic { fill: currentColor; width: 16px; height: 16px; }
.boton-redondo.detener:hover { opacity: .85; }
.nota { margin-top: 8px; text-align: center; font-size: 12px; color: var(--suave); }
.subida { margin-bottom: 8px; padding: 10px 14px; background: var(--sup); border: 1px solid var(--borde); border-radius: var(--r-sm); font-size: 14px; }
.barra { height: 4px; margin-top: 8px; overflow: hidden; border-radius: 4px; background: var(--sup3); }
.barra i { display: block; height: 100%; width: calc(var(--p, 0) * 100%); background: var(--acento); border-radius: 4px; transition: width .15s linear; }
.soltar { position: fixed; inset: 12px; z-index: 60; display: grid; place-items: center; border: 2px dashed var(--acento-link); border-radius: 24px; background: color-mix(in srgb, var(--bg) 88%, transparent); font-size: 20px; font-weight: 650; pointer-events: none; }

/* ---------- 8. Panel de herramientas y contexto ---------- */
.panel {
  position: fixed; top: 0; right: 0; bottom: 0; z-index: 40; display: flex; flex-direction: column; width: min(var(--panel), 100%);
  background: var(--sup); border-left: 1px solid var(--borde); box-shadow: var(--sombra);
  transform: translateX(104%); visibility: hidden; transition: transform .22s ease, visibility 0s .22s;
}
.app.con-panel .panel { transform: none; visibility: visible; transition: transform .22s ease, visibility 0s; }
.panel-cab { display: flex; align-items: center; gap: 8px; padding: 12px 14px; padding-top: max(12px, env(safe-area-inset-top)); border-bottom: 1px solid var(--borde); }
.panel-cab h2 { flex: 1; min-width: 0; font-size: 16px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.pestanas { display: flex; gap: 4px; padding: 8px 14px 0; border-bottom: 1px solid var(--borde); }
.pestanas button { padding: 10px 14px; background: none; border: 0; border-bottom: 2px solid transparent; color: var(--suave); font-weight: 600; transition: color var(--t), border-color var(--t); }
.pestanas button:hover { color: var(--texto); }
.pestanas button[aria-selected="true"] { color: var(--acento-link); border-bottom-color: var(--acento-link); }
.panel-cuerpo { flex: 1; min-height: 0; overflow-y: auto; padding: 14px; padding-bottom: max(14px, env(safe-area-inset-bottom)); }
.panel-cuerpo h3 { margin: 18px 0 8px; font-size: 12px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; color: var(--suave); }
.panel-cuerpo h3:first-child { margin-top: 0; }
.cifras { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }
.cifra { display: flex; flex-direction: column; gap: 2px; padding: 12px; background: var(--sup2); border: 1px solid transparent; border-radius: var(--r-sm); text-align: left; transition: border-color var(--t), background var(--t); }
.cifra:hover { border-color: var(--acento-link); }
.cifra b { font-size: 24px; line-height: 1.1; letter-spacing: -.02em; }
.cifra span { font-size: 13px; color: var(--suave); }
.elementos { display: flex; flex-direction: column; gap: 2px; margin: 0; padding: 0; list-style: none; }
.elemento { display: flex; align-items: center; gap: 10px; width: 100%; min-height: 40px; padding: 4px 10px; background: transparent; border: 0; border-radius: var(--r-sm); text-align: left; transition: background var(--t); }
.elemento:hover { background: var(--sup2); }
.elemento .ic { color: var(--suave); width: 18px; height: 18px; }
.elemento .nom { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.elemento small { color: var(--suave); white-space: nowrap; }
.herramienta { padding: 10px 12px; border: 1px solid var(--borde); border-radius: var(--r-sm); }
.herramienta + .herramienta { margin-top: 8px; }
.herramienta strong { display: flex; align-items: center; gap: 8px; font-size: 14.5px; }
.herramienta strong::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: var(--ok); }
.herramienta p { margin-top: 3px; font-size: 13px; line-height: 1.4; color: var(--suave); }

/* ---------- 9. Diálogos y avisos ---------- */
dialog { padding: 0; border: 1px solid var(--borde); border-radius: 20px; background: var(--sup); color: var(--texto); box-shadow: var(--sombra); width: min(440px, calc(100% - 28px)); }
dialog.ancho { width: min(720px, calc(100% - 28px)); }
dialog::backdrop { background: rgba(5, 7, 12, .6); backdrop-filter: blur(3px); }
dialog[open] { animation: aparece .2s ease both; }
.dlg-cuerpo { display: flex; flex-direction: column; gap: 14px; padding: 22px; }
.dlg-cuerpo h2 { font-size: 19px; letter-spacing: -.01em; }
.dlg-cuerpo input[type="text"], .dlg-cuerpo input[type="password"] { width: 100%; min-height: 46px; padding: 0 14px; background: var(--sup2); border: 1px solid var(--borde-fuerte); border-radius: var(--r-sm); font-size: 16px; }
.dlg-cuerpo input:focus-visible { outline: none; border-color: var(--acento-link); box-shadow: 0 0 0 3px var(--halo); }
.dlg-pie { display: flex; justify-content: flex-end; gap: 10px; flex-wrap: wrap; }
.dlg-error { min-height: 1.3em; color: var(--peligro); font-size: 14px; }
.diff { max-height: 48dvh; overflow: auto; padding: 12px; background: var(--codigo-bg); color: var(--codigo-txt); border-radius: var(--r-sm); font-family: var(--mono); font-size: 13px; line-height: 1.5; }
.diff div { white-space: pre-wrap; overflow-wrap: anywhere; min-height: 1.5em; }
.diff .mas { color: #4ade80; background: rgba(74, 222, 128, .1); }
.diff .menos { color: #f87171; background: rgba(248, 113, 113, .1); }
.avisos { position: fixed; left: 50%; top: 72px; z-index: 80; display: flex; flex-direction: column; align-items: center; gap: 8px; width: min(92%, 420px); transform: translateX(-50%); pointer-events: none; }
.aviso { padding: 10px 16px; background: var(--texto); color: var(--bg); border-radius: 12px; box-shadow: var(--sombra); font-size: 14px; animation: aparece .2s ease both; }
.aviso.mal { background: var(--peligro); color: #fff; }

/* ---------- 10. Responsive y preferencias ---------- */
@media (max-width: 899px) {
  .app, .app.colapsado { grid-template-columns: minmax(0, 1fr); }
  .lado {
    position: fixed; inset: 0 auto 0 0; width: min(86vw, 330px); box-shadow: var(--sombra);
    transform: translateX(-104%); visibility: hidden; transition: transform .22s ease, visibility 0s .22s;
  }
  .app.con-lado .lado { transform: none; visibility: visible; transition: transform .22s ease, visibility 0s; }
  .app.colapsado .marca-texto, .app.colapsado .buscar, .app.colapsado .lista, .app.colapsado .tema { display: revert; }
  .app.colapsado .lado, .app.colapsado .lado-cab { align-items: stretch; flex-direction: row; }
  .app.colapsado .lado { flex-direction: column; }
  .app.colapsado .boton.ancho, .app.colapsado .enlace { width: 100%; padding: 0 12px; justify-content: flex-start; }
  .app.colapsado .boton.ancho { justify-content: center; }
  #btnColapsar { display: none; }
  .cierre-lado { display: inline-grid; }
  .chat-acciones { opacity: 1; pointer-events: auto; }
  .chat-titulo { padding-right: 76px; }
  .carril { padding: 16px 14px 8px; }
  .flotante { bottom: 140px; right: 14px; }
}
@media (min-width: 900px) { .solo-movil { display: none !important; } }
@media (min-width: 1240px) {
  .app.con-panel { grid-template-columns: var(--lado) minmax(0, 1fr) var(--panel); }
  .app.con-panel.colapsado { grid-template-columns: var(--lado-col) minmax(0, 1fr) var(--panel); }
  .panel { position: static; transform: none; visibility: visible; display: none; box-shadow: none; transition: none; }
  .app.con-panel .panel { display: flex; }
  .velo-panel { display: none !important; }
}
@media (max-width: 520px) {
  .pill { max-width: 38vw; }
  .sugerencias { grid-template-columns: 1fr; }
  .msg.usuario .cuerpo { max-width: 92%; }
  .msg.agente .avatar { display: none; }
  .tema button span { display: none; }
}
@media (hover: none) { .chat-acciones { opacity: 1; pointer-events: auto; } .chat-titulo { padding-right: 76px; } }
@media (pointer: coarse) { .solo-puntero { display: none; } }
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: .01ms !important; animation-iteration-count: 1 !important; transition-duration: .01ms !important; scroll-behavior: auto !important; }
}
@media (forced-colors: active) {
  .boton.primario, .boton-redondo.enviar { border: 1px solid ButtonText; }
  .pill, .sugerencia, .entrada-caja { border: 1px solid CanvasText; }
}

/* ---------- Complementos ---------- */
.avatar { width: 32px; height: 32px; border-radius: 10px; margin-top: 2px; }
.avatar .ic { width: 17px; height: 17px; }
.codigo-cab .ic { width: 15px; height: 15px; }
.al-center { text-align: center; }
.al-right { text-align: right; }
.tarjeta-error .ic { width: 18px; height: 18px; }
.tarjeta-error .cab-error .ic { fill: none; }
.cierre-lado.icono { display: none; }
@media (max-width: 899px) { .cierre-lado.icono { display: inline-grid; } }
"""

SCRIPT = r""""use strict";
/* ==========================================================================
   Mi agente · interfaz web
   1 Utilidades · 2 Servicio API · 3 Markdown seguro · 4 Estado · 5 Mensajes
   6 Lista de chats · 7 Panel · 8 Diálogos y avisos · 9 Controlador · 10 Arranque
   Todo el contenido que llega del agente se inserta con textContent / nodos DOM,
   nunca con innerHTML, así que no puede ejecutar HTML ni scripts.
   ========================================================================== */
(() => {

/* ==================== 1. Utilidades ==================== */
const $ = (id) => document.getElementById(id);
const MAX_MENSAJE = 8000;
const MAX_SUBIDA = 60 * 1024 * 1024;
const EXT_FOTOS = [".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"];
const EXT_DOCS = [".pdf", ".docx", ".txt", ".md", ".csv", ".html", ".json", ".xml"];
const ACEPTAR_TODO = "image/*," + EXT_DOCS.concat(EXT_FOTOS).join(",");
const SVGNS = "http://www.w3.org/2000/svg";

const dormir = (ms) => new Promise((r) => setTimeout(r, ms));
const extension = (nombre) => { const i = nombre.lastIndexOf("."); return i < 0 ? "" : nombre.slice(i).toLowerCase(); };
const esEscritorio = () => window.matchMedia("(pointer: fine)").matches;
const hayPanelFijo = () => window.matchMedia("(min-width: 1240px)").matches;
const ahoraEsMovil = () => window.matchMedia("(max-width: 899px)").matches;

const memoria = {
  leer(clave, defecto) { try { const v = localStorage.getItem(clave); return v === null ? defecto : v; } catch (_) { return defecto; } },
  escribir(clave, valor) { try { localStorage.setItem(clave, valor); } catch (_) { /* almacenamiento no disponible */ } },
};

/** Crea un elemento. props: class, texto, onXxx (evento), cualquier atributo; hijos: nodos o texto. */
function el(etiqueta, props = {}, ...hijos) {
  const nodo = document.createElement(etiqueta);
  for (const [k, v] of Object.entries(props)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") nodo.className = v;
    else if (k === "texto") nodo.textContent = v;
    else if (k.startsWith("on") && typeof v === "function") nodo.addEventListener(k.slice(2), v);
    else nodo.setAttribute(k, v === true ? "" : String(v));
  }
  for (const h of hijos.flat()) {
    if (h === null || h === undefined || h === false) continue;
    nodo.append(typeof h === "object" && h.nodeType ? h : document.createTextNode(String(h)));
  }
  return nodo;
}

function icono(nombre) {
  const svg = document.createElementNS(SVGNS, "svg");
  svg.setAttribute("class", "ic");
  svg.setAttribute("aria-hidden", "true");
  const uso = document.createElementNS(SVGNS, "use");
  uso.setAttribute("href", "#i-" + nombre);
  svg.append(uso);
  return svg;
}

async function copiarTexto(texto) {
  try {
    if (navigator.clipboard && window.isSecureContext) { await navigator.clipboard.writeText(texto); return true; }
  } catch (_) { /* se prueba el método alternativo */ }
  const caja = el("textarea", { "aria-hidden": "true", tabindex: "-1" });
  caja.value = texto;
  caja.style.position = "fixed";
  caja.style.opacity = "0";
  document.body.append(caja);
  caja.select();
  let ok = false;
  try { ok = document.execCommand("copy"); } catch (_) { ok = false; }
  caja.remove();
  return ok;
}

/* ==================== 2. Servicio API ==================== */
class ErrorApi extends Error {
  constructor(mensaje, estado, datos) { super(mensaje); this.estado = estado; this.datos = datos; }
}

const Api = {
  async llamar(url, { metodo = "GET", cuerpo, tiempo = 30000 } = {}) {
    const control = new AbortController();
    const temporizador = setTimeout(() => control.abort(), tiempo);
    let respuesta;
    try {
      respuesta = await fetch(url, {
        method: metodo, credentials: "same-origin", signal: control.signal,
        headers: cuerpo ? { "Content-Type": "application/json" } : undefined,
        body: cuerpo ? JSON.stringify(cuerpo) : undefined,
      });
    } catch (_) {
      throw new ErrorApi("No hay conexión con el ordenador donde se ejecuta el agente.", 0);
    } finally {
      clearTimeout(temporizador);
    }
    let datos = null;
    try { datos = await respuesta.json(); } catch (_) { /* sin cuerpo JSON */ }
    if (respuesta.status === 401) {
      document.dispatchEvent(new CustomEvent("sesion-caducada"));
      throw new ErrorApi("Necesitas el PIN.", 401, datos);
    }
    if (!respuesta.ok) throw new ErrorApi((datos && datos.error) || "Error del servidor (" + respuesta.status + ").", respuesta.status, datos);
    return datos;
  },
  sesion: () => Api.llamar("/api/sesion", { tiempo: 8000 }),
  login: (pin) => Api.llamar("/api/login", { metodo: "POST", cuerpo: { pin } }),
  logout: () => Api.llamar("/api/logout", { metodo: "POST" }),
  configuracion: () => Api.llamar("/api/configuracion"),
  guardarClave: (clave) => Api.llamar("/api/configuracion/clave", { metodo: "POST", cuerpo: { clave }, tiempo: 120000 }),
  chats: () => Api.llamar("/api/chats"),
  chat: (id) => Api.llamar("/api/chats/" + encodeURIComponent(id)),
  renombrar: (id, titulo) => Api.llamar("/api/chats/" + encodeURIComponent(id), { metodo: "PATCH", cuerpo: { titulo } }),
  borrar: (id) => Api.llamar("/api/chats/" + encodeURIComponent(id), { metodo: "DELETE" }),
  enviar: (chatId, texto) => Api.llamar("/api/enviar", { metodo: "POST", cuerpo: { chat_id: chatId, texto } }),
  estado: () => Api.llamar("/api/estado", { tiempo: 8000 }),
  confirmar: (si) => Api.llamar("/api/confirmar", { metodo: "POST", cuerpo: { si } }),
  detener: () => Api.llamar("/api/detener", { metodo: "POST" }),
  contexto: () => Api.llamar("/api/contexto"),
  subir(archivos, alProgreso) {
    return new Promise((resolver, rechazar) => {
      const datos = new FormData();
      for (const f of archivos) datos.append("archivos", f, f.name);
      const x = new XMLHttpRequest();
      x.open("POST", "/api/subir");
      x.responseType = "json";
      x.upload.onprogress = (e) => { if (e.lengthComputable) alProgreso(e.loaded / e.total); };
      x.onload = () => {
        if (x.status === 401) {
          document.dispatchEvent(new CustomEvent("sesion-caducada"));
          rechazar(new ErrorApi("Necesitas el PIN.", 401));
        } else if (x.status >= 200 && x.status < 300) {
          resolver(x.response || {});
        } else {
          const motivo = x.status === 413 ? "El archivo es demasiado grande (máximo 60 MB)." : (x.response && x.response.error) || "No se pudo subir el archivo (" + x.status + ").";
          rechazar(new ErrorApi(motivo, x.status));
        }
      };
      x.onerror = () => rechazar(new ErrorApi("Se perdió la conexión mientras se subía el archivo.", 0));
      x.send(datos);
    });
  },
};

/* ==================== 3. Markdown seguro ==================== */
function urlSegura(texto) {
  try {
    const u = new URL(texto);
    return ["http:", "https:", "mailto:"].includes(u.protocol) ? u.href : null;
  } catch (_) { return null; }
}

/** Texto en línea -> lista de nodos {t, ...}. */
function parsearInline(texto) {
  const nodos = [];
  let buffer = "";
  let i = 0;
  const vaciar = () => { if (buffer) { nodos.push({ t: "texto", v: buffer }); buffer = ""; } };
  while (i < texto.length) {
    const c = texto[i];
    if (c === "`") {
      const fin = texto.indexOf("`", i + 1);
      if (fin > i + 1) { vaciar(); nodos.push({ t: "codigo", v: texto.slice(i + 1, fin) }); i = fin + 1; continue; }
    }
    if (c === "*" && texto[i + 1] === "*") {
      const fin = texto.indexOf("**", i + 2);
      if (fin > i + 2) { vaciar(); nodos.push({ t: "negrita", h: parsearInline(texto.slice(i + 2, fin)) }); i = fin + 2; continue; }
    }
    if ((c === "*" || c === "_") && texto[i + 1] && texto[i + 1] !== " " && texto[i + 1] !== c) {
      const fin = texto.indexOf(c, i + 1);
      const antes = i === 0 ? "" : texto[i - 1];
      const despues = fin < 0 ? "" : (texto[fin + 1] || "");
      const limpio = c === "*" || (!/\w/.test(antes) && !/\w/.test(despues));
      if (fin > i + 1 && texto[fin - 1] !== " " && limpio) {
        vaciar(); nodos.push({ t: "cursiva", h: parsearInline(texto.slice(i + 1, fin)) }); i = fin + 1; continue;
      }
    }
    if (c === "[") {
      const m = /^\[([^\]\n]+)\]\(([^)\s]+)\)/.exec(texto.slice(i));
      const href = m && urlSegura(m[2]);
      if (m && href) { vaciar(); nodos.push({ t: "enlace", href, h: parsearInline(m[1]) }); i += m[0].length; continue; }
    }
    if (c === "h" && (i === 0 || /[\s(]/.test(texto[i - 1]))) {
      const m = /^https?:\/\/[^\s<]+/.exec(texto.slice(i));
      if (m) {
        const url = m[0].replace(/[.,;:!?)\]]+$/, "");
        const href = urlSegura(url);
        if (href) { vaciar(); nodos.push({ t: "enlace", href, h: [{ t: "texto", v: url }] }); i += url.length; continue; }
      }
    }
    buffer += c;
    i++;
  }
  vaciar();
  return nodos;
}

const RE_ITEM = /^(\s*)([-*•]|\d+[.)])\s+(.*)$/;
const RE_TABLA_SEP = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;

/** Markdown -> lista de bloques. No genera HTML: solo estructuras de datos. */
function parsearMarkdown(texto) {
  const lineas = String(texto).replace(/\r\n?/g, "\n").split("\n");
  const bloques = [];
  const esEspecial = (l) => /^\s*(```|#{1,6}\s|>|[-*•]\s+|\d+[.)]\s+|\|)/.test(l) || /^\s*([-*_])\1{2,}\s*$/.test(l);
  const celdas = (s) => s.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((x) => x.trim());
  let i = 0;
  while (i < lineas.length) {
    const l = lineas[i];
    if (!l.trim()) { i++; continue; }

    let m = /^\s*\[\[foto:([^\]]+)\]\]\s*$/.exec(l);
    if (m) { bloques.push({ t: "foto", nombre: m[1].trim() }); i++; continue; }

    m = /^\s*```\s*([\w+#.-]*)\s*$/.exec(l);
    if (m) {
      const codigo = [];
      i++;
      while (i < lineas.length && !/^\s*```\s*$/.test(lineas[i])) { codigo.push(lineas[i]); i++; }
      i++;
      bloques.push({ t: "codigo", lenguaje: m[1], v: codigo.join("\n") });
      continue;
    }

    m = /^(#{1,6})\s+(.*?)\s*#*\s*$/.exec(l);
    if (m) { bloques.push({ t: "titulo", nivel: Math.min(m[1].length + 2, 6), h: parsearInline(m[2]) }); i++; continue; }

    if (/^\s*([-*_])\1{2,}\s*$/.test(l)) { bloques.push({ t: "regla" }); i++; continue; }

    if (/^\s*>/.test(l)) {
      const cita = [];
      while (i < lineas.length && /^\s*>/.test(lineas[i])) { cita.push(lineas[i].replace(/^\s*>\s?/, "")); i++; }
      bloques.push({ t: "cita", h: parsearMarkdown(cita.join("\n")) });
      continue;
    }

    if (/^\s*\|.*\|\s*$/.test(l) && i + 1 < lineas.length && RE_TABLA_SEP.test(lineas[i + 1]) && lineas[i + 1].includes("-")) {
      const cab = celdas(l);
      const al = celdas(lineas[i + 1]).map((x) => (x.startsWith(":") && x.endsWith(":") ? "center" : x.endsWith(":") ? "right" : "left"));
      i += 2;
      const filas = [];
      while (i < lineas.length && /^\s*\|.*\|\s*$/.test(lineas[i])) { filas.push(celdas(lineas[i])); i++; }
      bloques.push({ t: "tabla", cab, al, filas });
      continue;
    }

    m = RE_ITEM.exec(l);
    if (m) {
      const ordenada = /\d/.test(m[2]);
      const items = [];
      while (i < lineas.length) {
        const it = RE_ITEM.exec(lineas[i]);
        if (!it || /\d/.test(it[2]) !== ordenada) break;
        let contenido = it[3];
        i++;
        while (i < lineas.length && lineas[i].trim() && /^\s{2,}\S/.test(lineas[i]) && !RE_ITEM.test(lineas[i])) { contenido += " " + lineas[i].trim(); i++; }
        items.push(parsearInline(contenido));
      }
      bloques.push({ t: "lista", ordenada, items });
      continue;
    }

    const parrafo = [l];
    i++;
    while (i < lineas.length && lineas[i].trim() && !esEspecial(lineas[i])) { parrafo.push(lineas[i]); i++; }
    bloques.push({ t: "parrafo", lineas: parrafo.map(parsearInline) });
  }
  return bloques;
}

function renderInline(nodos) {
  const f = document.createDocumentFragment();
  for (const n of nodos) {
    if (n.t === "texto") f.append(n.v);
    else if (n.t === "negrita") f.append(el("strong", {}, renderInline(n.h)));
    else if (n.t === "cursiva") f.append(el("em", {}, renderInline(n.h)));
    else if (n.t === "codigo") f.append(el("code", { texto: n.v }));
    else if (n.t === "enlace") f.append(el("a", { href: n.href, target: "_blank", rel: "noopener noreferrer nofollow" }, renderInline(n.h)));
  }
  return f;
}

function bloqueCodigo(b) {
  const boton = el("button", { class: "boton", type: "button", "aria-label": "Copiar el código" }, icono("copy"), "Copiar");
  boton.addEventListener("click", async () => {
    if (!(await copiarTexto(b.v))) { avisar("No se pudo copiar el código.", true); return; }
    boton.replaceChildren(icono("check"), "Copiado");
    setTimeout(() => boton.replaceChildren(icono("copy"), "Copiar"), 1600);
  });
  return el("div", { class: "codigo" },
    el("div", { class: "codigo-cab" }, el("span", { texto: b.lenguaje || "código" }), boton),
    el("pre", {}, el("code", { texto: b.v })));
}

function tablaDom(b) {
  const alinear = (i) => "al-" + (b.al[i] || "left");
  const cabecera = el("thead", {}, el("tr", {}, b.cab.map((c, i) => el("th", { scope: "col", class: alinear(i) }, renderInline(parsearInline(c))))));
  const cuerpo = el("tbody", {}, b.filas.map((fila) => el("tr", {}, b.cab.map((_, i) => el("td", { class: alinear(i) }, renderInline(parsearInline(fila[i] || "")))))));
  return el("div", { class: "tabla-scroll", role: "region", "aria-label": "Tabla", tabindex: "0" }, el("table", {}, cabecera, cuerpo));
}

function fotoDom(nombre) {
  const url = "/api/foto/" + encodeURIComponent(nombre);
  const img = el("img", { src: url, alt: "Foto " + nombre, loading: "lazy" });
  const figura = el("figure", { class: "foto" },
    el("a", { href: url, target: "_blank", rel: "noopener", "aria-label": "Abrir la foto " + nombre + " en una pestaña nueva" }, img),
    el("figcaption", {}, el("span", { texto: nombre }), el("a", { href: url, download: nombre }, "Descargar")));
  img.addEventListener("error", () => figura.replaceChildren(el("p", { class: "suave", texto: "No se puede mostrar la foto «" + nombre + "»." })));
  return figura;
}

function renderBloques(bloques) {
  const f = document.createDocumentFragment();
  for (const b of bloques) {
    if (b.t === "parrafo") {
      const p = el("p");
      b.lineas.forEach((l, i) => { if (i) p.append(el("br")); p.append(renderInline(l)); });
      f.append(p);
    } else if (b.t === "titulo") f.append(el("h" + b.nivel, {}, renderInline(b.h)));
    else if (b.t === "lista") f.append(el(b.ordenada ? "ol" : "ul", {}, b.items.map((it) => el("li", {}, renderInline(it)))));
    else if (b.t === "cita") f.append(el("blockquote", {}, renderBloques(b.h)));
    else if (b.t === "regla") f.append(el("hr"));
    else if (b.t === "codigo") f.append(bloqueCodigo(b));
    else if (b.t === "tabla") f.append(tablaDom(b));
    else if (b.t === "foto") f.append(fotoDom(b.nombre));
  }
  return f;
}

/* ==================== 4. Estado ==================== */
const S = {
  chatId: null, mensajes: [], chats: [], chatsCargados: false, cargandoChat: false,
  ocupado: false, enviando: false, deteniendo: false, subiendo: false, sondeando: false, confirmando: false,
  filtro: "", ladoAbierto: false, pasos: [], actividad: [],
  panel: { abierto: false, pestana: "contexto", datos: null, cargando: false, error: null },
};
const E = {}; // referencias a elementos del DOM, se rellenan al arrancar

const SUGERENCIAS = [
  { icono: "calendar", titulo: "Resumen del día", desc: "Fecha, tareas pendientes y tus 3 prioridades.", accion: { enviar: "Hazme el resumen del día" } },
  { icono: "tasks", titulo: "Mis tareas", desc: "Lo que tienes pendiente, ordenado por fecha.", accion: { enviar: "¿Qué tareas tengo pendientes?" } },
  { icono: "cards", titulo: "Repasar con tarjetas", desc: "Preguntas de tus apuntes, de una en una.", accion: { enviar: "Pregúntame con mis tarjetas de repaso, de una en una" } },
  { icono: "doc", titulo: "Entender un documento", desc: "Sube un PDF o Word y te explico qué tienes que hacer.", accion: { archivo: EXT_DOCS.join(",") } },
  { icono: "image", titulo: "Editar una foto", desc: "Recortar, girar, filtros, texto o reducir su peso.", accion: { archivo: "image/*" } },
  { icono: "code", titulo: "Revisar mi código", desc: "Deja el archivo en la carpeta «codigo» y lo reviso.", accion: { rellenar: "Revisa mi archivo " } },
];

/* ---------- Apariencia ---------- */
function aplicarTema(tema) {
  document.documentElement.dataset.tema = tema;
  memoria.escribir("tema", tema);
  document.querySelectorAll(".tema button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.tema === tema)));
  const oscuro = tema === "oscuro" || (tema === "auto" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.querySelector('meta[name="theme-color"]').setAttribute("content", oscuro ? "#0a0c11" : "#f5f6fa");
}

function ponerColapsado(valor) {
  E.app.classList.toggle("colapsado", valor);
  E.btnColapsar.setAttribute("aria-expanded", String(!valor));
  const texto = valor ? "Expandir menú" : "Contraer menú";
  E.btnColapsar.setAttribute("aria-label", texto);
  E.btnColapsar.title = texto;
  memoria.escribir("colapsado", valor ? "1" : "0");
}

function actualizarVelo() {
  E.velo.hidden = !(S.ladoAbierto || (S.panel.abierto && !hayPanelFijo()));
}
function abrirLado() {
  S.ladoAbierto = true;
  E.app.classList.add("con-lado");
  E.btnMenu.setAttribute("aria-expanded", "true");
  actualizarVelo();
  E.btnCerrarLado.focus();
}
function cerrarLado(devolverFoco = true) {
  if (!S.ladoAbierto) return;
  S.ladoAbierto = false;
  E.app.classList.remove("con-lado");
  E.btnMenu.setAttribute("aria-expanded", "false");
  actualizarVelo();
  if (devolverFoco && ahoraEsMovil()) E.btnMenu.focus();
}

/* ---------- Estado visual ---------- */
function ponerPill(tipo, texto) {
  E.pill.dataset.tipo = tipo;
  E.pillTexto.textContent = texto;
}
function avisar(texto, mal = false) {
  const aviso = el("div", { class: "aviso" + (mal ? " mal" : ""), texto });
  E.avisos.append(aviso);
  setTimeout(() => aviso.remove(), mal ? 5200 : 2800);
}
function actualizarEnviar() {
  E.btnEnviar.disabled = S.ocupado || !E.entrada.value.trim();
}
function autoajustar() {
  E.entrada.style.height = "auto";
  E.entrada.style.height = Math.min(E.entrada.scrollHeight, 200) + "px";
  const n = E.entrada.value.length;
  E.contador.hidden = n < MAX_MENSAJE * 0.8;
  E.contador.textContent = n + " / " + MAX_MENSAJE;
  E.contador.classList.toggle("alerta", n >= MAX_MENSAJE);
}
function escribirEnEntrada(texto) {
  E.entrada.value = texto;
  autoajustar();
  actualizarEnviar();
  E.entrada.focus();
  E.entrada.setSelectionRange(texto.length, texto.length);
}
function setOcupado(valor) {
  S.ocupado = valor;
  E.btnDetener.hidden = !valor;
  E.btnEnviar.hidden = valor;
  E.btnAdjuntar.disabled = valor;
  E.btnNuevo.disabled = valor;
  E.lista.toggleAttribute("inert", valor);
  E.entrada.setAttribute("aria-busy", String(valor));
  if (!valor) { S.deteniendo = false; E.btnDetener.disabled = false; }
  actualizarEnviar();
  ponerPill(valor ? "trabajando" : "listo", valor ? "Trabajando…" : "Listo");
}

/* ==================== 5. Mensajes ==================== */
function cercaDelFinal() {
  const c = E.conversacion;
  return c.scrollHeight - c.scrollTop - c.clientHeight < 140;
}
function bajar(forzar = false) {
  if (!forzar && !cercaDelFinal()) return;
  requestAnimationFrame(() => E.conversacion.scrollTo({ top: E.conversacion.scrollHeight, behavior: forzar ? "instant" : "smooth" }));
}
function actualizarBotonFinal() {
  E.btnFinal.hidden = cercaDelFinal() || (S.mensajes.length === 0 && !E.pensando);
}
function actualizarBienvenida() {
  E.bienvenida.hidden = S.mensajes.length > 0 || S.cargandoChat || !!E.pensando;
}
function actualizarTitulo(texto) {
  E.titulo.textContent = texto || "Nuevo chat";
  document.title = (texto ? texto + " · " : "") + "Mi agente";
}

function textoUsuarioAnterior(indice) {
  for (let i = indice - 1; i >= 0; i--) if (S.mensajes[i].rol === "usuario") return S.mensajes[i].texto;
  return null;
}

function crearError(m, indice) {
  const detenido = /^Respuesta detenida/.test(m.texto);
  const corte = m.texto.indexOf("\n\nDetalle técnico:");
  const principal = corte < 0 ? m.texto : m.texto.slice(0, corte);
  const detalle = corte < 0 ? "" : m.texto.slice(corte).replace(/^\n\nDetalle técnico:\s*/, "");
  const tarjeta = el("div", { class: "tarjeta-error" },
    el("div", { class: "cab-error" }, icono(detenido ? "stop" : "alert"), detenido ? "Respuesta detenida" : "No se pudo completar"),
    el("p", { texto: principal }));
  if (detalle) tarjeta.append(el("details", {}, el("summary", { texto: "Ver detalle técnico" }), el("pre", { texto: detalle })));
  if (!detenido) {
    tarjeta.append(el("button", { class: "boton reintentar", type: "button", onclick: () => reintentar(m, indice) }, icono("retry"), "Reintentar"));
  }
  return el("article", { class: "msg error" + (detenido ? " detenido" : ""), role: detenido ? "status" : "alert" }, tarjeta);
}

function crearMensaje(m, indice) {
  if (m.rol === "usuario") return el("article", { class: "msg usuario" }, el("div", { class: "cuerpo", texto: m.texto }));
  if (m.rol === "error") return crearError(m, indice);
  const limpio = m.texto.replace(/\[\[foto:[^\]]+\]\]/g, "").trim();
  const copiar = el("button", { class: "icono", type: "button", "aria-label": "Copiar la respuesta", title: "Copiar" }, icono("copy"));
  copiar.addEventListener("click", async () => {
    if (!(await copiarTexto(limpio))) { avisar("No se pudo copiar.", true); return; }
    copiar.replaceChildren(icono("check"));
    avisar("Respuesta copiada");
    setTimeout(() => copiar.replaceChildren(icono("copy")), 1600);
  });
  return el("article", { class: "msg agente" },
    el("span", { class: "logo avatar", "aria-hidden": "true" }, icono("spark")),
    el("div", { class: "contenido" },
      el("div", { class: "prosa" }, renderBloques(parsearMarkdown(m.texto))),
      el("div", { class: "acciones" }, copiar)));
}

function pintarMensajes(lista) {
  E.mensajes.setAttribute("aria-busy", "true");
  E.mensajes.replaceChildren(...lista.map((m, i) => crearMensaje(m, i)));
  E.mensajes.setAttribute("aria-busy", "false");
  actualizarBienvenida();
}
function anadirDom(m, indice) {
  E.mensajes.querySelectorAll(".reintentar").forEach((b) => b.remove()); // solo el último error se puede reintentar
  const nodo = crearMensaje(m, indice);
  if (E.pensando) E.mensajes.insertBefore(nodo, E.pensando); else E.mensajes.append(nodo);
}
function anadirMensaje(m) {
  S.mensajes.push(m);
  anadirDom(m, S.mensajes.length - 1);
  actualizarBienvenida();
  bajar(m.rol === "usuario");
}
function mostrarEsqueletos() {
  E.mensajes.replaceChildren(el("div", { class: "esqueleto" }), el("div", { class: "esqueleto corto" }), el("div", { class: "esqueleto" }));
}

function mostrarPensando() {
  quitarPensando();
  E.pensTexto = el("span", { texto: "Pensando…" });
  E.pensPasos = el("ul", { class: "pasos", "aria-label": "Pasos realizados" });
  E.pensando = el("div", { id: "pensando", class: "pensando" },
    el("span", { class: "logo avatar", "aria-hidden": "true" }, icono("spark")),
    el("div", { class: "tarjeta" },
      el("div", { class: "fila" }, E.pensTexto),
      el("div", { class: "progreso", role: "progressbar", "aria-label": "El agente está trabajando" }),
      E.pensPasos));
  E.mensajes.append(E.pensando);
  actualizarBienvenida();
  bajar(true);
}
function quitarPensando() {
  if (E.pensando) E.pensando.remove();
  E.pensando = null;
  actualizarBienvenida();
}
function actualizarPensando(e) {
  if (!E.pensando) return;
  E.pensTexto.textContent = e.estado || "Pensando…";
  ponerPill("trabajando", e.estado || "Trabajando…");
  const pasos = e.pasos || [];
  if (pasos.length !== S.pasos.length) {
    E.pensPasos.replaceChildren(...pasos.map((p) => el("li", {}, icono("check"), p)));
    bajar();
  }
  S.pasos = pasos;
}

/* ==================== 6. Lista de chats ==================== */
function nombreGrupo(iso) {
  const fecha = new Date(iso);
  if (Number.isNaN(fecha.getTime())) return "Anteriores";
  const inicio = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const dias = Math.round((inicio(new Date()) - inicio(fecha)) / 86400000);
  if (dias <= 0) return "Hoy";
  if (dias === 1) return "Ayer";
  if (dias <= 7) return "Últimos 7 días";
  if (dias <= 30) return "Este mes";
  return "Anteriores";
}

function itemChat(c) {
  const activo = c.id === S.chatId;
  const abrir = el("button", { class: "chat-titulo", type: "button", title: c.titulo, "aria-current": activo ? "true" : null, texto: c.titulo, onclick: () => abrirChat(c.id) });
  const renombrarBtn = el("button", { class: "icono", type: "button", "aria-label": "Renombrar «" + c.titulo + "»", title: "Renombrar", onclick: () => renombrar(c) }, icono("pencil"));
  const borrarBtn = el("button", { class: "icono", type: "button", "aria-label": "Eliminar «" + c.titulo + "»", title: "Eliminar", onclick: () => borrar(c) }, icono("trash"));
  return el("div", { class: "chat-item" + (activo ? " activo" : "") }, abrir, el("div", { class: "chat-acciones" }, renombrarBtn, borrarBtn));
}

function pintarLista() {
  E.lista.replaceChildren();
  if (!S.chatsCargados) {
    E.lista.append(el("div", { class: "esqueleto" }), el("div", { class: "esqueleto corto" }), el("div", { class: "esqueleto" }));
    return;
  }
  const q = S.filtro.trim().toLowerCase();
  const chats = S.chats.filter((c) => !q || c.titulo.toLowerCase().includes(q));
  if (!chats.length) {
    E.lista.append(el("p", { class: "vacio", texto: q ? "Ninguna conversación coincide." : "Aún no hay conversaciones. Escribe algo para empezar." }));
    return;
  }
  let grupo = "";
  for (const c of chats) {
    const g = nombreGrupo(c.actualizada);
    if (g !== grupo) { E.lista.append(el("div", { class: "grupo", texto: g })); grupo = g; }
    E.lista.append(itemChat(c));
  }
}

async function cargarChats() {
  try {
    S.chats = await Api.chats();
    S.chatsCargados = true;
    pintarLista();
  } catch (e) {
    if (e.estado === 401) return;
    S.chatsCargados = true;
    S.chats = [];
    pintarLista();
    E.lista.replaceChildren(el("div", { class: "vacio" }, el("p", { texto: "No se pudo cargar el historial." }),
      el("button", { class: "boton pequeno", type: "button", onclick: () => { S.chatsCargados = false; pintarLista(); cargarChats(); } }, "Reintentar")));
  }
}

async function nuevoChat() {
  if (S.ocupado) return;
  S.chatId = null;
  S.mensajes = [];
  pintarMensajes([]);
  actualizarTitulo("");
  pintarLista();
  cerrarLado(false);
  actualizarBotonFinal();
  if (esEscritorio()) E.entrada.focus();
}

async function abrirChat(id) {
  if (S.ocupado) return;
  cerrarLado(false);
  if (id === S.chatId && S.mensajes.length) return;
  S.chatId = id;
  S.mensajes = [];
  S.cargandoChat = true;
  actualizarBienvenida();
  mostrarEsqueletos();
  pintarLista();
  try {
    const conv = await Api.chat(id);
    if (S.chatId !== id) return;
    S.mensajes = conv.mensajes;
    actualizarTitulo(conv.titulo);
    S.cargandoChat = false;
    pintarMensajes(S.mensajes);
    bajar(true);
    E.conversacion.focus({ preventScroll: true });
  } catch (e) {
    S.cargandoChat = false;
    if (e.estado === 404) { avisar("Esa conversación ya no existe.", true); S.chatId = null; await cargarChats(); pintarMensajes([]); actualizarTitulo(""); }
    else if (e.estado !== 401) { pintarMensajes([]); anadirMensaje({ rol: "error", texto: e.message }); }
  }
}

async function renombrar(c) {
  if (S.ocupado) return;
  E.dlgTextoCampo.value = c.titulo;
  const resultado = await abrirDialogo(E.dlgTexto);
  const nuevo = E.dlgTextoCampo.value.replace(/\s+/g, " ").trim();
  if (resultado !== "si" || !nuevo || nuevo === c.titulo) return;
  try {
    await Api.renombrar(c.id, nuevo);
    c.titulo = nuevo;
    if (c.id === S.chatId) actualizarTitulo(nuevo);
    pintarLista();
    avisar("Conversación renombrada");
  } catch (e) { if (e.estado !== 401) avisar(e.message, true); }
}

async function borrar(c) {
  if (S.ocupado) return;
  E.dlgBorrarTexto.textContent = "Se eliminará «" + c.titulo + "» con todos sus mensajes. Esta acción no se puede deshacer.";
  if ((await abrirDialogo(E.dlgBorrar)) !== "si") return;
  try {
    await Api.borrar(c.id);
    S.chats = S.chats.filter((x) => x.id !== c.id);
    if (c.id === S.chatId) await nuevoChat(); else pintarLista();
    avisar("Conversación eliminada");
  } catch (e) { if (e.estado !== 401) avisar(e.message, true); }
}

/* ==================== 7. Panel de herramientas y contexto ==================== */
function abrirPanel(pestana) {
  if (pestana) S.panel.pestana = pestana;
  S.panel.abierto = true;
  E.app.classList.add("con-panel");
  E.btnPanel.setAttribute("aria-expanded", "true");
  actualizarVelo();
  pintarPanel();
  cargarContexto();
  if (!hayPanelFijo()) E.btnPanelCerrar.focus();
}
function cerrarPanel() {
  if (!S.panel.abierto) return;
  S.panel.abierto = false;
  E.app.classList.remove("con-panel");
  E.btnPanel.setAttribute("aria-expanded", "false");
  actualizarVelo();
  E.btnPanel.focus();
}
function alternarPanel() { if (S.panel.abierto) cerrarPanel(); else abrirPanel(); }

async function cargarContexto(silencioso = false) {
  if (S.panel.cargando) return;
  S.panel.cargando = true;
  if (!silencioso) { S.panel.error = null; pintarPanel(); }
  try {
    S.panel.datos = await Api.contexto();
    S.panel.error = null;
  } catch (e) {
    if (e.estado !== 401) S.panel.error = e.message;
  } finally {
    S.panel.cargando = false;
    if (S.panel.abierto) pintarPanel();
  }
}

function accionDesdePanel(accion) {
  if (!hayPanelFijo()) cerrarPanel();
  accion();
}

function pintarPanel() {
  const cuerpo = E.cuerpoPanel;
  document.querySelectorAll(".pestanas button").forEach((b) => {
    const activa = b.dataset.pestana === S.panel.pestana;
    b.setAttribute("aria-selected", String(activa));
    b.tabIndex = activa ? 0 : -1;
  });
  cuerpo.setAttribute("aria-labelledby", S.panel.pestana === "contexto" ? "tabContexto" : "tabHerramientas");
  const d = S.panel.datos;
  if (!d) {
    if (S.panel.error) {
      cuerpo.replaceChildren(el("p", { class: "suave", texto: S.panel.error }),
        el("button", { class: "boton pequeno", type: "button", onclick: () => cargarContexto() }, "Reintentar"));
    } else {
      cuerpo.replaceChildren(el("div", { class: "esqueleto" }), el("div", { class: "esqueleto corto" }), el("div", { class: "esqueleto" }));
    }
    return;
  }
  cuerpo.replaceChildren(S.panel.pestana === "contexto" ? contextoDom(d) : herramientasDom(d));
}

function contextoDom(d) {
  const cifra = (n, etiqueta, frase) => el("button", { class: "cifra", type: "button", onclick: () => accionDesdePanel(() => enviar(frase)) }, el("b", { texto: String(n) }), el("span", { texto: etiqueta }));
  const f = document.createDocumentFragment();
  f.append(el("h3", { texto: "Resumen" }),
    el("div", { class: "cifras" },
      cifra(d.resumen.tareas_pendientes, "Tareas pendientes", "¿Qué tareas tengo pendientes?"),
      cifra(d.resumen.apuntes, "Apuntes guardados", "Enséñame mis apuntes"),
      cifra(d.resumen.tarjetas, "Tarjetas de repaso", "Pregúntame con mis tarjetas de repaso, de una en una"),
      cifra(d.documentos.length, "Documentos subidos", "¿Qué documentos tengo subidos?")));
  if (d.proximas.length) {
    f.append(el("h3", { texto: "Próximas tareas" }),
      el("ul", { class: "elementos" }, d.proximas.map((t) => el("li", {}, el("div", { class: "elemento" }, icono("tasks"), el("span", { class: "nom", texto: t.titulo }), el("small", { texto: t.fecha_limite || "sin fecha" }))))));
  }
  f.append(el("h3", { texto: "Documentos" }));
  f.append(d.documentos.length
    ? el("ul", { class: "elementos" }, d.documentos.map((x) => el("li", {}, el("button", { class: "elemento", type: "button", title: "Leer y explicar este documento", onclick: () => accionDesdePanel(() => enviar("Léeme el documento «" + x.nombre + "» y explícame qué tengo que hacer.")) }, icono("doc"), el("span", { class: "nom", texto: x.nombre }), el("small", { texto: x.kb + " KB" })))))
    : el("p", { class: "suave", texto: "Aún no has subido documentos." }));
  f.append(el("h3", { texto: "Fotos" }));
  f.append(d.fotos.length
    ? el("ul", { class: "elementos" }, d.fotos.map((x) => el("li", {}, el("button", { class: "elemento", type: "button", title: "Editar esta foto", onclick: () => accionDesdePanel(() => escribirEnEntrada("Edita mi foto «" + x.nombre + "»: ")) }, icono("image"), el("span", { class: "nom", texto: x.nombre }), el("small", { texto: x.editada ? "editada" : x.kb + " KB" })))))
    : el("p", { class: "suave", texto: "Aún no has subido fotos." }));
  return f;
}

function herramientasDom(d) {
  const f = document.createDocumentFragment();
  if (S.actividad.length) {
    f.append(el("h3", { texto: "Última actividad" }), el("ul", { class: "pasos" }, S.actividad.map((p) => el("li", {}, icono("check"), p))));
  }
  const grupos = new Map();
  for (const h of d.herramientas) {
    if (!grupos.has(h.categoria)) grupos.set(h.categoria, []);
    grupos.get(h.categoria).push(h);
  }
  for (const [categoria, lista] of grupos) {
    f.append(el("h3", { texto: categoria }));
    lista.forEach((h) => f.append(el("div", { class: "herramienta" }, el("strong", { texto: h.titulo }), el("p", { texto: h.descripcion }))));
  }
  return f;
}

/* ==================== 8. Diálogos ==================== */
function abrirDialogo(dialogo) {
  return new Promise((resolver) => {
    dialogo.returnValue = "";
    dialogo.addEventListener("close", () => resolver(dialogo.returnValue), { once: true });
    dialogo.showModal();
  });
}

function pintarDiff(texto) {
  E.dlgConfirmarTexto.replaceChildren(...texto.split("\n").map((linea) => {
    const clase = linea.startsWith("+") && !linea.startsWith("+++") ? "mas" : linea.startsWith("-") && !linea.startsWith("---") ? "menos" : null;
    return el("div", { class: clase, texto: linea || " " });
  }));
}

async function pedirConfirmacion(texto) {
  if (S.confirmando) return;
  S.confirmando = true;
  pintarDiff(texto);
  const resultado = await abrirDialogo(E.dlgConfirmar);
  S.confirmando = false;
  if (resultado === "cerrado") return; // el servidor ya no esperaba respuesta
  try { await Api.confirmar(resultado === "si"); } catch (e) { if (e.estado !== 401 && e.estado !== 409) avisar(e.message, true); }
}
function cerrarConfirmacion() {
  if (E.dlgConfirmar.open) E.dlgConfirmar.close("cerrado");
}

function mostrarLogin() {
  if (E.dlgLogin.open) return;
  E.loginError.textContent = "";
  E.dlgLogin.showModal();
  E.pin.focus();
}

function mostrarDialogoClave() {
  if (E.dlgClave.open) return;
  E.claveError.textContent = "";
  E.dlgClave.showModal();
  E.claveApi.focus();
}

/* ==================== 9. Controlador ==================== */
async function enviar(texto) {
  const mensaje = (texto === undefined ? E.entrada.value : texto).trim();
  if (!mensaje) { avisar("Escribe un mensaje antes de enviar.", true); E.entrada.focus(); return; }
  if (mensaje.length > MAX_MENSAJE) { avisar("El mensaje es demasiado largo (máximo " + MAX_MENSAJE + " caracteres).", true); return; }
  if (S.ocupado || S.enviando) return; // evita envíos duplicados
  S.enviando = true;
  const eraNuevo = S.chatId === null;
  anadirMensaje({ rol: "usuario", texto: mensaje });
  if (texto === undefined) { E.entrada.value = ""; autoajustar(); }
  setOcupado(true);
  mostrarPensando();
  S.pasos = [];
  S.actividad = [];
  try {
    const r = await Api.enviar(S.chatId, mensaje);
    S.chatId = r.chat_id;
    if (eraNuevo) actualizarTitulo(mensaje.length > 40 ? mensaje.slice(0, 39) + "…" : mensaje);
    cargarChats();
    sondear();
  } catch (e) {
    quitarPensando();
    setOcupado(false);
    if (e.estado !== 401) anadirMensaje({ rol: "error", texto: e.message, local: true });
    else { S.mensajes.pop(); pintarMensajes(S.mensajes); escribirEnEntrada(mensaje); }
  } finally {
    S.enviando = false;
  }
}

function reintentar(m, indice) {
  if (S.ocupado) return;
  const texto = textoUsuarioAnterior(indice);
  if (!texto) return;
  if (m.local) { // el mensaje nunca llegó al servidor: se quitan el aviso y el mensaje para no duplicarlos
    S.mensajes.splice(indice - 1, 2);
    pintarMensajes(S.mensajes);
  }
  enviar(texto);
}

async function detener() {
  if (!S.ocupado || S.deteniendo) return;
  S.deteniendo = true;
  E.btnDetener.disabled = true;
  if (E.pensTexto) E.pensTexto.textContent = "Deteniendo… se parará al terminar el paso actual";
  ponerPill("trabajando", "Deteniendo…");
  try { await Api.detener(); } catch (e) { if (e.estado !== 409 && e.estado !== 401) avisar(e.message, true); }
}

async function sondear() {
  if (S.sondeando) return;
  S.sondeando = true;
  let fallos = 0;
  try {
    for (;;) {
      try {
        const e = await Api.estado();
        fallos = 0;
        if (!e.ocupado) { S.pasos = e.pasos || S.pasos; break; } // el servidor conserva los pasos de la última ejecución
        actualizarPensando(e);
        if (e.confirmacion) pedirConfirmacion(e.confirmacion); else cerrarConfirmacion();
        await dormir(500);
      } catch (err) {
        if (err.estado === 401) return;
        fallos++;
        ponerPill("offline", "Reconectando…");
        await dormir(Math.min(1000 * fallos, 4000));
      }
    }
  } finally {
    S.sondeando = false;
  }
  await alTerminar();
}

async function alTerminar() {
  cerrarConfirmacion();
  S.actividad = S.pasos.slice();
  quitarPensando();
  setOcupado(false);
  if (S.chatId) {
    try {
      const conv = await Api.chat(S.chatId);
      const n = S.mensajes.length;
      const compatible = n > 0 && conv.mensajes.length >= n && conv.mensajes.slice(0, n).every((m, i) => m.rol === S.mensajes[i].rol && m.texto === S.mensajes[i].texto);
      S.mensajes = conv.mensajes.slice();
      actualizarTitulo(conv.titulo);
      if (compatible) conv.mensajes.slice(n).forEach((m, k) => anadirDom(m, n + k)); else pintarMensajes(S.mensajes);
      bajar(true);
      const ultimo = S.mensajes[S.mensajes.length - 1];
      if (ultimo && ultimo.rol === "error") ponerPill("error", /^Respuesta detenida/.test(ultimo.texto) ? "Detenido" : "No se pudo completar");
    } catch (e) {
      if (e.estado !== 401) anadirMensaje({ rol: "error", texto: "No se pudo recuperar la respuesta: " + e.message, local: true });
    }
  }
  cargarChats();
  if (S.panel.abierto) cargarContexto(true);
  if (esEscritorio()) E.entrada.focus();
}

/* ---------- Subida de archivos ---------- */
async function subirArchivos(lista) {
  const archivos = Array.from(lista);
  if (!archivos.length || S.ocupado || S.subiendo) return;
  const validos = [];
  const rechazados = [];
  for (const f of archivos) {
    const ext = extension(f.name);
    if (!EXT_FOTOS.includes(ext) && !EXT_DOCS.includes(ext)) rechazados.push(f.name + " (formato no admitido)");
    else if (f.size > MAX_SUBIDA) rechazados.push(f.name + " (supera 60 MB)");
    else validos.push(f);
  }
  if (rechazados.length) avisar("No se pueden subir: " + rechazados.join(", "), true);
  if (!validos.length) return;
  S.subiendo = true;
  E.subida.hidden = false;
  E.subidaBarra.style.setProperty("--p", "0");
  E.subidaTexto.textContent = "Subiendo " + (validos.length === 1 ? validos[0].name : validos.length + " archivos") + "…";
  try {
    const r = await Api.subir(validos, (p) => {
      E.subidaBarra.style.setProperty("--p", p.toFixed(3));
      E.subidaTexto.textContent = "Subiendo… " + Math.round(p * 100) + " %";
    });
    const docs = r.subidos || [];
    const fotos = r.fotos || [];
    if (r.rechazados && r.rechazados.length) avisar("El servidor no admite: " + r.rechazados.join(", "), true);
    if (docs.length || fotos.length) {
      avisar("Subido: " + docs.concat(fotos).join(", "));
      if (docs.length) {
        escribirEnEntrada(docs.length === 1
          ? "He subido el archivo «" + docs[0] + "». Léelo y explícame qué tengo que hacer."
          : "He subido estos archivos: " + docs.map((s) => "«" + s + "»").join(", ") + ". Léelos y explícame qué tengo que hacer.");
      } else {
        escribirEnEntrada(fotos.length === 1
          ? "He subido la foto «" + fotos[0] + "». Quiero que "
          : "He subido estas fotos: " + fotos.map((s) => "«" + s + "»").join(", ") + ". Quiero que ");
      }
      if (S.panel.abierto) cargarContexto(true);
    }
  } catch (e) {
    if (e.estado !== 401) avisar(e.message, true);
  } finally {
    S.subiendo = false;
    E.subida.hidden = true;
  }
}

function elegirArchivos(aceptar) {
  if (S.ocupado || S.subiendo) return;
  E.archivo.accept = aceptar || ACEPTAR_TODO;
  E.archivo.click();
}

function usarSugerencia(s) {
  if (s.accion.enviar) enviar(s.accion.enviar);
  else if (s.accion.archivo) elegirArchivos(s.accion.archivo);
  else if (s.accion.rellenar) escribirEnEntrada(s.accion.rellenar);
}

/* ==================== 10. Arranque ==================== */
function enlazarEventos() {
  E.formulario.addEventListener("submit", (ev) => { ev.preventDefault(); enviar(); });
  E.entrada.addEventListener("input", () => { autoajustar(); actualizarEnviar(); });
  E.entrada.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && !ev.shiftKey && !ev.isComposing && esEscritorio()) { ev.preventDefault(); enviar(); }
  });
  E.btnDetener.addEventListener("click", detener);
  E.btnAdjuntar.addEventListener("click", () => elegirArchivos(""));
  E.archivo.addEventListener("change", () => { subirArchivos(E.archivo.files); E.archivo.value = ""; });
  E.btnNuevo.addEventListener("click", nuevoChat);
  E.buscar.addEventListener("input", () => { S.filtro = E.buscar.value; pintarLista(); });
  E.btnColapsar.addEventListener("click", () => ponerColapsado(!E.app.classList.contains("colapsado")));
  E.btnMenu.addEventListener("click", abrirLado);
  E.btnCerrarLado.addEventListener("click", () => cerrarLado());
  E.velo.addEventListener("click", () => { cerrarLado(false); if (S.panel.abierto && !hayPanelFijo()) cerrarPanel(); });
  E.btnPanel.addEventListener("click", alternarPanel);
  E.btnPanelLado.addEventListener("click", () => { cerrarLado(false); abrirPanel(); });
  E.btnPanelCerrar.addEventListener("click", cerrarPanel);
  E.btnPanelRefrescar.addEventListener("click", () => cargarContexto());
  E.btnFinal.addEventListener("click", () => bajar(true));
  E.conversacion.addEventListener("scroll", actualizarBotonFinal, { passive: true });
  document.querySelectorAll(".tema button").forEach((b) => b.addEventListener("click", () => aplicarTema(b.dataset.tema)));
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => aplicarTema(document.documentElement.dataset.tema));
  window.addEventListener("resize", actualizarVelo);

  E.btnSalir.addEventListener("click", async () => {
    try { await Api.logout(); } catch (_) { /* da igual: se recarga */ }
    location.reload();
  });

  // Pestañas del panel (flechas izquierda/derecha)
  const pestanas = Array.from(document.querySelectorAll(".pestanas button"));
  pestanas.forEach((b, i) => {
    b.addEventListener("click", () => { S.panel.pestana = b.dataset.pestana; pintarPanel(); });
    b.addEventListener("keydown", (ev) => {
      if (ev.key !== "ArrowRight" && ev.key !== "ArrowLeft") return;
      const siguiente = pestanas[(i + (ev.key === "ArrowRight" ? 1 : -1) + pestanas.length) % pestanas.length];
      S.panel.pestana = siguiente.dataset.pestana;
      pintarPanel();
      siguiente.focus();
    });
  });

  // En el diálogo de renombrar, Enter guarda (el navegador activaría el primer botón: «Cancelar»)
  E.dlgTextoCampo.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && !ev.isComposing) { ev.preventDefault(); E.dlgTexto.close("si"); }
  });

  // Inicio de sesión
  document.addEventListener("sesion-caducada", mostrarLogin);
  E.btnClave.addEventListener("click", mostrarDialogoClave);
  E.btnClaveCancelar.addEventListener("click", () => E.dlgClave.close());
  E.formClave.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const clave = E.claveApi.value.trim();
    if (!clave) { E.claveError.textContent = "Pega tu clave de Gemini."; E.claveApi.focus(); return; }
    E.btnGuardarClave.disabled = true;
    E.claveError.textContent = "Comprobando la clave con Gemini…";
    try {
      await Api.guardarClave(clave);
      E.claveApi.value = "";
      E.dlgClave.close();
      avisar("Clave comprobada y guardada en este ordenador.");
      await iniciar();
    } catch (e) {
      E.claveError.textContent = e.message;
      E.claveApi.focus();
    } finally {
      E.btnGuardarClave.disabled = false;
    }
  });
  E.dlgLogin.addEventListener("cancel", (ev) => ev.preventDefault());
  E.formLogin.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const pin = E.pin.value.trim();
    if (!pin) { E.loginError.textContent = "Escribe el PIN."; E.pin.focus(); return; }
    E.btnLogin.disabled = true;
    try {
      await Api.login(pin);
      E.pin.value = "";
      E.dlgLogin.close();
      iniciar();
    } catch (e) {
      E.loginError.textContent = e.message;
      E.pin.select();
    } finally {
      E.btnLogin.disabled = false;
    }
  });

  // Teclado global: Escape cierra el panel o el menú
  document.addEventListener("keydown", (ev) => {
    if (ev.key !== "Escape" || document.querySelector("dialog[open]")) return;
    if (S.ladoAbierto) cerrarLado();
    else if (S.panel.abierto && !hayPanelFijo()) cerrarPanel();
  });

  // Arrastrar y soltar archivos
  let arrastres = 0;
  const llevaArchivos = (ev) => ev.dataTransfer && Array.from(ev.dataTransfer.types || []).includes("Files");
  window.addEventListener("dragenter", (ev) => { if (llevaArchivos(ev)) { arrastres++; E.soltar.hidden = false; } });
  window.addEventListener("dragover", (ev) => { if (llevaArchivos(ev)) ev.preventDefault(); });
  window.addEventListener("dragleave", (ev) => { if (llevaArchivos(ev) && --arrastres <= 0) { arrastres = 0; E.soltar.hidden = true; } });
  window.addEventListener("drop", (ev) => {
    if (!llevaArchivos(ev)) return;
    ev.preventDefault();
    arrastres = 0;
    E.soltar.hidden = true;
    subirArchivos(ev.dataTransfer.files);
  });

  // Conexión y pestaña en segundo plano
  window.addEventListener("offline", () => ponerPill("offline", "Sin conexión"));
  window.addEventListener("online", () => ponerPill(S.ocupado ? "trabajando" : "listo", S.ocupado ? "Trabajando…" : "Listo"));
  document.addEventListener("visibilitychange", () => { if (!document.hidden && S.ocupado && !S.sondeando) sondear(); });
}

function pintarSugerencias() {
  E.sugerencias.replaceChildren(...SUGERENCIAS.map((s) =>
    el("button", { class: "sugerencia", type: "button", onclick: () => usarSugerencia(s) },
      el("span", { class: "ic-caja", "aria-hidden": "true" }, icono(s.icono)),
      el("span", {}, el("strong", { texto: s.titulo }), el("span", { class: "desc", texto: s.desc })))));
}

async function iniciar() {
  S.chatsCargados = false;
  pintarLista();
  let estado;
  try {
    const sesion = await Api.sesion();
    if (!sesion.autenticado) { mostrarLogin(); return; }
    const configuracion = await Api.configuracion();
    if (!configuracion.clave_configurada) {
      ponerPill("offline", "Configura la clave de Gemini");
      mostrarDialogoClave();
      return;
    }
    estado = await Api.estado();
  } catch (e) {
    if (e.estado !== 401) { ponerPill("offline", "Sin conexión"); avisar(e.message, true); }
    return;
  }
  ponerPill("listo", "Listo");
  cargarChats();
  if (estado.ocupado && estado.chat_id) { // la página se recargó con el agente trabajando
    S.chatId = estado.chat_id;
    try {
      const conv = await Api.chat(S.chatId);
      S.mensajes = conv.mensajes;
      actualizarTitulo(conv.titulo);
      pintarMensajes(S.mensajes);
    } catch (_) { /* se mostrará vacío */ }
    setOcupado(true);
    mostrarPensando();
    bajar(true);
    sondear();
  } else {
    pintarMensajes(S.mensajes);
  }
}

function arrancar() {
  for (const id of ["app", "velo", "lado", "btnColapsar", "btnCerrarLado", "btnNuevo", "buscar", "lista", "btnPanelLado", "btnSalir",
    "btnMenu", "titulo", "pill", "pillTexto", "btnPanel", "conversacion", "bienvenida", "sugerencias", "mensajes", "btnFinal",
    "subida", "subidaTexto", "subidaBarra", "formulario", "btnAdjuntar", "entrada", "contador", "btnDetener", "btnEnviar", "archivo",
    "panel", "btnPanelRefrescar", "btnPanelCerrar", "cuerpoPanel", "soltar", "avisos",
    "dlgConfirmar", "dlgConfirmarTexto", "dlgTexto", "dlgTextoCampo", "dlgBorrar", "dlgBorrarTexto", "dlgLogin", "formLogin", "pin", "loginError", "btnLogin",
    "dlgClave", "formClave", "claveApi", "claveError", "btnGuardarClave", "btnClaveCancelar", "btnClave"]) {
    E[id] = $(id);
  }
  aplicarTema(memoria.leer("tema", "auto"));
  ponerColapsado(memoria.leer("colapsado", "0") === "1");
  pintarSugerencias();
  enlazarEventos();
  setOcupado(false);
  ponerPill("listo", "Conectando…");
  actualizarBienvenida();
  iniciar();
}

// Pequeño punto de acceso para pruebas automáticas del analizador de Markdown
window.__agente = { parsearMarkdown, parsearInline, urlSegura };

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", arrancar); else arrancar();

})();
"""


# ----------------------------------------------------------------------------
# Arranque
# ----------------------------------------------------------------------------

def hay_clave() -> bool:
    return bool(os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"))


def asegurar_clave() -> bool:
    """Carga una clave guardada; la interfaz permite introducirla si todavía no existe."""
    if hay_clave():
        return True
    try:
        configuracion_guardada = json.loads(CONFIG.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return False
    except (OSError, json.JSONDecodeError) as error:
        sys.stderr.write(
            f"No se pudo leer la configuración de Gemini ({error}). "
            "Puedes introducir la clave desde la aplicación web.\n"
        )
        return False
    guardada = configuracion_guardada.get("clave") if isinstance(configuracion_guardada, dict) else None
    if not isinstance(guardada, str) or not guardada.strip():
        return False
    os.environ["GOOGLE_API_KEY"] = guardada.strip()
    return True


def ip_local() -> str:
    """Dirección del ordenador dentro de tu red wifi."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))  # no envía nada: solo averigua qué red se usaría
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def preparar() -> None:
    """Carga el motor y redirige las confirmaciones al navegador."""
    global nucleo, CAPTURA, PIN
    asegurar_clave()
    if hay_clave():
        nucleo = cargar_motor()
    CARPETA_DATOS.mkdir(exist_ok=True)
    CAPTURA = Capturador(sys.stdout)
    sys.stdout = CAPTURA
    builtins.input = input_web
    PIN = obtener_pin()
    app.secret_key = leer_o_crear("secreto_web.key", lambda: secrets.token_hex(32))


PIN = ""

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inicia el agente personal en el navegador.")
    parser.add_argument(
        "--movil",
        action="store_true",
        help="Permite conexiones desde otros dispositivos de la red local (protegido por PIN).",
    )
    args = parser.parse_args()

    preparar()
    host = "0.0.0.0" if args.movil else "127.0.0.1"
    sys.stdout.real.write(
        "\n" + "=" * 58 + "\n"
        "  Agente personal - versión web\n"
        f"  En este ordenador:  http://localhost:{PUERTO}\n"
    )
    if args.movil:
        sys.stdout.real.write(f"  En el móvil (misma wifi):  http://{ip_local()}:{PUERTO}\n")
    sys.stdout.real.write(
        f"  PIN de acceso:  {PIN}\n"
        "  Para cerrar el programa pulsa Ctrl+C\n"
        + "=" * 58 + "\n\n"
    )
    app.run(host=host, port=PUERTO, threaded=True)
