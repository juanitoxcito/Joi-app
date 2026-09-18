"""
Joi -- app nativa Android (Fase 1).
Mismo motor del bot_joi.py (SQLite, estrategias, deudas, gastos fijos, etc.)
pero sin Telegram: la pantalla se redibuja en el sitio, como si "editar()"
del bot ahora dibujara directo en la app en vez de mandar un mensaje.

Base de datos en blanco -- Juan carga sus cuentas/deudas/gastos desde cero.
"""
import sqlite3
import time
from math import ceil
from datetime import datetime, timedelta, timezone

import os
import requests
from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.widget import Widget
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.metrics import dp
from kivy.core.window import Window
from kivy.core.text import LabelBase
from kivy.core.audio import SoundLoader
from kivy.graphics import Color, Rectangle, RoundedRectangle

# ==================== TEMA VISUAL (navy + morado, fuente Poppins) ====================
COLOR_FONDO = (0.06, 0.07, 0.13, 1)
COLOR_PANEL = (0.11, 0.12, 0.22, 1)
COLOR_PANEL_CLARO = (0.15, 0.16, 0.28, 1)
COLOR_MORADO = (0.58, 0.40, 0.98, 1)
COLOR_MORADO_OSCURO = (0.30, 0.20, 0.55, 1)
COLOR_MORADO_SUAVE = (0.40, 0.28, 0.70, 1)
COLOR_TEXTO = (0.95, 0.95, 0.98, 1)
COLOR_TEXTO_TENUE = (0.65, 0.65, 0.75, 1)
Window.clearcolor = COLOR_FONDO

_FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "fonts")
LabelBase.register(name="Poppins",
                    fn_regular=os.path.join(_FONT_DIR, "Poppins-Regular.ttf"),
                    fn_bold=os.path.join(_FONT_DIR, "Poppins-Bold.ttf"))
LabelBase.register(name="PoppinsSemiBold", fn_regular=os.path.join(_FONT_DIR, "Poppins-SemiBold.ttf"))
LabelBase.register(name="PoppinsMedium", fn_regular=os.path.join(_FONT_DIR, "Poppins-Medium.ttf"))
LabelBase.register(name="DSEG7", fn_regular=os.path.join(_FONT_DIR, "DSEG7Classic-Bold.ttf"))

# ==================== SONIDOS ====================
_SOUND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "sounds")
_SONIDOS = {}


def _cargar_sonido(nombre):
    # Los archivos quedaron con inicial mayúscula al subirlos desde el teléfono
    # (Click.wav, Exito.wav, Borrar.wav) -- se respeta ese nombre tal cual.
    ruta = os.path.join(_SOUND_DIR, f"{nombre.capitalize()}.wav")
    if nombre not in _SONIDOS:
        _SONIDOS[nombre] = SoundLoader.load(ruta)
    return _SONIDOS[nombre]


def sonido(nombre):
    """Reproduce un efecto: 'click' (toque de botón), 'exito' (acción completada
    con bien: registrar, guardar, confirmar) o 'borrar' (eliminar algo)."""
    s = _cargar_sonido(nombre)
    if s:
        s.stop()
        s.play()

DB_PATH = "joi.db"
UTC_MENOS_4 = timezone(timedelta(hours=-4))

MESES_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
            "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
DIAS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
DIAS_SEMANA = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
CATEGORIAS_GASTO = ["Comida", "Combustible", "Otro"]
CATEGORIAS_INGRESO = ["Ingreso", "Retorno de saldo"]

ESTRATEGIAS = {
    "speed":  {"fase1": (0.30, 0.55, 0.15), "fase2": (0.65, 0.20, 0.15)},
    "medium": {"fase1": (0.50, 0.35, 0.15), "fase2": (0.50, 0.30, 0.20)},
    "live":   {"fase1": (0.40, 0.20, 0.40), "fase2": (0.20, 0.20, 0.60)},
}


def fecha_larga_es(dt):
    return f"{DIAS_ES[dt.weekday()]} {dt.day} de {MESES_ES[dt.month - 1]} del {dt.year}"


def saludo():
    ahora = datetime.now(UTC_MENOS_4)
    momento = "días" if ahora.hour < 12 else ("tardes" if ahora.hour < 19 else "noches")
    return f"¡Buenos {momento} Juan! Son las {ahora.strftime('%I:%M %p')} y estamos a {fecha_larga_es(ahora)}."


# ==================== BASE DE DATOS ====================

def iniciar_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""CREATE TABLE IF NOT EXISTS cuentas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL UNIQUE,
        grupo TEXT NOT NULL, saldo REAL NOT NULL DEFAULT 0,
        moneda TEXT NOT NULL, ultima_confirmacion TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS movimientos (
        id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT NOT NULL, tipo TEXT NOT NULL,
        monto REAL NOT NULL, moneda TEXT NOT NULL, monto_usdt REAL NOT NULL,
        categoria TEXT NOT NULL, cuenta_id INTEGER NOT NULL)""")
    con.execute("""CREATE TABLE IF NOT EXISTS deudas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL, monto_total REAL NOT NULL,
        monto_pagado REAL NOT NULL DEFAULT 0, moneda TEXT NOT NULL DEFAULT 'USDT',
        interes_mensual REAL NOT NULL DEFAULT 0, fecha_limite TEXT,
        estado TEXT NOT NULL DEFAULT 'activa', ultimo_aviso_fecha TEXT,
        tipo_pago TEXT NOT NULL DEFAULT 'unico', monto_cuota REAL, dia_pago INTEGER,
        ultimo_interes_fecha TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS pagos_mensuales (
        id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL, monto REAL NOT NULL,
        moneda TEXT NOT NULL, frecuencia TEXT NOT NULL DEFAULT 'mensual', dia_vence INTEGER,
        dia_semana INTEGER, recargo REAL NOT NULL DEFAULT 0, cuenta_id INTEGER, categoria TEXT,
        prioridad INTEGER NOT NULL DEFAULT 3, activo INTEGER NOT NULL DEFAULT 1,
        ultimo_aviso_fecha TEXT, ultima_fecha_registrada TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS por_cobrar (
        id INTEGER PRIMARY KEY AUTOINCREMENT, tipo TEXT NOT NULL, monto_original REAL NOT NULL,
        monto_pendiente REAL NOT NULL, moneda TEXT NOT NULL, descripcion TEXT NOT NULL,
        cuenta_origen_id INTEGER, estado TEXT NOT NULL DEFAULT 'pendiente', fecha TEXT NOT NULL)""")
    con.execute("""CREATE TABLE IF NOT EXISTS recordatorio_ajustes (
        tipo TEXT NOT NULL, item_id INTEGER NOT NULL, dias_antes INTEGER NOT NULL DEFAULT 3,
        PRIMARY KEY (tipo, item_id))""")
    con.execute("""CREATE TABLE IF NOT EXISTS objetivos (
        id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL, monto_meta REAL NOT NULL,
        monto_actual REAL NOT NULL DEFAULT 0, moneda TEXT NOT NULL DEFAULT 'USDT',
        fecha_limite TEXT, estado TEXT NOT NULL DEFAULT 'activo')""")
    con.execute("""CREATE TABLE IF NOT EXISTS deuda_pagos (
        id INTEGER PRIMARY KEY AUTOINCREMENT, deuda_id INTEGER NOT NULL,
        monto REAL NOT NULL, fecha TEXT NOT NULL)""")
    con.execute("""CREATE TABLE IF NOT EXISTS config_estrategia (
        id INTEGER PRIMARY KEY CHECK (id=1), colchon_meta REAL NOT NULL DEFAULT 150,
        colchon_actual REAL NOT NULL DEFAULT 0, estrategia_activa TEXT NOT NULL DEFAULT 'medium')""")
    if con.execute("SELECT COUNT(*) FROM config_estrategia").fetchone()[0] == 0:
        con.execute("INSERT INTO config_estrategia (id, colchon_meta, colchon_actual) VALUES (1, 150, 0)")
    columnas_config = {f[1] for f in con.execute("PRAGMA table_info(config_estrategia)").fetchall()}
    if "hora_manana" not in columnas_config:
        con.execute("ALTER TABLE config_estrategia ADD COLUMN hora_manana TEXT")
    if "hora_mediodia" not in columnas_config:
        con.execute("ALTER TABLE config_estrategia ADD COLUMN hora_mediodia TEXT")
    if "hora_noche" not in columnas_config:
        con.execute("ALTER TABLE config_estrategia ADD COLUMN hora_noche TEXT")
    con.execute("""CREATE TABLE IF NOT EXISTS config_sueldo (
        id INTEGER PRIMARY KEY CHECK (id=1), activo INTEGER NOT NULL DEFAULT 0,
        frecuencia TEXT, monto REAL, moneda TEXT, cuenta_id INTEGER,
        dia_semana INTEGER, dia_mes INTEGER, ultima_confirmacion TEXT)""")
    if con.execute("SELECT COUNT(*) FROM config_sueldo").fetchone()[0] == 0:
        con.execute("INSERT INTO config_sueldo (id, activo) VALUES (1, 0)")
    columnas_sueldo = {f[1] for f in con.execute("PRAGMA table_info(config_sueldo)").fetchall()}
    if "cuenta_origen_id" not in columnas_sueldo:
        con.execute("ALTER TABLE config_sueldo ADD COLUMN cuenta_origen_id INTEGER")
    con.commit()
    return con


def conectar():
    return sqlite3.connect(DB_PATH)


def dias_antes_de(con, tipo, item_id):
    fila = con.execute("SELECT dias_antes FROM recordatorio_ajustes WHERE tipo=? AND item_id=?", (tipo, item_id)).fetchone()
    return fila[0] if fila else 3


# ==================== TASAS Y CONVERSIÓN ====================

_cache_tasas = {"valor": None, "ts": 0}


def obtener_tasas():
    ahora = time.time()
    if _cache_tasas["valor"] and ahora - _cache_tasas["ts"] < 3600:
        return _cache_tasas["valor"]
    try:
        paralelo = requests.get("https://ve.dolarapi.com/v1/dolares/paralelo", timeout=4).json()
        tasas = {"paralelo": paralelo["promedio"]}
        _cache_tasas["valor"] = tasas
        _cache_tasas["ts"] = ahora
        return tasas
    except Exception:
        return _cache_tasas["valor"] or {"paralelo": 1}


def convertir_a_usdt(monto, moneda):
    moneda = (moneda or "USD").upper()
    if moneda in ("USD", "USDT"):
        return monto
    if moneda in ("VES", "BS"):
        return monto / obtener_tasas()["paralelo"]
    return monto


def convertir_de_usdt(monto_usdt, moneda):
    moneda = (moneda or "USD").upper()
    if moneda in ("USD", "USDT"):
        return monto_usdt
    if moneda in ("VES", "BS"):
        return monto_usdt * obtener_tasas()["paralelo"]
    return monto_usdt


def parsear_monto(texto):
    limpio = texto.strip().replace(",", "")
    return float(limpio)


def sumar_meses(fecha, n):
    mes_total = fecha.month - 1 + n
    anio = fecha.year + mes_total // 12
    mes = mes_total % 12 + 1
    dia = min(fecha.day, 28)
    return fecha.replace(year=anio, month=mes, day=dia)


# ==================== ESTATUS Y ESTRATEGIA ====================

def listar_cuentas_simples():
    con = conectar()
    filas = con.execute("SELECT id, nombre FROM cuentas ORDER BY id").fetchall()
    con.close()
    return [{"id": f[0], "nombre": f[1]} for f in filas]


def pedir_cuenta(texto_pregunta, prefijo, excluir_id=None):
    """Muestra la lista de cuentas para elegir (con el prefijo de callback dado).
    Si no hay ninguna cuenta todavía, avisa en vez de mostrar una pantalla vacía."""
    cuentas = listar_cuentas_simples()
    if excluir_id is not None:
        cuentas = [c for c in cuentas if c["id"] != excluir_id]
    if not cuentas:
        render("No tienes ninguna cuenta creada todavía. Ve a Menú > Saldo > Anexar para crear una primero.",
               [[("Menú", "menu:main")]])
        return
    filas = [[(c["nombre"], f"{prefijo}{c['id']}")] for c in cuentas]
    render(texto_pregunta, filas)


def calcular_costo_semanal_usdt(con):
    total = 0.0
    for monto, moneda, frecuencia in con.execute(
            "SELECT monto, moneda, frecuencia FROM pagos_mensuales WHERE activo=1").fetchall():
        usdt = convertir_a_usdt(monto, moneda)
        if frecuencia == "diario":
            total += usdt * 7
        elif frecuencia == "semanal":
            total += usdt
        else:
            total += usdt / 4.33
    fila_sueldo = con.execute(
        "SELECT activo, frecuencia, monto, moneda, cuenta_origen_id FROM config_sueldo WHERE id=1").fetchone()
    if fila_sueldo:
        s_activo, s_frecuencia, s_monto, s_moneda, s_cuenta_origen_id = fila_sueldo
        if s_activo and s_cuenta_origen_id and s_monto:
            s_usdt = convertir_a_usdt(s_monto, s_moneda)
            if s_frecuencia == "diario":
                total += s_usdt * 7
            elif s_frecuencia == "semanal":
                total += s_usdt
            elif s_frecuencia == "mensual":
                total += s_usdt / 4.33
    return total


def estatus_calcular(con):
    saldo_total_usdt = sum(
        convertir_a_usdt(s, m) for _, s, m in con.execute("SELECT nombre, saldo, moneda FROM cuentas").fetchall())
    costo_semanal = calcular_costo_semanal_usdt(con)
    if costo_semanal <= 0:
        return {"saldo_total_usdt": round(saldo_total_usdt, 2), "costo_semanal_usdt": 0,
                "semanas_cobertura": None, "estado": "Sin gastos fijos",
                "faltante_saludable": 0, "faltante_optimo": 0}
    semanas = saldo_total_usdt / costo_semanal
    if semanas < 1:
        estado = "Crítico"
    elif semanas < 4:
        estado = "Saludable"
    else:
        estado = "Óptimo"
    faltante_saludable = max(round(costo_semanal - saldo_total_usdt, 2), 0) if semanas < 1 else 0
    faltante_optimo = max(round(costo_semanal * 4 - saldo_total_usdt, 2), 0) if semanas < 4 else 0
    return {"saldo_total_usdt": round(saldo_total_usdt, 2), "costo_semanal_usdt": round(costo_semanal, 2),
            "semanas_cobertura": round(semanas, 1),
            "estado": estado, "faltante_saludable": faltante_saludable, "faltante_optimo": faltante_optimo}


def calcular_deuda_mayor_interes(con):
    return con.execute(
        "SELECT id, nombre, monto_total, monto_pagado, moneda FROM deudas WHERE estado='activa' "
        "ORDER BY interes_mensual DESC LIMIT 1").fetchone()


def calcular_objetivo_activo(con):
    return con.execute(
        "SELECT id, nombre, monto_meta, monto_actual, moneda FROM objetivos WHERE estado='activo' "
        "ORDER BY (fecha_limite IS NULL), fecha_limite ASC, id ASC LIMIT 1").fetchone()


def aplicar_estrategia_ingreso(con, monto_usdt):
    cfg = con.execute("SELECT colchon_meta, colchon_actual, estrategia_activa FROM config_estrategia WHERE id=1").fetchone()
    colchon_meta, colchon_actual, estrategia_activa = cfg
    lineas = []
    estatus_actual = estatus_calcular(con)["estado"]
    if estatus_actual == "Crítico" and estrategia_activa != "live":
        estrategia_usar = "live"
        lineas.append("(Estatus Crítico -- se usó LIVE en vez de tu estrategia elegida para protegerte)")
    else:
        estrategia_usar = estrategia_activa
    tabla = ESTRATEGIAS.get(estrategia_usar, ESTRATEGIAS["medium"])
    if colchon_actual < colchon_meta:
        pct_colchon, pct_deuda, pct_libre = tabla["fase1"]
        pct_ahorro = 0.0
    else:
        pct_deuda, pct_ahorro, pct_libre = tabla["fase2"]
        pct_colchon = 0.0
    monto_colchon = round(monto_usdt * pct_colchon, 2)
    monto_deuda = round(monto_usdt * pct_deuda, 2)
    monto_ahorro = round(monto_usdt * pct_ahorro, 2)
    monto_libre = round(monto_usdt * pct_libre, 2)
    if monto_colchon:
        nuevo_colchon = round(colchon_actual + monto_colchon, 2)
        con.execute("UPDATE config_estrategia SET colchon_actual=? WHERE id=1", (nuevo_colchon,))
        lineas.append(f"Colchón: +{monto_colchon} (ahora {nuevo_colchon} de {colchon_meta})")
    deuda = calcular_deuda_mayor_interes(con)
    if deuda and monto_deuda:
        deuda_id, deuda_nombre, deuda_total, deuda_pagado, deuda_moneda = deuda
        monto_deuda_en_su_moneda = round(convertir_de_usdt(monto_deuda, deuda_moneda), 2)
        nuevo_pagado = min(deuda_pagado + monto_deuda_en_su_moneda, deuda_total)
        con.execute("UPDATE deudas SET monto_pagado=? WHERE id=?", (nuevo_pagado, deuda_id))
        con.execute("INSERT INTO deuda_pagos (deuda_id, monto, fecha) VALUES (?, ?, ?)",
                    (deuda_id, monto_deuda_en_su_moneda, datetime.now(UTC_MENOS_4).isoformat()))
        if nuevo_pagado >= deuda_total:
            con.execute("UPDATE deudas SET estado='pagada' WHERE id=?", (deuda_id,))
            lineas.append(f"Deuda '{deuda_nombre}': +{monto_deuda_en_su_moneda} {deuda_moneda} -- ¡saldada!")
        else:
            lineas.append(f"Deuda '{deuda_nombre}' (mayor interés): +{monto_deuda_en_su_moneda} {deuda_moneda} "
                          f"(falta {round(deuda_total - nuevo_pagado, 2)} {deuda_moneda})")
    elif monto_deuda:
        monto_libre += monto_deuda
    objetivo = calcular_objetivo_activo(con)
    if objetivo and monto_ahorro:
        obj_id, obj_nombre, obj_meta, obj_actual, obj_moneda = objetivo
        monto_ahorro_en_su_moneda = round(convertir_de_usdt(monto_ahorro, obj_moneda), 2)
        nuevo_actual = min(obj_actual + monto_ahorro_en_su_moneda, obj_meta)
        con.execute("UPDATE objetivos SET monto_actual=? WHERE id=?", (nuevo_actual, obj_id))
        if nuevo_actual >= obj_meta:
            con.execute("UPDATE objetivos SET estado='cumplido' WHERE id=?", (obj_id,))
            lineas.append(f"Objetivo '{obj_nombre}': +{monto_ahorro_en_su_moneda} {obj_moneda} -- ¡cumplido!")
        else:
            lineas.append(f"Objetivo '{obj_nombre}': +{monto_ahorro_en_su_moneda} {obj_moneda} "
                          f"(falta {round(obj_meta - nuevo_actual, 2)} {obj_moneda})")
    elif monto_ahorro:
        monto_libre += monto_ahorro
    lineas.append(f"Libre: +{round(monto_libre, 2)}")
    con.commit()
    return lineas


# ==================== NOTIFICACIONES (Android) ====================

def mostrar_notificacion(titulo, mensaje):
    """Muestra una notificación nativa de Android. Deja que la excepción suba
    (no la esconde) para que quien la llama pueda mostrar el error real."""
    from jnius import autoclass
    PythonActivity = autoclass("org.kivy.android.PythonActivity")
    Context = autoclass("android.content.Context")
    NotificationManager = autoclass("android.app.NotificationManager")
    NotificationChannel = autoclass("android.app.NotificationChannel")
    NotificationBuilder = autoclass("android.app.Notification$Builder")
    BuildVersion = autoclass("android.os.Build$VERSION")

    activity = PythonActivity.mActivity
    servicio = activity.getSystemService(Context.NOTIFICATION_SERVICE)
    canal_id = "joi_canal"
    if BuildVersion.SDK_INT >= 26:
        canal = NotificationChannel(canal_id, "Joi", NotificationManager.IMPORTANCE_HIGH)
        servicio.createNotificationChannel(canal)
        builder = NotificationBuilder(activity, canal_id)
    else:
        builder = NotificationBuilder(activity)
    builder.setContentTitle(titulo)
    builder.setContentText(mensaje)
    builder.setSmallIcon(activity.getApplicationInfo().icon)
    builder.setAutoCancel(True)
    servicio.notify(1, builder.build())


def probar_notificacion():
    try:
        from android.permissions import request_permissions, check_permission, Permission
        if check_permission(Permission.POST_NOTIFICATIONS):
            mostrar_notificacion("Joi", "¡Notificación de prueba! Si ves esto, funciona.")
            render("Notificación enviada -- revisa la barra de notificaciones.", [[("Menú", "menu:main")]])
            return

        def _tras_permiso(permisos, resultados):
            if resultados and resultados[0]:
                mostrar_notificacion("Joi", "¡Notificación de prueba! Si ves esto, funciona.")
                render("Permiso concedido y notificación enviada -- revisa la barra de notificaciones.",
                       [[("Menú", "menu:main")]])
            else:
                render("No diste el permiso de notificaciones -- Joi no podrá avisarte más adelante. "
                       "Puedes activarlo luego en Ajustes > Apps > Joi > Notificaciones.",
                       [[("Menú", "menu:main")]])

        request_permissions([Permission.POST_NOTIFICATIONS], _tras_permiso)
        render("Pidiendo permiso de notificaciones...", [])
    except Exception as e:
        import traceback
        detalle = traceback.format_exc()
        render(f"ERROR al probar notificación:\n\n{type(e).__name__}: {e}\n\n{detalle[-600:]}",
               [[("Menú", "menu:main")]])


# ==================== ALARMAS PROGRAMADAS (Android AlarmManager) ====================

NOMBRE_PAQUETE_SERVICIO = None  # se calcula solo, ver _nombre_clase_servicio()


def _nombre_clase_servicio():
    """Nombre completo (paquete + clase) del servicio Java que Android genera
    automáticamente a partir de 'services = joialarm:service.py' en buildozer.spec."""
    from jnius import autoclass
    PythonActivity = autoclass("org.kivy.android.PythonActivity")
    activity = PythonActivity.mActivity
    paquete = activity.getPackageName()
    return f"{paquete}.ServiceJoialarm"


def programar_alarma(slot, hora_str):
    """Programa (o reprograma) la alarma diaria de un turno ('manana', 'mediodia'
    o 'noche') a la hora dada (texto 'HH:MM'). Se dispara aunque la app esté cerrada."""
    from jnius import autoclass
    PythonActivity = autoclass("org.kivy.android.PythonActivity")
    Context = autoclass("android.content.Context")
    AlarmManager = autoclass("android.app.AlarmManager")
    PendingIntent = autoclass("android.app.PendingIntent")
    Calendar = autoclass("java.util.Calendar")
    ServiceJoialarm = autoclass(_nombre_clase_servicio())

    activity = PythonActivity.mActivity
    intent = ServiceJoialarm.getDefaultIntent(activity, "", "Joi", "Aviso programado", slot)
    codigo_peticion = {"manana": 100, "mediodia": 101, "noche": 102}[slot]
    flags = PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
    pendiente = PendingIntent.getService(activity, codigo_peticion, intent, flags)

    hh, mm = map(int, hora_str.split(":"))
    ahora = Calendar.getInstance()
    objetivo = Calendar.getInstance()
    objetivo.set(Calendar.HOUR_OF_DAY, hh)
    objetivo.set(Calendar.MINUTE, mm)
    objetivo.set(Calendar.SECOND, 0)
    objetivo.set(Calendar.MILLISECOND, 0)
    if objetivo.getTimeInMillis() <= ahora.getTimeInMillis():
        objetivo.add(Calendar.DAY_OF_MONTH, 1)

    gestor_alarmas = activity.getSystemService(Context.ALARM_SERVICE)
    gestor_alarmas.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, objetivo.getTimeInMillis(), pendiente)


def programar_todas_las_alarmas(mostrar_error_en_pantalla=False):
    try:
        con = conectar()
        fila = con.execute(
            "SELECT hora_manana, hora_mediodia, hora_noche FROM config_estrategia WHERE id=1").fetchone()
        con.close()
        hora_manana, hora_mediodia, hora_noche = fila
        if hora_manana:
            programar_alarma("manana", hora_manana)
        if hora_mediodia:
            programar_alarma("mediodia", hora_mediodia)
        if hora_noche:
            programar_alarma("noche", hora_noche)
    except Exception as e:
        if mostrar_error_en_pantalla:
            import traceback
            detalle = traceback.format_exc()
            render(f"ERROR al programar las alarmas:\n\n{type(e).__name__}: {e}\n\n{detalle[-600:]}",
                   [[("Menú", "menu:main")]])
        else:
            print(f"[ALARMAS] No se pudieron programar (¿no es Android?): {e}")


# ==================== MÓDULO: SUELDO ====================

def sueldo_pendiente_hoy(con):
    fila = con.execute(
        "SELECT activo, frecuencia, dia_semana, dia_mes, ultima_confirmacion FROM config_sueldo WHERE id=1").fetchone()
    if not fila or not fila[0]:
        return False
    _, frecuencia, dia_semana, dia_mes, ultima_confirmacion = fila
    hoy = datetime.now(UTC_MENOS_4)
    if ultima_confirmacion == hoy.strftime("%Y-%m-%d"):
        return False
    if frecuencia == "diario":
        return True
    if frecuencia == "semanal":
        return hoy.weekday() == dia_semana
    if frecuencia == "mensual":
        return hoy.day == dia_mes
    return False


def sueldo_confirmar_prompt():
    con = conectar()
    monto, moneda = con.execute("SELECT monto, moneda FROM config_sueldo WHERE id=1").fetchone()
    con.close()
    render(f"¿Transferiste tus {monto} {moneda} del sueldo hoy?",
           [[("Sí, completo", "sueldo:confirmar:si"), ("No", "sueldo:confirmar:no")],
            [("Otra cantidad (reciclaje)", "sueldo:confirmar:editar")]])


def sueldo_confirmar_callback(respuesta):
    con = conectar()
    hoy_str = datetime.now(UTC_MENOS_4).strftime("%Y-%m-%d")
    if respuesta == "no":
        con.execute("UPDATE config_sueldo SET ultima_confirmacion=? WHERE id=1", (hoy_str,))
        con.commit()
        con.close()
        render("Entendido, no se registró nada. Te preguntaré de nuevo el próximo día que toque.",
               [[("Menú", "menu:main")]])
        return
    if respuesta == "editar":
        con.close()
        iniciar_flujo("sueldo_editar_monto_dia", "monto", {})
        render("¿Cuánto vas a transferir hoy? (usa un monto menor si estás reciclando saldo del día anterior, "
               "o 0 si no vas a transferir nada)", pedir_texto=True, teclado_numero=True)
        return
    monto, moneda, cuenta_id, cuenta_origen_id = con.execute(
        "SELECT monto, moneda, cuenta_id, cuenta_origen_id FROM config_sueldo WHERE id=1").fetchone()
    con.close()
    ESTADO["datos"] = {"monto": monto, "moneda": moneda, "cuenta_destino_id": cuenta_id}
    sueldo_aplicar(cuenta_origen_id)


def sueldo_editar_monto_dia_texto(texto):
    try:
        monto_dia = parsear_monto(texto)
    except ValueError:
        render("Escribe solo el número.", pedir_texto=True, teclado_numero=True)
        return
    if monto_dia < 0:
        render("El monto no puede ser negativo.", pedir_texto=True, teclado_numero=True)
        return
    con = conectar()
    moneda, cuenta_id, cuenta_origen_id = con.execute(
        "SELECT moneda, cuenta_id, cuenta_origen_id FROM config_sueldo WHERE id=1").fetchone()
    con.close()
    ESTADO["datos"] = {"monto": monto_dia, "moneda": moneda, "cuenta_destino_id": cuenta_id}
    sueldo_aplicar(cuenta_origen_id)


def sueldo_aplicar(cuenta_origen_id):
    d = ESTADO["datos"]
    con = conectar()
    hoy_str = datetime.now(UTC_MENOS_4).strftime("%Y-%m-%d")
    cuenta_destino = con.execute("SELECT nombre, saldo, moneda FROM cuentas WHERE id=?",
                                 (d["cuenta_destino_id"],)).fetchone()
    if not cuenta_destino:
        con.close()
        render("La cuenta configurada para el sueldo ya no existe. Ve a Sueldo para elegir otra.",
               [[("Menú", "menu:main")]])
        return
    monto_usdt = convertir_a_usdt(d["monto"], d["moneda"])
    ahora = datetime.now(UTC_MENOS_4).isoformat()
    delta_destino_moneda = monto_usdt * obtener_tasas()["paralelo"] if cuenta_destino[2] == "VES" else monto_usdt
    nuevo_saldo_destino = cuenta_destino[1] + delta_destino_moneda
    con.execute("UPDATE cuentas SET saldo=? WHERE id=?", (nuevo_saldo_destino, d["cuenta_destino_id"]))
    con.execute("INSERT INTO movimientos (fecha, tipo, monto, moneda, monto_usdt, categoria, cuenta_id) "
                "VALUES (?,?,?,?,?,?,?)",
                (ahora, "ingreso", d["monto"], d["moneda"], monto_usdt, "Ingreso", d["cuenta_destino_id"]))
    texto_origen = ""
    if cuenta_origen_id:
        cuenta_origen = con.execute("SELECT nombre, saldo, moneda FROM cuentas WHERE id=?",
                                    (cuenta_origen_id,)).fetchone()
        delta_origen_moneda = monto_usdt * obtener_tasas()["paralelo"] if cuenta_origen[2] == "VES" else monto_usdt
        nuevo_saldo_origen = cuenta_origen[1] - delta_origen_moneda
        con.execute("UPDATE cuentas SET saldo=? WHERE id=?", (nuevo_saldo_origen, cuenta_origen_id))
        con.execute("INSERT INTO movimientos (fecha, tipo, monto, moneda, monto_usdt, categoria, cuenta_id) "
                    "VALUES (?,'gasto',?,?,?,?,?)",
                    (ahora, round(delta_origen_moneda, 2), cuenta_origen[2], monto_usdt, "Transferencia",
                     cuenta_origen_id))
        texto_origen = f" (salió de {cuenta_origen[0]}, nuevo saldo {round(nuevo_saldo_origen, 2)} {cuenta_origen[2]})"
    lineas_estrategia = aplicar_estrategia_ingreso(con, monto_usdt)
    con.execute("UPDATE config_sueldo SET ultima_confirmacion=? WHERE id=1", (hoy_str,))
    con.commit()
    con.close()
    terminar_flujo()
    texto = (f"Sueldo registrado: {d['monto']} {d['moneda']} en {cuenta_destino[0]}{texto_origen}.\n"
             f"Nuevo saldo {cuenta_destino[0]}: {round(nuevo_saldo_destino, 2)} {cuenta_destino[2]}")
    if lineas_estrategia:
        texto += "\n\nRepartido según tu estrategia:\n" + "\n".join(lineas_estrategia)
    sonido("exito")
    render(texto, [[("Menú", "menu:main")]])


def sueldo_menu():
    con = conectar()
    fila = con.execute(
        "SELECT activo, frecuencia, monto, moneda, cuenta_id, dia_semana, dia_mes, cuenta_origen_id "
        "FROM config_sueldo WHERE id=1"
    ).fetchone()
    activo, frecuencia, monto, moneda, cuenta_id, dia_semana, dia_mes, cuenta_origen_id = fila
    if not activo:
        texto = "El sueldo no está configurado."
    else:
        cuenta = con.execute("SELECT nombre FROM cuentas WHERE id=?", (cuenta_id,)).fetchone()
        cuenta_nombre = cuenta[0] if cuenta else "cuenta eliminada"
        extra = f", cada {DIAS_SEMANA[dia_semana]}" if frecuencia == "semanal" else \
            (f", día {dia_mes}" if frecuencia == "mensual" else "")
        if cuenta_origen_id:
            origen = con.execute("SELECT nombre FROM cuentas WHERE id=?", (cuenta_origen_id,)).fetchone()
            origen_texto = f", sale de {origen[0]}" if origen else ", sale de una cuenta eliminada"
        else:
            origen_texto = ", de fuente externa"
        texto = f"Sueldo configurado: {monto} {moneda} ({frecuencia}{extra}) -> {cuenta_nombre}{origen_texto}"
    con.close()
    filas = [[("Configurar/Editar", "sueldo:config:frecuencia")]]
    if activo:
        filas.append([("Confirmar ahora", "sueldo:confirmarahora")])
        filas.append([("Desactivar", "sueldo:desactivar")])
    filas.append([("Volver", "menu:saldo")])
    render(texto, filas)


def sueldo_config_frecuencia():
    render("¿Cada cuánto te pagan?",
           [[("Diario", "sueldo:frecuencia:diario"), ("Semanal", "sueldo:frecuencia:semanal"),
             ("Mensual", "sueldo:frecuencia:mensual")]])


def sueldo_frecuencia_callback(frecuencia):
    iniciar_flujo("sueldo_config", "monto", {"frecuencia": frecuencia})
    render("¿Cuánto es el sueldo?", pedir_texto=True, teclado_numero=True)


def sueldo_config_texto(texto):
    d = ESTADO["datos"]
    if ESTADO["paso"] == "monto":
        try:
            d["monto"] = parsear_monto(texto)
        except ValueError:
            render("Escribe solo el número.", pedir_texto=True, teclado_numero=True)
            return
        ESTADO["paso"] = "moneda"
        render("¿Moneda?", [[("USD", "sueldo:moneda:USD"), ("USDT", "sueldo:moneda:USDT"), ("VES", "sueldo:moneda:VES")]])
        return
    if ESTADO["paso"] == "dia_mes":
        try:
            dia = int(texto.strip())
            assert 1 <= dia <= 31
        except (ValueError, AssertionError):
            render("Escribe un número de día válido (1-31).", pedir_texto=True, teclado_numero=True)
            return
        d["dia_mes"] = dia
        ESTADO["paso"] = "cuenta"
        pedir_cuenta("¿A qué cuenta entra?", "sueldo:cuenta:")
        return


def sueldo_moneda_callback(moneda):
    d = ESTADO["datos"]
    d["moneda"] = moneda
    if d["frecuencia"] == "semanal":
        ESTADO["paso"] = "dia_semana"
        filas = [[(dd, f"sueldo:diasemana:{i}")] for i, dd in enumerate(DIAS_SEMANA)]
        render("¿Qué día de la semana?", filas)
    elif d["frecuencia"] == "mensual":
        ESTADO["paso"] = "dia_mes"
        render("¿Qué día del mes? (1-31)", pedir_texto=True, teclado_numero=True)
    else:
        ESTADO["paso"] = "cuenta"
        pedir_cuenta("¿A qué cuenta entra?", "sueldo:cuenta:")


def sueldo_diasemana_callback(dia_semana):
    ESTADO["datos"]["dia_semana"] = dia_semana
    ESTADO["paso"] = "cuenta"
    pedir_cuenta("¿A qué cuenta entra?", "sueldo:cuenta:")


def sueldo_cuenta_callback(cuenta_id):
    d = ESTADO["datos"]
    d["cuenta_id"] = cuenta_id
    render("¿De qué cuenta sale ese dinero, o es de fuente externa?",
           [[("Cuenta interna", "sueldo:configorigen:interna"), ("Externa", "sueldo:configorigen:externa")]])


def sueldo_config_origen_callback(tipo):
    if tipo == "externa":
        sueldo_config_guardar(None)
        return
    d = ESTADO["datos"]
    filas = [[(c["nombre"], f"sueldo:configorigeninterno:{c['id']}")]
             for c in listar_cuentas_simples() if c["id"] != d["cuenta_id"]]
    if not filas:
        render("No tienes otra cuenta de dónde elegir -- se guardará como externa.", [])
        sueldo_config_guardar(None)
        return
    render("¿De cuál de tus cuentas sale?", filas)


def sueldo_config_guardar(cuenta_origen_id):
    d = ESTADO["datos"]
    con = conectar()
    con.execute("UPDATE config_sueldo SET activo=1, frecuencia=?, monto=?, moneda=?, cuenta_id=?, "
                "dia_semana=?, dia_mes=?, cuenta_origen_id=?, ultima_confirmacion=NULL WHERE id=1",
                (d["frecuencia"], d["monto"], d["moneda"], d["cuenta_id"], d.get("dia_semana"),
                 d.get("dia_mes"), cuenta_origen_id))
    con.commit()
    con.close()
    terminar_flujo()
    sonido("exito")
    extra = " Esto también se contará como un gasto fijo recurrente al calcular tu Estatus." if cuenta_origen_id else ""
    render(f"Sueldo configurado. Te preguntaré en el check-in de la mañana cuando corresponda.{extra}",
           [[("Menú", "menu:main")]])


def sueldo_confirmar_ahora():
    sueldo_confirmar_prompt()


def sueldo_desactivar():
    con = conectar()
    con.execute("UPDATE config_sueldo SET activo=0 WHERE id=1")
    con.commit()
    con.close()
    render("Sueldo desactivado.", [[("Menú", "menu:main")]])


# ==================== PANTALLA: HORARIOS DE AVISOS ====================

def _hora24_a_texto12(hora24):
    """Convierte 'HH:MM' (24h) a texto '7:30 AM' para mostrar. None -> 'Sin configurar'."""
    if not hora24:
        return "Sin configurar"
    hh, mm = map(int, hora24.split(":"))
    periodo = "AM" if hh < 12 else "PM"
    hh12 = hh % 12
    if hh12 == 0:
        hh12 = 12
    return f"{hh12}:{mm:02d} {periodo}"


def horarios_menu():
    con = conectar()
    fila = con.execute(
        "SELECT hora_manana, hora_mediodia, hora_noche FROM config_estrategia WHERE id=1").fetchone()
    con.close()
    hora_manana, hora_mediodia, hora_noche = fila
    texto = ("Horarios de tus avisos automáticos:\n\n"
             f"Check-in de la mañana: {_hora24_a_texto12(hora_manana)}\n"
             f"Corte de mediodía: {_hora24_a_texto12(hora_mediodia)}\n"
             f"Cierre de la noche: {_hora24_a_texto12(hora_noche)}")
    render(texto, [[("Cambiar mañana", "horario:editar:manana")],
                   [("Cambiar mediodía", "horario:editar:mediodia")],
                   [("Cambiar noche", "horario:editar:noche")],
                   [("Volver", "menu:recordatorios")]])


def horario_editar_iniciar(slot):
    iniciar_flujo("horario_editar", "hora", {"slot": slot})
    render("¿A qué hora? Escribe un número del 1 al 12.", pedir_texto=True, teclado_numero=True)


def horario_editar_texto(texto):
    d = ESTADO["datos"]
    paso = ESTADO["paso"]
    if paso == "hora":
        texto = texto.strip()
        if not texto.isdigit() or not (1 <= int(texto) <= 12):
            render("Escribe un número del 1 al 12.", pedir_texto=True, teclado_numero=True)
            return
        d["hora12"] = int(texto)
        ESTADO["paso"] = "minuto"
        render("¿Y los minutos? Escribe un número del 0 al 59 (usa 0 para en punto).",
               pedir_texto=True, teclado_numero=True)
        return
    if paso == "minuto":
        texto = texto.strip()
        if not texto.isdigit() or not (0 <= int(texto) <= 59):
            render("Escribe un número del 0 al 59.", pedir_texto=True, teclado_numero=True)
            return
        d["minuto"] = int(texto)
        ESTADO["paso"] = "periodo"
        render("¿AM o PM?", [[("AM", "horario:periodo:AM"), ("PM", "horario:periodo:PM")]])
        return


def horario_periodo_callback(periodo):
    d = ESTADO["datos"]
    hh12, mm = d["hora12"], d["minuto"]
    if periodo == "AM":
        hh24 = 0 if hh12 == 12 else hh12
    else:
        hh24 = 12 if hh12 == 12 else hh12 + 12
    hora_normalizada = f"{hh24:02d}:{mm:02d}"
    slot = d["slot"]
    columna = {"manana": "hora_manana", "mediodia": "hora_mediodia", "noche": "hora_noche"}[slot]
    con = conectar()
    con.execute(f"UPDATE config_estrategia SET {columna}=? WHERE id=1", (hora_normalizada,))
    con.commit()
    con.close()
    terminar_flujo()
    programar_todas_las_alarmas(mostrar_error_en_pantalla=True)
    render(f"Hora actualizada a {_hora24_a_texto12(hora_normalizada)}. Alarma reprogramada.",
           [[("Menú", "menu:main")]])


# ==================== MOTOR DE PANTALLA (equivalente a enviar/editar de Telegram) ====================

ESTADO = {"flujo": None, "paso": None, "datos": {}}


def iniciar_flujo(flujo, paso, datos=None):
    ESTADO["flujo"] = flujo
    ESTADO["paso"] = paso
    ESTADO["datos"] = datos or {}


def terminar_flujo():
    ESTADO["flujo"] = None
    ESTADO["paso"] = None
    ESTADO["datos"] = {}


COLOR_LIQUIDO_VERDE = (0.62, 0.86, 0.20, 1)
COLOR_TUBO_FONDO = (0.93, 0.97, 0.85, 1)
COLOR_CASCO_NEGRO = (0.08, 0.08, 0.09, 1)
COLOR_PANTALLA_NEGRA = (0.03, 0.03, 0.04, 1)
COLOR_DIGITO_BLANCO = (0.95, 0.97, 0.95, 1)
COLOR_DIGITO_VERDE_TENUE = (0.55, 0.80, 0.45, 1)


class MedidorLiquidez(BoxLayout):
    """Tubo vertical tipo 'nivel de albañil' (carcasa negra, líquido verde que
    sube o baja según tu liquidez) + una 'pantallita digital' al lado con el
    saldo actual de la cuenta del sueldo, para saber cuánto te queda por gastar."""

    def __init__(self, **kwargs):
        super().__init__(orientation="horizontal", size_hint=(1, None), height=dp(96), spacing=dp(14), **kwargs)

        self.tubo = Widget(size_hint=(None, 1), width=dp(34))
        with self.tubo.canvas:
            self._casco = Color(*COLOR_CASCO_NEGRO)
            self._casco_rect = RoundedRectangle(radius=[dp(10)])
            self._fondo = Color(*COLOR_TUBO_FONDO)
            self._fondo_rect = RoundedRectangle(radius=[dp(8)])
            self._liquido = Color(*COLOR_LIQUIDO_VERDE)
            self._liquido_rect = Rectangle()
            self._marca = Color(*COLOR_CASCO_NEGRO)
            self._marcas_rect = [Rectangle() for _ in range(3)]
        self.tubo.bind(pos=self._redibujar, size=self._redibujar)
        self.add_widget(self.tubo)

        self.pantalla = BoxLayout(orientation="vertical", size_hint=(1, 1), padding=(dp(12), dp(10)))
        with self.pantalla.canvas.before:
            Color(*COLOR_PANTALLA_NEGRA)
            self._pantalla_rect = RoundedRectangle(radius=[dp(10)])
        self.pantalla.bind(pos=self._redibujar_pantalla, size=self._redibujar_pantalla)

        self.etiqueta_titulo = Label(text="Sueldo", font_name="Poppins", font_size=dp(11),
                                     color=COLOR_DIGITO_VERDE_TENUE, size_hint=(1, None), height=dp(16),
                                     halign="left", valign="top")
        self.etiqueta_titulo.bind(size=lambda inst, s: setattr(inst, "text_size", s))

        self.etiqueta_numero = Label(text="--", font_name="DSEG7", font_size=dp(26),
                                     color=COLOR_DIGITO_BLANCO, size_hint=(1, 1),
                                     halign="left", valign="middle")
        self.etiqueta_numero.bind(size=lambda inst, s: setattr(inst, "text_size", s))

        self.pantalla.add_widget(self.etiqueta_titulo)
        self.pantalla.add_widget(self.etiqueta_numero)
        self.add_widget(self.pantalla)

        self._fraccion = 0.0

    def _redibujar(self, *_):
        x, y = self.tubo.pos
        w, h = self.tubo.size
        borde = dp(3)
        self._casco_rect.pos = (x, y)
        self._casco_rect.size = (w, h)
        self._fondo_rect.pos = (x + borde, y + borde)
        self._fondo_rect.size = (w - borde * 2, h - borde * 2)
        alto_liquido = max((h - borde * 2) * self._fraccion, 0)
        self._liquido_rect.pos = (x + borde, y + borde)
        self._liquido_rect.size = (w - borde * 2, alto_liquido)
        for i, marca in enumerate(self._marcas_rect):
            frac_marca = (i + 1) / (len(self._marcas_rect) + 1)
            marca.pos = (x + borde, y + borde + (h - borde * 2) * frac_marca)
            marca.size = (w - borde * 2, dp(1.4))

    def _redibujar_pantalla(self, *_):
        self._pantalla_rect.pos = self.pantalla.pos
        self._pantalla_rect.size = self.pantalla.size

    def actualizar(self, fraccion, titulo_pantalla, texto_numero):
        self._fraccion = max(0.0, min(1.0, fraccion))
        self.etiqueta_titulo.text = titulo_pantalla
        self.etiqueta_numero.text = texto_numero
        self._redibujar()
        self._redibujar_pantalla()


def actualizar_medidor():
    if PANTALLA is None or not hasattr(PANTALLA, "medidor"):
        return
    con = conectar()
    r = estatus_calcular(con)
    fila_sueldo = con.execute("SELECT activo, cuenta_id FROM config_sueldo WHERE id=1").fetchone()
    activo, cuenta_id = fila_sueldo if fila_sueldo else (0, None)
    titulo = "Sueldo"
    if activo and cuenta_id:
        cuenta = con.execute("SELECT nombre, saldo, moneda FROM cuentas WHERE id=?", (cuenta_id,)).fetchone()
        if cuenta:
            titulo = cuenta[0]
            texto_numero = f"{round(cuenta[1], 2)} {cuenta[2]}"
        else:
            texto_numero = "cuenta eliminada"
    else:
        texto_numero = "sin configurar"
    con.close()
    fraccion = 0.0 if r["estado"] == "Sin gastos fijos" else min(r["semanas_cobertura"] / 4, 1.0)
    PANTALLA.medidor.actualizar(fraccion, titulo, texto_numero)


class MainScreen(Screen):
    """Una sola pantalla cuyo contenido se reconstruye en cada paso,
    igual que el bot reescribía el mensaje con editar()."""

    def build(self):
        raiz = BoxLayout(orientation="vertical", padding=dp(18), spacing=dp(14))
        with raiz.canvas.before:
            Color(*COLOR_FONDO)
            self._bg = Rectangle(pos=raiz.pos, size=raiz.size)
        raiz.bind(pos=self._actualizar_bg, size=self._actualizar_bg)

        self.titulo = Label(text="Joi", font_name="PoppinsSemiBold", font_size=dp(24), color=COLOR_MORADO,
                             size_hint=(1, None), height=dp(36), halign="left", valign="middle")
        self.titulo.bind(size=lambda inst, s: setattr(inst, "text_size", s))
        raiz.add_widget(self.titulo)

        tarjeta = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(12), size_hint=(1, 1))
        with tarjeta.canvas.before:
            Color(*COLOR_PANEL)
            self._tarjeta_rect = RoundedRectangle(pos=tarjeta.pos, size=tarjeta.size, radius=[dp(20)])
        tarjeta.bind(pos=self._actualizar_tarjeta, size=self._actualizar_tarjeta)

        scroll = ScrollView(size_hint=(1, 1))
        self.contenido = BoxLayout(orientation="vertical", spacing=dp(12), size_hint_y=None, padding=(0, dp(4)))
        self.contenido.bind(minimum_height=self.contenido.setter("height"))
        scroll.add_widget(self.contenido)
        tarjeta.add_widget(scroll)

        self.medidor = MedidorLiquidez()
        tarjeta.add_widget(self.medidor)

        raiz.add_widget(tarjeta)

        self.add_widget(raiz)
        render(saludo())
        pantalla_inicio()
        programar_todas_las_alarmas(mostrar_error_en_pantalla=True)

    def _actualizar_bg(self, *_):
        self._bg.pos = self.pos
        self._bg.size = self.size

    def _actualizar_tarjeta(self, instance, *_):
        self._tarjeta_rect.pos = instance.pos
        self._tarjeta_rect.size = instance.size


PANTALLA = None  # referencia global a la MainScreen, asignada al arrancar


class BotonRedondeado(Button):
    """Botón con esquinas redondeadas reales (canvas propio) y fuente Poppins,
    en vez del rectángulo plano por defecto de Kivy."""

    def __init__(self, color_fondo=COLOR_MORADO_OSCURO, color_presionado=None, **kwargs):
        super().__init__(**kwargs)
        self.background_normal = ""
        self.background_down = ""
        self.background_color = (0, 0, 0, 0)
        self.color = COLOR_TEXTO
        self.font_name = "PoppinsMedium"
        self.font_size = dp(15)
        self._color_fondo = color_fondo
        self._color_presionado = color_presionado or tuple(min(c * 1.25, 1) for c in color_fondo[:3]) + (1,)
        with self.canvas.before:
            self._color_instr = Color(*self._color_fondo)
            self._rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(14)])
        self.bind(pos=self._actualizar, size=self._actualizar)
        self.bind(state=self._actualizar_color)

    def _actualizar(self, *_):
        self._rect.pos = self.pos
        self._rect.size = self.size

    def _actualizar_color(self, *_):
        self._color_instr.rgba = self._color_presionado if self.state == "down" else self._color_fondo


def _boton(texto, on_press, color=COLOR_MORADO_OSCURO):
    b = BotonRedondeado(text=texto, size_hint_y=None, height=dp(48), color_fondo=color)

    def _con_sonido(inst):
        try:
            sonido("click")
        except Exception:
            pass
        on_press(inst)

    b.bind(on_release=_con_sonido)
    return b


CANCELAR_CB = "menu:main"


def _con_cancelar(filas_botones):
    if ESTADO["flujo"] is None:
        return filas_botones
    filas_botones = list(filas_botones) if filas_botones else []
    ya_tiene = any(cb == CANCELAR_CB for fila in filas_botones for _, cb in fila)
    if not ya_tiene:
        filas_botones = filas_botones + [[("X Cancelar", CANCELAR_CB)]]
    return filas_botones


def render(texto, filas_botones=None, pedir_texto=False, teclado_numero=False):
    """Equivalente a enviar()/editar() del bot: redibuja título + botones,
    y opcionalmente un campo de texto para el paso actual.
    teclado_numero=True muestra el teclado numérico del teléfono (para montos, días, etc.)."""
    filas_botones = _con_cancelar(filas_botones)
    cont = PANTALLA.contenido
    cont.clear_widgets()
    lbl = Label(text=texto, font_name="Poppins", font_size=dp(15.5), color=COLOR_TEXTO,
                size_hint_y=None, halign="left", valign="top", line_height=1.3)
    lbl.bind(width=lambda inst, w: setattr(inst, "text_size", (w, None)))
    lbl.bind(texture_size=lambda inst, ts: setattr(inst, "height", ts[1] + dp(10)))
    cont.add_widget(lbl)

    if pedir_texto:
        entrada = TextInput(multiline=False, size_hint_y=None, height=dp(48), font_name="Poppins",
                             font_size=dp(15), background_normal="", background_active="",
                             background_color=COLOR_PANEL_CLARO, foreground_color=COLOR_TEXTO,
                             cursor_color=COLOR_MORADO, hint_text="Escribe aquí...",
                             hint_text_color=COLOR_TEXTO_TENUE, padding=(dp(12), dp(12)),
                             input_filter=("float" if teclado_numero else None),
                             input_type=("number" if teclado_numero else "text"))

        def _enviar_texto(*_a):
            valor = entrada.text
            entrada.text = ""
            manejar_texto(valor)

        entrada.bind(on_text_validate=_enviar_texto)
        cont.add_widget(entrada)
        cont.add_widget(_boton("Enviar", _enviar_texto, color=COLOR_MORADO))

    if filas_botones:
        for fila in filas_botones:
            row = BoxLayout(orientation="horizontal", spacing=dp(8), size_hint_y=None, height=dp(48))
            for etiqueta, cb in fila:
                row.add_widget(_boton(etiqueta, lambda inst, cb=cb: manejar_callback(cb)))
            cont.add_widget(row)

    actualizar_medidor()


# ==================== DESPACHO: CALLBACKS (botones) ====================

def manejar_callback(data):
    partes = data.split(":")

    if data == "menu:main":
        terminar_flujo()
        menu_principal()
        return
    if data == "sys:probarnotif":
        probar_notificacion()
        return
    if data == "sys:horarios":
        horarios_menu()
        return
    if data == "sys:sueldo":
        sueldo_menu()
        return
    if data.startswith("sueldo:confirmar:"):
        sueldo_confirmar_callback(data.split(":")[2])
        return
    if data == "sueldo:config:frecuencia":
        sueldo_config_frecuencia()
        return
    if data.startswith("sueldo:frecuencia:"):
        sueldo_frecuencia_callback(data.split(":")[2])
        return
    if data.startswith("sueldo:moneda:"):
        sueldo_moneda_callback(data.split(":")[2])
        return
    if data.startswith("sueldo:diasemana:"):
        sueldo_diasemana_callback(int(data.split(":")[2]))
        return
    if data.startswith("sueldo:cuenta:"):
        sueldo_cuenta_callback(int(data.split(":")[2]))
        return
    if data.startswith("sueldo:configorigen:"):
        sueldo_config_origen_callback(data.split(":")[2])
        return
    if data.startswith("sueldo:configorigeninterno:"):
        sueldo_config_guardar(int(data.split(":")[2]))
        return
    if data == "sueldo:confirmarahora":
        sueldo_confirmar_ahora()
        return
    if data == "sueldo:desactivar":
        sueldo_desactivar()
        return
    if data.startswith("horario:editar:"):
        horario_editar_iniciar(data.split(":")[2])
        return
    if data.startswith("horario:periodo:"):
        horario_periodo_callback(data.split(":")[2])
        return
    if data == "menu:registrar":
        registrar_iniciar()
        return
    if data == "reg:borrar":
        registrar_borrar_menu()
        return
    if data.startswith("reg:borrarid:"):
        registrar_borrar_confirmar_menu(int(partes[2]))
        return
    if data.startswith("reg:borrarconfirmar:"):
        registrar_borrar_ejecutar(int(partes[2]))
        return
    if data.startswith("reg:"):
        registrar_callback(data)
        return
    if data == "menu:saldo":
        saldo_menu()
        return
    if data.startswith("saldo:ver:"):
        saldo_ver(int(partes[2]))
        return
    if data == "saldo:total":
        saldo_total()
        return
    if data == "saldo:estatus":
        estatus_mostrar()
        return
    if data == "saldo:anexar":
        saldo_anexar_menu()
        return
    if data == "saldo:editar":
        saldo_editar_menu()
        return
    if data.startswith("saldo:editarid:"):
        saldo_editar_iniciar(int(partes[2]))
        return
    if data == "saldo:anexar:agregar":
        saldo_anexar_agregar_iniciar()
        return
    if data == "saldo:anexar:quitar":
        saldo_anexar_quitar_menu()
        return
    if data.startswith("saldo:anexar:quitarid:"):
        saldo_anexar_quitar_confirmar(int(partes[3]))
        return
    if data.startswith("anexar:moneda:"):
        anexar_cuenta_callback(partes[2])
        return

    if data in ("menu:deudas", "deuda:menu"):
        deudas_menu()
        return
    if data == "deuda:ver":
        deudas_ver()
        return
    if data == "deuda:nueva":
        deuda_nueva_iniciar()
        return
    if data == "deuda:pagada":
        deuda_pagada_menu()
        return
    if data.startswith("deuda:pagadaid:"):
        deuda_pagada_confirmar(int(partes[2]))
        return
    if data == "deuda:actualizar":
        recalcular_estrategia_ejecutar()
        return
    if data.startswith("deuda:moneda:"):
        deuda_moneda_callback(partes[2])
        return
    if data.startswith("deuda:tipopago:"):
        deuda_tipopago_callback(partes[2])
        return
    if data.startswith("deuda:userecom:"):
        deuda_userecom_callback(partes[2])
        return
    if data == "deuda:elegirestrategia":
        deuda_elegirestrategia_callback()
        return
    if data.startswith("deuda:setestrategia:"):
        deuda_setestrategia_callback(partes[2])
        return
    if data == "deuda:estrategia":
        estrategia_menu()
        return
    if data.startswith("estrategia:elegir:"):
        estrategia_elegir_callback(partes[2])
        return
    if data == "deuda:informe":
        informe_mostrar()
        return

    if data.startswith("cal:"):
        manejar_calendario(data, partes)
        return

    if data in ("menu:pagosmensuales", "pago:menu"):
        pagos_menu()
        return
    if data == "pago:ver":
        pagos_ver()
        return
    if data == "pago:nuevo":
        pago_nuevo_iniciar()
        return
    if data.startswith("pago:moneda:"):
        ESTADO["datos"]["moneda"] = partes[2]
        ESTADO["paso"] = "frecuencia"
        render("¿Diario, semanal o mensual?",
               [[("Diario", "pago:frecuencia:diario"), ("Semanal", "pago:frecuencia:semanal"),
                 ("Mensual", "pago:frecuencia:mensual")]])
        return
    if data == "pago:frecuencia:mensual":
        ESTADO["datos"]["frecuencia"] = "mensual"
        ESTADO["paso"] = "dia"
        render("¿Qué día del mes vence? (1-31)", pedir_texto=True, teclado_numero=True)
        return
    if data in ("pago:frecuencia:diario", "pago:frecuencia:semanal"):
        ESTADO["datos"]["frecuencia"] = partes[2]
        filas = [[(c, f"pago:catrec:{c}")] for c in CATEGORIAS_GASTO]
        render("¿Categoría?", filas)
        return
    if data.startswith("pago:catrec:"):
        pago_recurrente_categoria_callback(partes[2])
        return
    if data.startswith("pago:cuentarec:"):
        pago_recurrente_cuenta_callback(int(partes[2]))
        return
    if data.startswith("pago:diasemana:"):
        pago_dia_semana_callback(int(partes[2]))
        return
    if data == "pago:editar":
        pago_editar_menu()
        return
    if data.startswith("pago:editarid:"):
        pago_editar_campos(int(partes[2]))
        return
    if data.startswith("pago:editarcampo:"):
        _, _, pago_id, campo = data.split(":")
        pago_editar_campo_elegido(int(pago_id), campo)
        return
    if data.startswith("pago:editarvalor:"):
        _, _, pago_id, campo, valor = data.split(":", 4)
        pago_editar_valor_callback(int(pago_id), campo, valor)
        return
    if data == "pago:pausar":
        pago_pausar_menu()
        return
    if data == "pago:pausarprioridad3":
        pago_pausar_prioridad3()
        return
    if data == "pago:borrar":
        pago_borrar_menu()
        return
    if data.startswith("pago:borrarid:"):
        pago_borrar_confirmar_menu(int(partes[2]))
        return
    if data.startswith("pago:borrarconfirmar:"):
        pago_borrar_ejecutar(int(partes[2]))
        return
    if data.startswith("pago:pausarid:"):
        pago_pausar_confirmar(int(partes[2]))
        return

    if data in ("menu:porcobrar", "pc:menu"):
        porcobrar_menu()
        return
    if data == "pc:prestamo":
        prestamo_iniciar()
        return
    if data == "pc:cobrar":
        cobrar_iniciar()
        return
    if data.startswith("prestamo:moneda:") or data.startswith("pc:moneda:"):
        porcobrar_moneda_callback(partes[2])
        return
    if data.startswith("prestamo:cuenta:"):
        prestamo_cuenta_callback(int(partes[2]))
        return
    if data == "pc:pagado":
        pagado_menu()
        return
    if data.startswith("pagado:elegir:"):
        pagado_elegir(int(partes[2]))
        return
    if data.startswith("pagado:completo:"):
        pagado_completo_callback(int(partes[2]))
        return
    if data.startswith("pagado:diferente:"):
        pagado_diferente_iniciar(int(partes[2]))
        return
    if data.startswith("pagado:cuenta:"):
        pagado_cuenta_callback(int(partes[2]))
        return

    if data in ("menu:recordatorios", "rec:menu"):
        recordatorios_menu()
        return
    if data == "rec:proximos":
        recordatorios_proximos()
        return
    if data == "rec:ajustar":
        recordatorios_ajustar_menu()
        return
    if data.startswith("rec:elegir:"):
        _, _, tipo, item_id = data.split(":")
        recordatorios_ajustar_iniciar(tipo, int(item_id))
        return

    if data in ("menu:resumen", "resumen:menu"):
        resumen_menu()
        return
    if data.startswith("resumen:tipo:"):
        resumen_periodo_menu(partes[2])
        return
    if data.startswith("resumen:ver:"):
        _, _, tipo, periodo = data.split(":")
        resumen_mostrar(tipo, periodo)
        return

    if data.startswith("obj:moneda:"):
        objetivo_moneda_callback(partes[2])
        return
    if data in ("menu:objetivos", "obj:menu"):
        objetivos_menu()
        return
    if data == "obj:ver":
        objetivos_ver()
        return
    if data == "obj:nuevo":
        objetivo_nuevo_iniciar()
        return
    if data == "obj:cumplido":
        objetivo_cumplido_menu()
        return
    if data.startswith("obj:cumplidoid:"):
        objetivo_cumplido_confirmar(int(partes[2]))
        return


def manejar_texto(texto):
    flujo = ESTADO.get("flujo")
    if not flujo:
        return
    despachadores = {
        "registrar": registrar_texto, "anexar_cuenta": anexar_cuenta_texto,
        "deuda_nueva": deuda_nueva_texto, "objetivo_nuevo": objetivo_nuevo_texto,
        "pago_nuevo": pago_nuevo_texto, "pago_editar": pago_editar_texto,
        "prestamo": porcobrar_texto, "porcobrar_nuevo": porcobrar_texto,
        "pagado": pagado_texto, "ajustar_aviso": ajustar_aviso_texto,
        "saldo_editar": saldo_editar_texto,
        "horario_editar": horario_editar_texto,
        "sueldo_config": sueldo_config_texto,
        "sueldo_editar_monto_dia": sueldo_editar_monto_dia_texto,
    }
    fn = despachadores.get(flujo)
    if fn:
        fn(texto)


# ==================== MENÚ PRINCIPAL ====================

def pantalla_inicio():
    """Al abrir la app: si toca confirmar el sueldo hoy, pregunta eso primero;
    si no, va directo al menú principal."""
    con = conectar()
    pendiente = sueldo_pendiente_hoy(con)
    con.close()
    if pendiente:
        sueldo_confirmar_prompt()
    else:
        menu_principal()


def menu_principal():
    filas = [
        [("Registrar", "menu:registrar"), ("Por cobrar", "menu:porcobrar")],
        [("Deudas", "menu:deudas"), ("Gastos fijos", "menu:pagosmensuales")],
        [("Recordatorios", "menu:recordatorios"), ("Saldo", "menu:saldo")],
        [("Resumen", "menu:resumen"), ("Objetivos", "menu:objetivos")],
    ]
    render("¿Qué quieres hacer?", filas)


# ==================== CALENDARIO SIMPLIFICADO (Fase 1: pedir fecha por texto) ====================
# Nota: el selector visual de calendario del bot se simplifica por texto en esta
# primera fase (escribe AAAA-MM-DD o "no" para omitir); se puede mejorar visualmente después.

def pedir_fecha(texto_pregunta, destino):
    ESTADO["datos"]["_destino_fecha"] = destino
    ESTADO["paso"] = "_fecha_texto"
    render(texto_pregunta + "\n(Escribe AAAA-MM-DD, o 'no' para omitir)", pedir_texto=True)


def manejar_calendario(data, partes):
    # compatibilidad con versiones futuras del selector visual; no usado en Fase 1
    pass


# ==================== MÓDULO: REGISTRAR ====================

def registrar_iniciar():
    iniciar_flujo("registrar", "tipo")
    render("¿Ingreso o gasto?",
           [[("Ingreso", "reg:tipo:ingreso"), ("Gasto", "reg:tipo:gasto")], [("Borrar uno", "reg:borrar")]])


def registrar_borrar_menu():
    con = conectar()
    filas_db = con.execute(
        "SELECT m.id, m.fecha, m.tipo, m.monto, m.moneda, m.categoria FROM movimientos m "
        "ORDER BY m.fecha DESC LIMIT 10").fetchall()
    con.close()
    if not filas_db:
        render("No hay movimientos registrados.", [[("Volver", "menu:registrar")]])
        return
    filas = []
    for mid, fecha, tipo, monto, moneda, categoria in filas_db:
        fecha_corta = fecha[5:16].replace("T", " ")
        filas.append([(f"{fecha_corta} {tipo} {monto} {moneda} ({categoria})", f"reg:borrarid:{mid}")])
    filas.append([("Volver", "menu:registrar")])
    render("¿Cuál quieres borrar? (últimos 10)", filas)


def registrar_borrar_confirmar_menu(mov_id):
    con = conectar()
    fila = con.execute("SELECT tipo, monto, moneda, categoria FROM movimientos WHERE id=?", (mov_id,)).fetchone()
    con.close()
    if not fila:
        render("Ese movimiento ya no existe.", [[("Menú", "menu:main")]])
        return
    tipo, monto, moneda, categoria = fila
    render(f"¿Borrar {tipo} de {monto} {moneda} ({categoria})?",
           [[("Sí, borrar", f"reg:borrarconfirmar:{mov_id}"), ("No", "menu:registrar")]])


def registrar_borrar_ejecutar(mov_id):
    con = conectar()
    fila = con.execute("SELECT tipo, monto_usdt, cuenta_id FROM movimientos WHERE id=?", (mov_id,)).fetchone()
    if not fila:
        con.close()
        render("Ese movimiento ya no existe.", [[("Menú", "menu:main")]])
        return
    tipo, monto_usdt, cuenta_id = fila
    cuenta = con.execute("SELECT nombre, saldo, moneda FROM cuentas WHERE id=?", (cuenta_id,)).fetchone()
    delta = -monto_usdt if tipo == "ingreso" else monto_usdt
    delta_en_moneda = delta * obtener_tasas()["paralelo"] if cuenta[2] == "VES" else delta
    nuevo_saldo = cuenta[1] + delta_en_moneda
    con.execute("UPDATE cuentas SET saldo=? WHERE id=?", (nuevo_saldo, cuenta_id))
    con.execute("DELETE FROM movimientos WHERE id=?", (mov_id,))
    con.commit()
    con.close()
    sonido("borrar")
    render(f"Borrado. Nuevo saldo {cuenta[0]}: {round(nuevo_saldo, 2)} {cuenta[2]}.", [[("Menú", "menu:main")]])


def registrar_callback(data):
    partes = data.split(":")
    d = ESTADO["datos"]
    if partes[1] == "tipo":
        d["tipo"] = partes[2]
        ESTADO["paso"] = "monto"
        render("¿Cuánto? (escribe solo el número)", pedir_texto=True, teclado_numero=True)
        return
    if partes[1] == "moneda":
        d["moneda"] = partes[2]
        ESTADO["paso"] = "cuenta"
        pedir_cuenta("¿De/a qué cuenta?", "reg:cuenta:")
        return
    if partes[1] == "cuenta":
        d["cuenta_id"] = int(partes[2])
        ESTADO["paso"] = "categoria"
        opciones = CATEGORIAS_GASTO if d["tipo"] == "gasto" else CATEGORIAS_INGRESO
        filas = [[(c, f"reg:cat:{c}")] for c in opciones]
        render("¿Categoría?", filas)
        return
    if partes[1] == "cat":
        d["categoria"] = partes[2]
        if d["tipo"] == "gasto":
            con = conectar()
            cuenta = con.execute("SELECT nombre, saldo, moneda FROM cuentas WHERE id=?", (d["cuenta_id"],)).fetchone()
            monto_usdt = convertir_a_usdt(d["monto"], d["moneda"])
            saldo_usdt = convertir_a_usdt(cuenta[1], cuenta[2])
            con.close()
            if monto_usdt > saldo_usdt:
                d["monto_usdt_total"] = monto_usdt
                d["saldo_disponible_principal"] = saldo_usdt
                faltante = round(monto_usdt - saldo_usdt, 2)
                otras = [c for c in listar_cuentas_simples() if c["id"] != d["cuenta_id"]]
                if not otras:
                    render(f"{cuenta[0]} no alcanza -- faltan ~{faltante} USDT, y no tienes otra cuenta de "
                           f"donde completarlo. El gasto no se registró.", [[("Menú", "menu:main")]])
                    return
                filas = [[(c["nombre"], f"reg:cuenta2:{c['id']}")] for c in otras]
                render(f"{cuenta[0]} no alcanza -- faltan ~{faltante} USDT. ¿De qué cuenta sacas el resto?", filas)
                return
        finalizar_registro(d)
        return
    if partes[1] == "cuenta2":
        d["cuenta_secundaria_id"] = int(partes[2])
        finalizar_registro_dividido(d)
        return


def registrar_texto(texto):
    if ESTADO["paso"] != "monto":
        return
    try:
        monto = parsear_monto(texto)
    except ValueError:
        render("Eso no es un número. Escribe solo la cantidad, ej: 20 o 20000", pedir_texto=True, teclado_numero=True)
        return
    if monto <= 0:
        render("El monto debe ser mayor a 0.", pedir_texto=True, teclado_numero=True)
        return
    ESTADO["datos"]["monto"] = monto
    ESTADO["paso"] = "moneda"
    render("¿En qué moneda?",
           [[("USD", "reg:moneda:USD"), ("USDT", "reg:moneda:USDT"), ("VES", "reg:moneda:VES")]])


def finalizar_registro(datos):
    con = conectar()
    monto_usdt = convertir_a_usdt(datos["monto"], datos["moneda"])
    ahora = datetime.now(UTC_MENOS_4).isoformat()
    cuenta = con.execute("SELECT nombre, saldo, moneda FROM cuentas WHERE id=?", (datos["cuenta_id"],)).fetchone()
    delta = monto_usdt if datos["tipo"] == "ingreso" else -monto_usdt
    delta_en_moneda_cuenta = delta * obtener_tasas()["paralelo"] if cuenta[2] == "VES" else delta
    nuevo_saldo = cuenta[1] + delta_en_moneda_cuenta
    con.execute("UPDATE cuentas SET saldo=? WHERE id=?", (nuevo_saldo, datos["cuenta_id"]))
    con.execute("INSERT INTO movimientos (fecha, tipo, monto, moneda, monto_usdt, categoria, cuenta_id) "
                "VALUES (?,?,?,?,?,?,?)",
                (ahora, datos["tipo"], datos["monto"], datos["moneda"], monto_usdt, datos["categoria"], datos["cuenta_id"]))
    lineas_estrategia = []
    if datos["tipo"] == "ingreso" and datos["categoria"] != "Retorno de saldo":
        lineas_estrategia = aplicar_estrategia_ingreso(con, monto_usdt)
    con.commit()
    advertencias = []
    if datos["tipo"] == "gasto":
        if nuevo_saldo < 0:
            advertencias.append(f"ADVERTENCIA: {cuenta[0]} quedó en negativo ({round(nuevo_saldo, 2)} {cuenta[2]}).")
        if estatus_calcular(con)["estado"] == "Crítico":
            advertencias.append("ADVERTENCIA: tu estatus general quedó en Crítico -- ya no cubres ni 1 semana de gasto fijo.")
    con.close()
    terminar_flujo()
    verbo = "Ingreso" if datos["tipo"] == "ingreso" else "Gasto"
    texto = (f"{verbo} registrado: {datos['monto']} {datos['moneda']} ({datos['categoria']})\n"
             f"{'Entra a' if datos['tipo'] == 'ingreso' else 'Sale de'} {cuenta[0]}.\n"
             f"Nuevo saldo {cuenta[0]}: {round(nuevo_saldo, 2)} {cuenta[2]}")
    if lineas_estrategia:
        texto += "\n\nRepartido según tu estrategia:\n" + "\n".join(lineas_estrategia)
    if advertencias:
        texto += "\n\n" + "\n".join(advertencias)
    sonido("exito")
    render(texto, [[("Menú", "menu:main")]])


def finalizar_registro_dividido(datos):
    con = conectar()
    ahora = datetime.now(UTC_MENOS_4).isoformat()
    cuenta1 = con.execute("SELECT nombre, saldo, moneda FROM cuentas WHERE id=?", (datos["cuenta_id"],)).fetchone()
    cuenta2 = con.execute("SELECT nombre, saldo, moneda FROM cuentas WHERE id=?", (datos["cuenta_secundaria_id"],)).fetchone()
    monto_usdt_total = datos["monto_usdt_total"]
    saldo1_usdt = datos["saldo_disponible_principal"]
    resto_usdt = round(monto_usdt_total - saldo1_usdt, 2)
    con.execute("UPDATE cuentas SET saldo=0 WHERE id=?", (datos["cuenta_id"],))
    con.execute("INSERT INTO movimientos (fecha, tipo, monto, moneda, monto_usdt, categoria, cuenta_id) "
                "VALUES (?,'gasto',?,?,?,?,?)",
                (ahora, cuenta1[1], cuenta1[2], round(saldo1_usdt, 2), datos["categoria"], datos["cuenta_id"]))
    delta2_moneda = resto_usdt * obtener_tasas()["paralelo"] if cuenta2[2] == "VES" else resto_usdt
    nuevo_saldo2 = cuenta2[1] - delta2_moneda
    con.execute("UPDATE cuentas SET saldo=? WHERE id=?", (nuevo_saldo2, datos["cuenta_secundaria_id"]))
    con.execute("INSERT INTO movimientos (fecha, tipo, monto, moneda, monto_usdt, categoria, cuenta_id) "
                "VALUES (?,'gasto',?,?,?,?,?)",
                (ahora, round(delta2_moneda, 2), cuenta2[2], resto_usdt, datos["categoria"], datos["cuenta_secundaria_id"]))
    con.commit()
    advertencias = []
    if nuevo_saldo2 < 0:
        advertencias.append(f"ADVERTENCIA: {cuenta2[0]} también quedó en negativo ({round(nuevo_saldo2, 2)} {cuenta2[2]}).")
    if estatus_calcular(con)["estado"] == "Crítico":
        advertencias.append("ADVERTENCIA: tu estatus general quedó en Crítico -- ya no cubres ni 1 semana de gasto fijo.")
    con.close()
    terminar_flujo()
    texto = (f"Gasto registrado en dos partes ({datos['categoria']}):\n"
             f"- {cuenta1[0]}: {cuenta1[1]} {cuenta1[2]} (todo el saldo, queda en 0)\n"
             f"- {cuenta2[0]}: {round(delta2_moneda, 2)} {cuenta2[2]} (el resto)\n"
             f"Nuevo saldo {cuenta2[0]}: {round(nuevo_saldo2, 2)} {cuenta2[2]}")
    if advertencias:
        texto += "\n\n" + "\n".join(advertencias)
    sonido("exito")
    render(texto, [[("Menú", "menu:main")]])


# ==================== MÓDULO: SALDO ====================

def saldo_menu():
    con = conectar()
    cuentas = con.execute("SELECT id, nombre FROM cuentas ORDER BY id").fetchall()
    con.close()
    filas = [[(c[1], f"saldo:ver:{c[0]}")] for c in cuentas]
    filas.append([("Anexar", "saldo:anexar")])
    filas.append([("Total", "saldo:total")])
    filas.append([("Estatus", "saldo:estatus")])
    filas.append([("Sueldo", "sys:sueldo")])
    filas.append([("Volver", "menu:main")])
    render("¿Qué cuenta quieres ver?", filas)


def saldo_ver(cuenta_id):
    con = conectar()
    c = con.execute("SELECT nombre, saldo, moneda, ultima_confirmacion FROM cuentas WHERE id=?", (cuenta_id,)).fetchone()
    con.close()
    usdt = round(convertir_a_usdt(c[1], c[2]), 2)
    extra = f" (~{usdt} USDT)" if c[2] != "USDT" else ""
    ultima = c[3][:16].replace("T", " ") if c[3] else "nunca confirmado"
    render(f"{c[0]}: {c[1]} {c[2]}{extra}\nÚltima confirmación: {ultima}", [[("Volver", "menu:saldo")]])


def saldo_total():
    con = conectar()
    cuentas = con.execute("SELECT nombre, saldo, moneda FROM cuentas").fetchall()
    con.close()
    total = sum(convertir_a_usdt(c[1], c[2]) for c in cuentas)
    detalle = "\n".join(f"{c[0]} {round(convertir_a_usdt(c[1], c[2]), 2)}" for c in cuentas)
    render(f"Total: {round(total, 2)} USDT\n({detalle})", [[("Volver", "menu:saldo")]])


def estatus_mostrar():
    con = conectar()
    r = estatus_calcular(con)
    con.close()
    tasas = obtener_tasas()
    costo_bs = round(r["costo_semanal_usdt"] * tasas["paralelo"], 2)
    lineas = ["ESTATUS DE TU PLAN", "", f"Estado: {r['estado']}", f"Saldo total: {r['saldo_total_usdt']} USDT",
              f"Tu semana cuesta: {r['costo_semanal_usdt']} USDT (~{costo_bs} Bs)"]
    if r["estado"] == "Sin gastos fijos":
        lineas.append("\nTodavía no tienes gastos fijos configurados -- sin eso no puedo calcular "
                      "si tu saldo te alcanza o no. Ve a 'Gastos fijos' para agregarlos.")
    elif r["estado"] == "Crítico":
        lineas.append("\nADVERTENCIA: no tienes respaldo para cubrir tu semana.")
        lineas.append(f"Para llegar a Saludable, te faltan: {r['faltante_saludable']} USDT")
    elif r["estado"] == "Saludable":
        lineas.append(f"\nCobertura actual: ~{r['semanas_cobertura']} semanas.")
        lineas.append(f"Para llegar a Óptimo, te faltan: {r['faltante_optimo']} USDT")
    else:
        lineas.append("\nEstás cubierto por 4 semanas o más de gasto fijo.")
    render("\n".join(lineas), [[("Volver", "menu:saldo")]])


def saldo_anexar_menu():
    render("¿Qué quieres hacer?",
           [[("Agregar cuenta nueva", "saldo:anexar:agregar")], [("Quitar una cuenta", "saldo:anexar:quitar")],
            [("Editar saldo", "saldo:editar")], [("Volver", "menu:saldo")]])


def saldo_editar_menu():
    con = conectar()
    cuentas = con.execute("SELECT id, nombre, saldo, moneda FROM cuentas ORDER BY id").fetchall()
    con.close()
    if not cuentas:
        render("No tienes cuentas todavía.", [[("Volver", "saldo:anexar")]])
        return
    filas = [[(f"{n} ({s} {m})", f"saldo:editarid:{i}")] for i, n, s, m in cuentas]
    filas.append([("Volver", "saldo:anexar")])
    render("¿Cuál cuenta quieres editar?", filas)


def saldo_editar_iniciar(cuenta_id):
    iniciar_flujo("saldo_editar", "monto", {"cuenta_id": cuenta_id})
    render("¿Cuál es el saldo correcto?", pedir_texto=True, teclado_numero=True)


def saldo_editar_texto(texto):
    try:
        monto = parsear_monto(texto)
    except ValueError:
        render("Escribe solo el número.", pedir_texto=True, teclado_numero=True)
        return
    con = conectar()
    con.execute("UPDATE cuentas SET saldo=?, ultima_confirmacion=? WHERE id=?",
                (monto, datetime.now(UTC_MENOS_4).isoformat(), ESTADO["datos"]["cuenta_id"]))
    con.commit()
    con.close()
    terminar_flujo()
    sonido("exito")
    render("Saldo actualizado.", [[("Menú", "menu:main")]])


def saldo_anexar_agregar_iniciar():
    iniciar_flujo("anexar_cuenta", "nombre")
    render("¿Nombre de la cuenta nueva?", pedir_texto=True)


def saldo_anexar_quitar_menu():
    con = conectar()
    cuentas = con.execute("SELECT id, nombre, saldo, moneda FROM cuentas").fetchall()
    con.close()
    filas = [[(f"{c[1]} ({c[2]} {c[3]})", f"saldo:anexar:quitarid:{c[0]}")] for c in cuentas]
    filas.append([("Volver", "menu:saldo")])
    render("¿Cuál cuenta quitar?", filas)


def saldo_anexar_quitar_confirmar(cuenta_id):
    con = conectar()
    con.execute("DELETE FROM cuentas WHERE id=?", (cuenta_id,))
    con.commit()
    con.close()
    sonido("borrar")
    render("Cuenta eliminada.", [[("Menú", "menu:main")]])


def anexar_cuenta_texto(texto):
    d = ESTADO["datos"]
    if ESTADO["paso"] == "nombre":
        d["nombre"] = texto.strip()
        ESTADO["paso"] = "saldo_inicial"
        render("¿Saldo inicial? (escribe solo el número, 0 si empieza en cero)", pedir_texto=True, teclado_numero=True)
        return
    if ESTADO["paso"] == "saldo_inicial":
        try:
            d["saldo"] = parsear_monto(texto)
        except ValueError:
            render("Eso no es un número. Escribe solo la cantidad.", pedir_texto=True, teclado_numero=True)
            return
        ESTADO["paso"] = "moneda"
        render("¿Moneda?", [[("USD", "anexar:moneda:USD"), ("USDT", "anexar:moneda:USDT"), ("VES", "anexar:moneda:VES")]])


def anexar_cuenta_callback(moneda):
    d = ESTADO["datos"]
    con = conectar()
    try:
        con.execute("INSERT INTO cuentas (nombre, grupo, saldo, moneda, ultima_confirmacion) "
                    "VALUES (?, 'sin_grupo', ?, ?, ?)",
                    (d["nombre"], d["saldo"], moneda, datetime.now(UTC_MENOS_4).isoformat()))
        con.commit()
        render(f"Cuenta '{d['nombre']}' agregada.", [[("Menú", "menu:main")]])
        sonido("exito")
    except sqlite3.IntegrityError:
        render("Ya existe una cuenta con ese nombre.", [[("Menú", "menu:main")]])
    finally:
        con.close()
        terminar_flujo()


# ==================== MÓDULO: DEUDAS ====================

def deudas_menu():
    render("¿Qué quieres hacer?",
           [[("Ver estado", "deuda:ver"), ("Nueva", "deuda:nueva")],
            [("Marcar pagada", "deuda:pagada"), ("Actualizar", "deuda:actualizar")],
            [("Estrategia", "deuda:estrategia"), ("Informe", "deuda:informe")],
            [("Volver", "menu:main")]])


def recalcular_estrategia_ejecutar():
    con = conectar()
    con.execute("UPDATE config_estrategia SET colchon_actual=0 WHERE id=1")
    con.execute("UPDATE deudas SET monto_pagado=0 WHERE estado='activa'")
    con.execute("UPDATE objetivos SET monto_actual=0 WHERE estado='activo'")
    con.execute("DELETE FROM deuda_pagos WHERE deuda_id IN (SELECT id FROM deudas WHERE estado='activa')")
    con.commit()
    ingresos = con.execute(
        "SELECT monto_usdt FROM movimientos WHERE tipo='ingreso' AND categoria='Ingreso' ORDER BY fecha ASC").fetchall()
    for (monto_usdt,) in ingresos:
        aplicar_estrategia_ingreso(con, monto_usdt)
    deudas_cuotas = con.execute(
        "SELECT id, nombre, monto_total, moneda, dia_pago FROM deudas WHERE estado='activa' "
        "AND tipo_pago='cuotas' AND dia_pago IS NOT NULL").fetchall()
    for did, nombre, monto_total, moneda, dia_pago in deudas_cuotas:
        calcular_resumen_cuotas(con, did, nombre, monto_total, moneda, dia_pago)
    con.close()
    sonido("exito")
    render("Plan actualizado con tus datos actuales.", [[("Menú", "menu:main")]])


def deudas_ver():
    con = conectar()
    filas_db = con.execute(
        "SELECT nombre, monto_total, monto_pagado, moneda, interes_mensual, fecha_limite, tipo_pago, dia_pago "
        "FROM deudas WHERE estado='activa'").fetchall()
    colchon_meta, colchon_actual = con.execute("SELECT colchon_meta, colchon_actual FROM config_estrategia WHERE id=1").fetchone()
    con.close()
    if not filas_db:
        texto = "No tienes deudas activas."
    else:
        lineas = []
        for n, total, pagado, moneda, interes, limite, tipo_pago, dia_pago in filas_db:
            falta = round(total - pagado, 2)
            extra = f", interés {interes*100:.0f}%/mes" if interes else ""
            if tipo_pago == "cuotas":
                extra += f", se reinicia día {dia_pago}"
            extra += f", vence {limite}" if limite else ""
            lineas.append(f"{n}: falta {falta} {moneda}{extra}")
        texto = "Deudas activas:\n" + "\n".join(lineas)
    texto += f"\n\nColchón: {colchon_actual} de {colchon_meta}"
    render(texto, [[("Volver", "deuda:menu")]])


def deuda_nueva_iniciar():
    iniciar_flujo("deuda_nueva", "nombre")
    render("¿Nombre de la deuda?", pedir_texto=True)


def deuda_nueva_texto(texto):
    d = ESTADO["datos"]
    if ESTADO["paso"] == "nombre":
        d["nombre"] = texto.strip()
        ESTADO["paso"] = "monto_total"
        render("¿Monto?", pedir_texto=True, teclado_numero=True)
        return
    if ESTADO["paso"] == "monto_total":
        try:
            d["monto_total"] = parsear_monto(texto)
        except ValueError:
            render("Escribe solo el número.", pedir_texto=True, teclado_numero=True)
            return
        ESTADO["paso"] = "moneda"
        render("¿Moneda?", [[("USD", "deuda:moneda:USD"), ("USDT", "deuda:moneda:USDT"), ("VES", "deuda:moneda:VES")]])
        return
    if ESTADO["paso"] == "interes":
        try:
            d["interes_mensual"] = parsear_monto(texto) / 100
        except ValueError:
            render("Escribe solo el número, ej: 10 para 10%.", pedir_texto=True, teclado_numero=True)
            return
        con = conectar()
        saldo_actual = estatus_calcular(con)["saldo_total_usdt"]
        if saldo_actual <= 0:
            con.close()
            render("Todavía no tienes ningún saldo registrado (tu liquidez actual es $0), así que no "
                   "puedo calcular una recomendación real -- necesito saber con cuánto cuentas primero.\n\n"
                   "Puedes configurar tu saldo ahora, o elegir tú mismo la estrategia y seguir con la deuda.",
                   [[("Elegir yo la estrategia", "deuda:elegirestrategia")],
                    [("Configurar saldo primero", "menu:saldo")],
                    [("Menú", "menu:main")]])
            return
        recomendada, estatus, deuda_total, ingreso_30d = deuda_recomendar_estrategia(
            con, convertir_a_usdt(d["monto_total"], d["moneda"]))
        con.close()
        d["_recomendada"] = recomendada
        render(f"Con tu situación actual (Estatus: {estatus}, deuda total {round(deuda_total, 2)}, "
               f"ingreso promedio {round(ingreso_30d, 2)}/mes), te recomiendo: {recomendada.upper()}.",
               [[(f"Usar {recomendada.upper()}", f"deuda:userecom:{recomendada}"), ("Elegir yo", "deuda:elegirestrategia")]])
        return
    if ESTADO["paso"] == "_fecha_texto":
        _procesar_fecha_texto(texto)
        return


def _procesar_fecha_texto(texto):
    texto = texto.strip()
    fecha = None if texto.lower() == "no" else texto
    destino = ESTADO["datos"].get("_destino_fecha")
    if destino == "deuda_nueva":
        deuda_guardar(ESTADO["datos"], fecha)
    elif destino == "deuda_reinicio":
        dia_pago = None
        try:
            dia_pago = int(fecha.split("-")[2]) if fecha else None
        except (ValueError, IndexError):
            dia_pago = None
        deuda_guardar(ESTADO["datos"], None, dia_pago_directo=dia_pago)
    elif destino == "objetivo_nuevo":
        objetivo_guardar(ESTADO["datos"], fecha)


def deuda_recomendar_estrategia(con, monto_nueva_deuda_usdt):
    estatus = estatus_calcular(con)["estado"]
    deudas_activas = con.execute("SELECT monto_total, monto_pagado, moneda FROM deudas WHERE estado='activa'").fetchall()
    deuda_pendiente_actual_usdt = sum(convertir_a_usdt(t - p, m) for t, p, m in deudas_activas)
    deuda_total = round(deuda_pendiente_actual_usdt + monto_nueva_deuda_usdt, 2)
    desde = (datetime.now(UTC_MENOS_4) - timedelta(days=30)).isoformat()
    ingreso_30d = con.execute(
        "SELECT COALESCE(SUM(monto_usdt),0) FROM movimientos WHERE tipo='ingreso' AND categoria='Ingreso' AND fecha>=?",
        (desde,)).fetchone()[0]
    ingreso_30d = round(ingreso_30d, 2)
    if estatus == "Crítico":
        recomendada = "live"
    elif ingreso_30d > 0 and deuda_total > 3 * ingreso_30d:
        recomendada = "speed"
    else:
        recomendada = "medium"
    return recomendada, estatus, deuda_total, ingreso_30d


def _continuar_a_tipo_pago():
    ESTADO["paso"] = "tipo_pago"
    render("¿Un solo pago (Límite) o se reinicia cada mes (Reinicio)?",
           [[("Límite (un solo pago)", "deuda:tipopago:unico"), ("Reinicio (cada mes)", "deuda:tipopago:cuotas")]])


def deuda_userecom_callback(nombre):
    con = conectar()
    con.execute("UPDATE config_estrategia SET estrategia_activa=? WHERE id=1", (nombre,))
    con.commit()
    con.close()
    _continuar_a_tipo_pago()


def deuda_elegirestrategia_callback():
    render("¿Cuál estrategia usar?",
           [[("Speed", "deuda:setestrategia:speed"), ("Medium", "deuda:setestrategia:medium"),
             ("Live", "deuda:setestrategia:live")]])


def deuda_setestrategia_callback(nombre):
    con = conectar()
    con.execute("UPDATE config_estrategia SET estrategia_activa=? WHERE id=1", (nombre,))
    con.commit()
    con.close()
    _continuar_a_tipo_pago()


def estrategia_menu():
    con = conectar()
    activa = con.execute("SELECT estrategia_activa FROM config_estrategia WHERE id=1").fetchone()[0]
    con.close()
    render(f"Estrategia activa: {activa.upper()}\n\n¿Cuál usar?",
           [[("Speed", "estrategia:elegir:speed"), ("Medium", "estrategia:elegir:medium"),
             ("Live", "estrategia:elegir:live")], [("Volver", "deuda:menu")]])


def estrategia_elegir_callback(nombre):
    con = conectar()
    con.execute("UPDATE config_estrategia SET estrategia_activa=? WHERE id=1", (nombre,))
    con.commit()
    con.close()
    sonido("exito")
    render(f"Estrategia cambiada a {nombre.upper()}.", [[("Menú", "menu:main")]])


def informe_mostrar():
    con = conectar()
    deudas = con.execute(
        "SELECT id, nombre, monto_total, monto_pagado, moneda, tipo_pago, dia_pago, fecha_limite "
        "FROM deudas WHERE estado='activa'").fetchall()
    hoy = datetime.now(UTC_MENOS_4).date()
    if not deudas:
        con.close()
        render("No tienes deudas activas.", [[("Volver", "deuda:menu")]])
        return
    estatus_info = estatus_calcular(con)
    cfg = con.execute("SELECT colchon_meta, colchon_actual, estrategia_activa FROM config_estrategia WHERE id=1").fetchone()
    colchon_meta, colchon_actual, estrategia_activa = cfg
    estrategia_usar = "live" if estatus_info["estado"] == "Crítico" else estrategia_activa
    tabla_estr = ESTRATEGIAS.get(estrategia_usar, ESTRATEGIAS["medium"])
    pct_deuda = tabla_estr["fase1"][1] if colchon_actual < colchon_meta else tabla_estr["fase2"][0]
    cuota_estimada_usdt = estatus_info["saldo_total_usdt"] * pct_deuda
    prioritaria = calcular_deuda_mayor_interes(con)
    bloques = []
    for did, nombre, total, pagado, moneda, tipo_pago, dia_pago, fecha_limite in deudas:
        pendiente = round(total - pagado, 2)
        pagos = con.execute("SELECT monto FROM deuda_pagos WHERE deuda_id=?", (did,)).fetchall()
        n_pagos = len(pagos)
        cuota_prom = round(sum(p[0] for p in pagos) / n_pagos, 2) if n_pagos else 0
        if tipo_pago == "cuotas" and dia_pago:
            proxima = hoy.replace(day=min(dia_pago, 28)) if hoy.day <= dia_pago else \
                (hoy.replace(day=1) + timedelta(days=32)).replace(day=min(dia_pago, 28))
            dias = (proxima - hoy).days
            fecha_prox = proxima.isoformat()
        elif tipo_pago == "unico" and fecha_limite:
            proxima = datetime.strptime(fecha_limite, "%Y-%m-%d").date()
            dias = (proxima - hoy).days
            fecha_prox = fecha_limite
        else:
            dias, fecha_prox = None, "sin fecha"
        if prioritaria and prioritaria[0] == did and cuota_estimada_usdt > 0:
            cuota_estimada = round(convertir_de_usdt(cuota_estimada_usdt, moneda), 2)
            linea_cuota_est = f"  Cuota estimada ahora ({estrategia_usar.upper()}): {cuota_estimada} {moneda}\n"
        elif prioritaria and prioritaria[0] != did:
            linea_cuota_est = f"  Cuota estimada ahora: $0 -- se le paga primero a '{prioritaria[1]}'\n"
        else:
            linea_cuota_est = ""
        bloque = (f"{nombre}\n  Monto pendiente: {pendiente} {moneda}\n{linea_cuota_est}"
                  f"  Cuota promedio real (histórico): {cuota_prom} {moneda}\n  Pagos hechos: {n_pagos}\n"
                  f"  Próximo pago: {fecha_prox}" + (f" (en {dias} días)" if dias is not None else ""))
        bloques.append(bloque)
    con.close()
    render("\n\n".join(bloques), [[("Volver", "deuda:menu")]])


def deuda_moneda_callback(moneda):
    ESTADO["datos"]["moneda"] = moneda
    ESTADO["paso"] = "interes"
    render("¿Porcentaje de interés mensual? (0 si no tiene)", pedir_texto=True, teclado_numero=True)


def deuda_tipopago_callback(tipo_pago):
    ESTADO["datos"]["tipo_pago"] = tipo_pago
    if tipo_pago == "cuotas":
        pedir_fecha("¿Qué día se reinicia el cobro cada mes? (usa cualquier fecha con ese día, ej. 2026-01-15 para día 15)",
                    "deuda_reinicio")
    else:
        pedir_fecha("¿Fecha límite?", "deuda_nueva")


def deuda_guardar(datos, fecha_seleccionada, dia_pago_directo=None):
    con = conectar()
    mes_actual = datetime.now(UTC_MENOS_4).strftime("%Y-%m")
    fecha_limite = None
    dia_pago = None
    if datos.get("tipo_pago") == "cuotas":
        dia_pago = dia_pago_directo
    else:
        fecha_limite = fecha_seleccionada
    cur = con.execute(
        "INSERT INTO deudas (nombre, monto_total, monto_pagado, moneda, interes_mensual, fecha_limite, "
        "tipo_pago, monto_cuota, dia_pago, ultimo_interes_fecha) VALUES (?, ?, 0, ?, ?, ?, ?, NULL, ?, ?)",
        (datos["nombre"], datos["monto_total"], datos["moneda"], datos["interes_mensual"], fecha_limite,
         datos["tipo_pago"], dia_pago, mes_actual))
    nueva_deuda_id = cur.lastrowid
    con.commit()
    terminar_flujo()
    if datos["tipo_pago"] == "cuotas" and dia_pago:
        texto = calcular_resumen_cuotas(con, nueva_deuda_id, datos["nombre"], datos["monto_total"], datos["moneda"], dia_pago)
    elif datos["tipo_pago"] == "cuotas":
        texto = f"Deuda '{datos['nombre']}' creada: {datos['monto_total']} {datos['moneda']} (sin día de reinicio)."
    else:
        extra = f", vence {fecha_limite}" if fecha_limite else ""
        texto = f"Deuda '{datos['nombre']}' creada: {datos['monto_total']} {datos['moneda']}{extra}."
    con.close()
    sonido("exito")
    render(texto, [[("Menú", "menu:main")]])


def calcular_resumen_cuotas(con, deuda_id, nombre, monto_total, moneda, dia_pago):
    cfg = con.execute("SELECT colchon_meta, colchon_actual, estrategia_activa FROM config_estrategia WHERE id=1").fetchone()
    colchon_meta, colchon_actual, estrategia_activa = cfg
    estatus_info = estatus_calcular(con)
    estatus_actual = estatus_info["estado"]
    saldo_total_usdt = estatus_info["saldo_total_usdt"]
    estrategia_usar = "live" if estatus_actual == "Crítico" else estrategia_activa
    tabla = ESTRATEGIAS.get(estrategia_usar, ESTRATEGIAS["medium"])
    pct_deuda = tabla["fase1"][1] if colchon_actual < colchon_meta else tabla["fase2"][0]
    hoy = datetime.now(UTC_MENOS_4).date()
    proxima = hoy.replace(day=min(dia_pago, 28)) if hoy.day <= dia_pago else \
        (hoy.replace(day=1) + timedelta(days=32)).replace(day=min(dia_pago, 28))
    dias_restantes = (proxima - hoy).days
    prioritaria = calcular_deuda_mayor_interes(con)
    lineas = [f"Deuda '{nombre}' creada: {monto_total} {moneda}, se reinicia el día {dia_pago} de cada mes.", ""]
    if prioritaria and prioritaria[0] != deuda_id:
        lineas.append(f"Todavía no le va a tocar abono -- primero se está pagando '{prioritaria[1]}' (mayor interés).")
        lineas.append(f"Próximo pago: día {dia_pago} (en {dias_restantes} días)")
        return "\n".join(lineas)
    lineas.append(f"Estatus actual: {estatus_actual} -- estrategia en uso: {estrategia_usar.upper()} "
                  f"({pct_deuda*100:.0f}% va a deuda)")
    if saldo_total_usdt > 0:
        cuota_estimada_usdt = saldo_total_usdt * pct_deuda
        cuota_estimada = round(convertir_de_usdt(cuota_estimada_usdt, moneda), 2)
        n_cuotas = ceil(monto_total / cuota_estimada) if cuota_estimada > 0 else None
        lineas.append(f"Cuota estimada (según tu saldo total actual): {cuota_estimada} {moneda}")
        if n_cuotas:
            lineas.append(f"Cuotas estimadas para saldarla: {n_cuotas}")
            fecha_limite_estimada = sumar_meses(hoy, n_cuotas).replace(day=min(dia_pago, 28))
            con.execute("UPDATE deudas SET fecha_limite=? WHERE id=?", (fecha_limite_estimada.isoformat(), deuda_id))
            con.commit()
            lineas.append(f"Fecha límite estimada: {fecha_limite_estimada.isoformat()} "
                          f"(cambia según tu Estatus/saldo -- 'Actualizar' la refresca)")
        else:
            lineas.append("Tu saldo total es 0 -- en cuanto tengas saldo en alguna cuenta, esta cuota se calcula sola.")
    lineas.append(f"Próximo pago: día {dia_pago} (en {dias_restantes} días)")
    return "\n".join(lineas)


def deuda_pagada_menu():
    con = conectar()
    deudas = con.execute("SELECT id, nombre FROM deudas WHERE estado='activa'").fetchall()
    con.close()
    if not deudas:
        render("No tienes deudas activas.", [[("Volver", "deuda:menu")]])
        return
    filas = [[(n, f"deuda:pagadaid:{i}")] for i, n in deudas]
    filas.append([("Volver", "deuda:menu")])
    render("¿Cuál marcar como pagada?", filas)


def deuda_pagada_confirmar(deuda_id):
    con = conectar()
    con.execute("UPDATE deudas SET estado='pagada', monto_pagado=monto_total WHERE id=?", (deuda_id,))
    con.commit()
    con.close()
    sonido("exito")
    render("Deuda marcada como pagada.", [[("Menú", "menu:main")]])


# ==================== MÓDULO: PAGOS MENSUALES (gastos fijos) ====================

def pagos_menu():
    render("¿Qué quieres hacer?",
           [[("Ver estado", "pago:ver"), ("Nuevo", "pago:nuevo")], [("Editar", "pago:editar"), ("Pausar", "pago:pausar")],
            [("Borrar", "pago:borrar")], [("Volver", "menu:main")]])


def pago_borrar_menu():
    con = conectar()
    pagos = con.execute("SELECT id, nombre FROM pagos_mensuales").fetchall()
    con.close()
    if not pagos:
        render("No tienes gastos fijos configurados.", [[("Volver", "pago:menu")]])
        return
    filas = [[(n, f"pago:borrarid:{i}")] for i, n in pagos]
    filas.append([("Volver", "pago:menu")])
    render("¿Cuál quieres borrar?", filas)


def pago_borrar_confirmar_menu(pago_id):
    con = conectar()
    fila = con.execute("SELECT nombre FROM pagos_mensuales WHERE id=?", (pago_id,)).fetchone()
    con.close()
    if not fila:
        render("Ese gasto fijo ya no existe.", [[("Menú", "menu:main")]])
        return
    render(f"¿Borrar '{fila[0]}' para siempre?", [[("Sí, borrar", f"pago:borrarconfirmar:{pago_id}"), ("No", "pago:menu")]])


def pago_borrar_ejecutar(pago_id):
    con = conectar()
    con.execute("DELETE FROM pagos_mensuales WHERE id=?", (pago_id,))
    con.commit()
    con.close()
    sonido("borrar")
    render("Gasto fijo borrado.", [[("Menú", "menu:main")]])


def pagos_ver():
    con = conectar()
    filas_db = con.execute(
        "SELECT nombre, monto, moneda, frecuencia, dia_vence, dia_semana, recargo, activo, prioridad "
        "FROM pagos_mensuales").fetchall()
    con.close()
    if not filas_db:
        texto = "No tienes gastos fijos configurados."
    else:
        lineas = []
        for n, monto, moneda, frecuencia, dia, dia_semana, recargo, activo, prioridad in filas_db:
            estado_txt = "" if activo else " (pausado)"
            if frecuencia == "diario":
                lineas.append(f"{n}: {monto} {moneda}, diario, prioridad {prioridad}{estado_txt}")
            elif frecuencia == "semanal":
                lineas.append(f"{n}: {monto} {moneda}, cada {DIAS_SEMANA[dia_semana]}, prioridad {prioridad}{estado_txt}")
            else:
                extra = f", recargo {recargo} si se atrasa" if recargo else ""
                lineas.append(f"{n}: {monto} {moneda}, día {dia}{extra}, prioridad {prioridad}{estado_txt}")
        texto = "Gastos fijos:\n" + "\n".join(lineas)
    render(texto, [[("Volver", "pago:menu")]])


def pago_nuevo_iniciar():
    iniciar_flujo("pago_nuevo", "nombre")
    render("¿Nombre del gasto fijo?", pedir_texto=True)


def pago_nuevo_texto(texto):
    d = ESTADO["datos"]
    if ESTADO["paso"] == "nombre":
        d["nombre"] = texto.strip()
        ESTADO["paso"] = "monto"
        render("¿Monto?", pedir_texto=True, teclado_numero=True)
        return
    if ESTADO["paso"] == "monto":
        try:
            d["monto"] = parsear_monto(texto)
        except ValueError:
            render("Escribe solo el número.", pedir_texto=True, teclado_numero=True)
            return
        ESTADO["paso"] = "moneda"
        render("¿Moneda?", [[("USD", "pago:moneda:USD"), ("USDT", "pago:moneda:USDT"), ("VES", "pago:moneda:VES")]])
        return
    if ESTADO["paso"] == "dia":
        try:
            dia = int(texto.strip())
            assert 1 <= dia <= 31
        except (ValueError, AssertionError):
            render("Escribe un número de día válido (1-31).", pedir_texto=True, teclado_numero=True)
            return
        d["dia_vence"] = dia
        ESTADO["paso"] = "recargo"
        render("¿Recargo por atraso? (0 si no hay)", pedir_texto=True, teclado_numero=True)
        return
    if ESTADO["paso"] == "recargo":
        try:
            d["recargo"] = parsear_monto(texto)
        except ValueError:
            render("Escribe solo el número.", pedir_texto=True, teclado_numero=True)
            return
        con = conectar()
        con.execute("INSERT INTO pagos_mensuales (nombre, monto, moneda, frecuencia, dia_vence, recargo) "
                    "VALUES (?,?,?,'mensual',?,?)", (d["nombre"], d["monto"], d["moneda"], d["dia_vence"], d["recargo"]))
        con.commit()
        con.close()
        terminar_flujo()
        extra_recargo = f", recargo {d['recargo']} si se atrasa" if d["recargo"] else ""
        sonido("exito")
        render(f"Gasto fijo mensual '{d['nombre']}' creado: {d['monto']} {d['moneda']}, día {d['dia_vence']}{extra_recargo}.",
               [[("Menú", "menu:main")]])


def pago_recurrente_categoria_callback(categoria):
    d = ESTADO["datos"]
    d["categoria"] = categoria
    frecuencia = "cada semana" if d["frecuencia"] == "semanal" else "cada día"
    pedir_cuenta(f"¿De qué cuenta sale {frecuencia}?", "pago:cuentarec:")


def pago_recurrente_cuenta_callback(cuenta_id):
    d = ESTADO["datos"]
    d["cuenta_id"] = cuenta_id
    if d["frecuencia"] == "semanal":
        filas = [[(dd, f"pago:diasemana:{i}")] for i, dd in enumerate(DIAS_SEMANA)]
        render("¿Qué día de la semana?", filas)
    else:
        pago_recurrente_guardar(d)


def pago_dia_semana_callback(dia_semana):
    ESTADO["datos"]["dia_semana"] = dia_semana
    pago_recurrente_guardar(ESTADO["datos"])


def pago_recurrente_guardar(d):
    con = conectar()
    prioridad = 1 if d["categoria"] == "Comida" else 3
    con.execute("INSERT INTO pagos_mensuales (nombre, monto, moneda, frecuencia, cuenta_id, categoria, dia_semana, prioridad) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (d["nombre"], d["monto"], d["moneda"], d["frecuencia"], d["cuenta_id"], d["categoria"],
                 d.get("dia_semana"), prioridad))
    con.commit()
    con.close()
    terminar_flujo()
    extra = f", cada {DIAS_SEMANA[d['dia_semana']]}" if d["frecuencia"] == "semanal" else ", todos los días"
    sonido("exito")
    render(f"Gasto fijo '{d['nombre']}' creado: {d['monto']} {d['moneda']}, categoría {d['categoria']}{extra}, "
           f"prioridad {prioridad}.\nSe registra solo.", [[("Menú", "menu:main")]])


def pago_editar_menu():
    con = conectar()
    pagos = con.execute("SELECT id, nombre FROM pagos_mensuales").fetchall()
    con.close()
    if not pagos:
        render("No tienes gastos fijos configurados.", [[("Volver", "pago:menu")]])
        return
    filas = [[(n, f"pago:editarid:{i}")] for i, n in pagos]
    filas.append([("Volver", "pago:menu")])
    render("¿Cuál quieres editar?", filas)


def pago_editar_campos(pago_id):
    con = conectar()
    frecuencia = con.execute("SELECT frecuencia FROM pagos_mensuales WHERE id=?", (pago_id,)).fetchone()[0]
    con.close()
    campos = [("Nombre", "nombre"), ("Monto", "monto"), ("Moneda", "moneda")]
    if frecuencia == "mensual":
        campos += [("Día del mes", "dia_vence"), ("Recargo", "recargo")]
    else:
        campos += [("Categoría", "categoria"), ("Cuenta", "cuenta")]
        if frecuencia == "semanal":
            campos.append(("Día de la semana", "diasemana"))
    campos.append(("Prioridad", "prioridad"))
    filas = [[(label, f"pago:editarcampo:{pago_id}:{campo}")] for label, campo in campos]
    filas.append([("Volver", "pago:editar")])
    render("¿Qué quieres cambiar?", filas)


def pago_editar_campo_elegido(pago_id, campo):
    if campo == "moneda":
        render("¿Nueva moneda?",
               [[("USD", f"pago:editarvalor:{pago_id}:moneda:USD"), ("USDT", f"pago:editarvalor:{pago_id}:moneda:USDT"),
                 ("VES", f"pago:editarvalor:{pago_id}:moneda:VES")]])
    elif campo == "categoria":
        filas = [[(c, f"pago:editarvalor:{pago_id}:categoria:{c}")] for c in CATEGORIAS_GASTO]
        render("¿Nueva categoría?", filas)
    elif campo == "cuenta":
        pedir_cuenta("¿Nueva cuenta?", f"pago:editarvalor:{pago_id}:cuenta:")
    elif campo == "diasemana":
        filas = [[(dd, f"pago:editarvalor:{pago_id}:diasemana:{i}")] for i, dd in enumerate(DIAS_SEMANA)]
        render("¿Nuevo día?", filas)
    elif campo == "prioridad":
        render("¿Nueva prioridad? (1 = esencial, 3 = lo primero que se pausa)",
               [[("1", f"pago:editarvalor:{pago_id}:prioridad:1"), ("2", f"pago:editarvalor:{pago_id}:prioridad:2"),
                 ("3", f"pago:editarvalor:{pago_id}:prioridad:3")]])
    else:
        iniciar_flujo("pago_editar", campo, {"pago_id": pago_id})
        preguntas = {"nombre": "¿Nuevo nombre?", "monto": "¿Nuevo monto?",
                     "dia_vence": "¿Nuevo día del mes? (1-31)", "recargo": "¿Nuevo recargo?"}
        render(preguntas[campo], pedir_texto=True, teclado_numero=(campo != "nombre"))


def pago_editar_valor_callback(pago_id, campo, valor):
    columna = {"cuenta": "cuenta_id", "diasemana": "dia_semana"}.get(campo, campo)
    valor_final = int(valor) if columna in ("cuenta_id", "dia_semana", "prioridad") else valor
    con = conectar()
    con.execute(f"UPDATE pagos_mensuales SET {columna}=? WHERE id=?", (valor_final, pago_id))
    con.commit()
    con.close()
    sonido("exito")
    render("Actualizado.", [[("Menú", "menu:main")]])


def pago_editar_texto(texto):
    pago_id = ESTADO["datos"]["pago_id"]
    campo = ESTADO["paso"]
    if campo == "nombre":
        valor = texto.strip()
    elif campo in ("monto", "recargo"):
        try:
            valor = parsear_monto(texto)
        except ValueError:
            render("Escribe solo el número.", pedir_texto=True, teclado_numero=True)
            return
    elif campo == "dia_vence":
        try:
            valor = int(texto.strip())
            assert 1 <= valor <= 31
        except (ValueError, AssertionError):
            render("Escribe un número de día válido (1-31).", pedir_texto=True, teclado_numero=True)
            return
    else:
        return
    con = conectar()
    con.execute(f"UPDATE pagos_mensuales SET {campo}=? WHERE id=?", (valor, pago_id))
    con.commit()
    con.close()
    terminar_flujo()
    sonido("exito")
    render("Actualizado.", [[("Menú", "menu:main")]])


def pago_pausar_menu():
    con = conectar()
    pagos = con.execute("SELECT id, nombre, activo FROM pagos_mensuales").fetchall()
    con.close()
    filas = [[(f"{n} ({'activo' if a else 'pausado'})", f"pago:pausarid:{i}")] for i, n, a in pagos]
    filas.append([("Volver", "pago:menu")])
    render("¿Cuál pausar/reactivar?", filas)


def pago_pausar_confirmar(pago_id):
    con = conectar()
    actual = con.execute("SELECT activo FROM pagos_mensuales WHERE id=?", (pago_id,)).fetchone()[0]
    con.execute("UPDATE pagos_mensuales SET activo=? WHERE id=?", (0 if actual else 1, pago_id))
    con.commit()
    con.close()
    sonido("exito")
    render("Actualizado.", [[("Menú", "menu:main")]])


def pago_pausar_prioridad3():
    con = conectar()
    con.execute("UPDATE pagos_mensuales SET activo=0 WHERE activo=1 AND prioridad=3")
    con.commit()
    con.close()
    sonido("exito")
    render("Gastos de prioridad 3 pausados.", [[("Menú", "menu:main")]])


# ==================== MÓDULO: POR COBRAR ====================

def porcobrar_menu():
    render("¿Qué quieres hacer?",
           [[("Préstamo", "pc:prestamo"), ("Por cobrar", "pc:cobrar")], [("Pagado", "pc:pagado")],
            [("Volver", "menu:main")]])


def prestamo_iniciar():
    iniciar_flujo("prestamo", "monto")
    render("¿Cuánto?", pedir_texto=True, teclado_numero=True)


def cobrar_iniciar():
    iniciar_flujo("porcobrar_nuevo", "monto")
    render("¿Cuánto te deben?", pedir_texto=True, teclado_numero=True)


def porcobrar_texto(texto):
    d = ESTADO["datos"]
    flujo = ESTADO["flujo"]
    if ESTADO["paso"] == "monto":
        try:
            d["monto"] = parsear_monto(texto)
        except ValueError:
            render("Escribe solo el número.", pedir_texto=True, teclado_numero=True)
            return
        ESTADO["paso"] = "moneda"
        prefijo = "prestamo" if flujo == "prestamo" else "pc"
        render("¿Moneda?", [[("USD", f"{prefijo}:moneda:USD"), ("USDT", f"{prefijo}:moneda:USDT"),
                             ("VES", f"{prefijo}:moneda:VES")]])
        return
    if ESTADO["paso"] == "descripcion":
        d["descripcion"] = texto.strip()
        if flujo == "prestamo":
            con = conectar()
            cuenta = con.execute("SELECT nombre, saldo, moneda FROM cuentas WHERE id=?", (d["cuenta_id"],)).fetchone()
            delta_usdt = convertir_a_usdt(d["monto"], d["moneda"])
            delta_en_moneda = delta_usdt * obtener_tasas()["paralelo"] if cuenta[2] == "VES" else delta_usdt
            nuevo_saldo = cuenta[1] - delta_en_moneda
            con.execute("UPDATE cuentas SET saldo=? WHERE id=?", (nuevo_saldo, d["cuenta_id"]))
            con.execute("INSERT INTO por_cobrar (tipo, monto_original, monto_pendiente, moneda, descripcion, "
                        "cuenta_origen_id, estado, fecha) VALUES ('prestamo', ?, ?, ?, ?, ?, 'pendiente', ?)",
                        (d["monto"], d["monto"], d["moneda"], d["descripcion"], d["cuenta_id"],
                         datetime.now(UTC_MENOS_4).isoformat()))
            con.commit()
            con.close()
            terminar_flujo()
            sonido("exito")
            render(f"Préstamo registrado: {d['monto']} {d['moneda']} ({d['descripcion']}) -- salió de {cuenta[0]}.",
                   [[("Menú", "menu:main")]])
        else:
            con = conectar()
            con.execute("INSERT INTO por_cobrar (tipo, monto_original, monto_pendiente, moneda, descripcion, "
                        "cuenta_origen_id, estado, fecha) VALUES ('cobrar', ?, ?, ?, ?, NULL, 'pendiente', ?)",
                        (d["monto"], d["monto"], d["moneda"], d["descripcion"], datetime.now(UTC_MENOS_4).isoformat()))
            con.commit()
            con.close()
            terminar_flujo()
            sonido("exito")
            render(f"Anotado: {d['monto']} {d['moneda']} por cobrar ({d['descripcion']}).", [[("Menú", "menu:main")]])


def porcobrar_moneda_callback(moneda):
    ESTADO["datos"]["moneda"] = moneda
    if ESTADO["flujo"] == "prestamo":
        ESTADO["paso"] = "cuenta"
        pedir_cuenta("¿De qué cuenta sale?", "prestamo:cuenta:")
    else:
        ESTADO["paso"] = "descripcion"
        render("¿De quién / por qué?", pedir_texto=True)


def prestamo_cuenta_callback(cuenta_id):
    ESTADO["datos"]["cuenta_id"] = cuenta_id
    ESTADO["paso"] = "descripcion"
    render("¿A quién / para qué?", pedir_texto=True)


def pagado_menu():
    con = conectar()
    pendientes = con.execute(
        "SELECT id, descripcion, monto_pendiente, moneda FROM por_cobrar WHERE estado='pendiente'").fetchall()
    con.close()
    if not pendientes:
        render("No tienes nada pendiente por cobrar.", [[("Volver", "pc:menu")]])
        return
    filas = [[(f"{desc} -- {monto} {moneda}", f"pagado:elegir:{i}")] for i, desc, monto, moneda in pendientes]
    filas.append([("Volver", "pc:menu")])
    render("¿Cuál pagaron?", filas)


def pagado_elegir(item_id):
    iniciar_flujo("pagado", "opcion", {"item_id": item_id})
    render("¿Completo o monto diferente?",
           [[("Completo", f"pagado:completo:{item_id}"), ("Monto diferente", f"pagado:diferente:{item_id}")]])


def pagado_aplicar(con, item_id, monto_pagado_ahora, cuenta_id):
    fila = con.execute("SELECT monto_pendiente, moneda FROM por_cobrar WHERE id=?", (item_id,)).fetchone()
    nuevo_pendiente = round(fila[0] - monto_pagado_ahora, 2)
    if nuevo_pendiente <= 0:
        con.execute("UPDATE por_cobrar SET estado='pagado', monto_pendiente=0 WHERE id=?", (item_id,))
        nuevo_pendiente = 0
    else:
        con.execute("UPDATE por_cobrar SET monto_pendiente=? WHERE id=?", (nuevo_pendiente, item_id))
    cuenta = con.execute("SELECT saldo, moneda FROM cuentas WHERE id=?", (cuenta_id,)).fetchone()
    monto_usdt = convertir_a_usdt(monto_pagado_ahora, fila[1])
    delta_en_moneda = monto_usdt * obtener_tasas()["paralelo"] if cuenta[1] == "VES" else monto_usdt
    con.execute("UPDATE cuentas SET saldo=saldo+? WHERE id=?", (delta_en_moneda, cuenta_id))
    con.commit()
    return nuevo_pendiente


def _pagado_pedir_cuenta():
    pedir_cuenta("¿A qué cuenta entra este pago?", "pagado:cuenta:")


def pagado_completo_callback(item_id):
    con = conectar()
    monto_pendiente_antes = con.execute("SELECT monto_pendiente FROM por_cobrar WHERE id=?", (item_id,)).fetchone()[0]
    con.close()
    ESTADO["datos"] = {"item_id": item_id, "monto": monto_pendiente_antes}
    _pagado_pedir_cuenta()


def pagado_diferente_iniciar(item_id):
    ESTADO["paso"] = "monto_diferente"
    ESTADO["datos"]["item_id"] = item_id
    render("¿Cuánto te pagaron?", pedir_texto=True, teclado_numero=True)


def pagado_texto(texto):
    if ESTADO["paso"] != "monto_diferente":
        return
    try:
        monto = parsear_monto(texto)
    except ValueError:
        render("Escribe solo el número.", pedir_texto=True, teclado_numero=True)
        return
    ESTADO["datos"]["monto"] = monto
    _pagado_pedir_cuenta()


def pagado_cuenta_callback(cuenta_id):
    d = ESTADO["datos"]
    con = conectar()
    nuevo_pendiente = pagado_aplicar(con, d["item_id"], d["monto"], cuenta_id)
    cuenta_nombre = con.execute("SELECT nombre FROM cuentas WHERE id=?", (cuenta_id,)).fetchone()[0]
    con.close()
    terminar_flujo()
    sonido("exito")
    if nuevo_pendiente > 0:
        render(f"Abono registrado: {d['monto']}. Queda pendiente: {nuevo_pendiente}. Se sumó a {cuenta_nombre}.",
               [[("Menú", "menu:main")]])
    else:
        render(f"Cobrado: {d['monto']}. Quedó saldado. Se sumó a {cuenta_nombre}.", [[("Menú", "menu:main")]])


# ==================== MÓDULO: OBJETIVOS ====================

def objetivos_menu():
    render("¿Qué quieres hacer?",
           [[("Ver estado", "obj:ver"), ("Nuevo", "obj:nuevo")], [("Marcar cumplido", "obj:cumplido")],
            [("Volver", "menu:main")]])


def objetivos_ver():
    con = conectar()
    filas_db = con.execute(
        "SELECT nombre, monto_meta, monto_actual, moneda, fecha_limite FROM objetivos WHERE estado='activo'").fetchall()
    con.close()
    if not filas_db:
        texto = "No tienes objetivos activos."
    else:
        lineas = []
        for n, meta, actual, moneda, limite in filas_db:
            extra = f", vence {limite}" if limite else ""
            lineas.append(f"{n}: {round(actual, 2)} de {meta} {moneda}{extra}")
        texto = "Objetivos activos:\n" + "\n".join(lineas)
    render(texto, [[("Volver", "obj:menu")]])


def objetivo_nuevo_iniciar():
    iniciar_flujo("objetivo_nuevo", "nombre")
    render("¿Nombre del objetivo?", pedir_texto=True)


def objetivo_nuevo_texto(texto):
    d = ESTADO["datos"]
    if ESTADO["paso"] == "nombre":
        d["nombre"] = texto.strip()
        ESTADO["paso"] = "monto_meta"
        render("¿Cuánto quieres juntar?", pedir_texto=True, teclado_numero=True)
        return
    if ESTADO["paso"] == "monto_meta":
        try:
            d["monto_meta"] = parsear_monto(texto)
        except ValueError:
            render("Escribe solo el número.", pedir_texto=True, teclado_numero=True)
            return
        ESTADO["paso"] = "moneda"
        render("¿Moneda?", [[("USD", "obj:moneda:USD"), ("USDT", "obj:moneda:USDT"), ("VES", "obj:moneda:VES")]])
        return
    if ESTADO["paso"] == "_fecha_texto":
        _procesar_fecha_texto(texto)


def objetivo_moneda_callback(moneda):
    ESTADO["datos"]["moneda"] = moneda
    pedir_fecha("¿Fecha límite?", "objetivo_nuevo")


def objetivo_guardar(datos, fecha_limite):
    con = conectar()
    con.execute("INSERT INTO objetivos (nombre, monto_meta, monto_actual, moneda, fecha_limite) VALUES (?, ?, 0, ?, ?)",
                (datos["nombre"], datos["monto_meta"], datos["moneda"], fecha_limite))
    con.commit()
    con.close()
    terminar_flujo()
    extra = f", vence {fecha_limite}" if fecha_limite else ""
    sonido("exito")
    render(f"Objetivo '{datos['nombre']}' creado: {datos['monto_meta']} {datos['moneda']}{extra}.", [[("Menú", "menu:main")]])


def objetivo_cumplido_menu():
    con = conectar()
    objetivos = con.execute("SELECT id, nombre FROM objetivos WHERE estado='activo'").fetchall()
    con.close()
    if not objetivos:
        render("No tienes objetivos activos.", [[("Volver", "obj:menu")]])
        return
    filas = [[(n, f"obj:cumplidoid:{i}")] for i, n in objetivos]
    filas.append([("Volver", "obj:menu")])
    render("¿Cuál marcar como cumplido?", filas)


def objetivo_cumplido_confirmar(objetivo_id):
    con = conectar()
    con.execute("UPDATE objetivos SET estado='cumplido', monto_actual=monto_meta WHERE id=?", (objetivo_id,))
    con.commit()
    con.close()
    sonido("exito")
    render("Objetivo marcado como cumplido.", [[("Menú", "menu:main")]])


# ==================== MÓDULO: RECORDATORIOS ====================

def recordatorios_menu():
    render("¿Qué quieres ver?", [[("Próximos avisos", "rec:proximos"), ("Ajustar aviso", "rec:ajustar")],
                                 [("Horarios de avisos", "sys:horarios")],
                                 [("Volver", "menu:main")]])


def recordatorios_proximos():
    con = conectar()
    lineas = []
    hoy = datetime.now(UTC_MENOS_4).date()
    for nombre, limite in con.execute("SELECT nombre, fecha_limite FROM deudas WHERE estado='activa'").fetchall():
        if limite:
            dias = (datetime.strptime(limite, "%Y-%m-%d").date() - hoy).days
            lineas.append(f"{nombre} (Deuda): vence en {dias} días" if dias >= 0 else
                          f"{nombre} (Deuda): vencida hace {-dias} días")
        else:
            lineas.append(f"{nombre} (Deuda): sin fecha límite")
    for nombre, dia in con.execute(
            "SELECT nombre, dia_vence FROM pagos_mensuales WHERE activo=1 AND frecuencia='mensual'").fetchall():
        proximo = hoy.replace(day=min(dia, 28)) if hoy.day <= dia else \
            (hoy.replace(day=1) + timedelta(days=32)).replace(day=min(dia, 28))
        dias = (proximo - hoy).days
        lineas.append(f"{nombre} (Gasto fijo mensual): vence en {dias} días")
    for desc, monto, moneda in con.execute(
            "SELECT descripcion, monto_pendiente, moneda FROM por_cobrar WHERE estado='pendiente'").fetchall():
        lineas.append(f"{desc} (Por cobrar): {monto} {moneda}, sin fecha")
    con.close()
    texto = "\n".join(lineas) if lineas else "No hay nada pendiente."
    render(texto, [[("Volver", "rec:menu")]])


def recordatorios_ajustar_menu():
    con = conectar()
    items = []
    for i, n in con.execute("SELECT id, nombre FROM deudas WHERE estado='activa'").fetchall():
        items.append(("deuda", i, n))
    for i, n in con.execute("SELECT id, nombre FROM pagos_mensuales WHERE activo=1").fetchall():
        items.append(("pago_mensual", i, n))
    con.close()
    filas = [[(n, f"rec:elegir:{t}:{i}")] for t, i, n in items]
    filas.append([("Volver", "rec:menu")])
    render("¿Cuál?", filas)


def recordatorios_ajustar_iniciar(tipo, item_id):
    iniciar_flujo("ajustar_aviso", "dias", {"tipo": tipo, "item_id": item_id})
    render("¿Cuántos días antes te aviso?", pedir_texto=True, teclado_numero=True)


def ajustar_aviso_texto(texto):
    try:
        dias = int(texto.strip())
    except ValueError:
        render("Escribe solo el número de días.", pedir_texto=True, teclado_numero=True)
        return
    con = conectar()
    con.execute("INSERT INTO recordatorio_ajustes (tipo, item_id, dias_antes) VALUES (?,?,?) "
                "ON CONFLICT(tipo, item_id) DO UPDATE SET dias_antes=excluded.dias_antes",
                (ESTADO["datos"]["tipo"], ESTADO["datos"]["item_id"], dias))
    con.commit()
    con.close()
    terminar_flujo()
    sonido("exito")
    render(f"Listo, te aviso {dias} días antes.", [[("Menú", "menu:main")]])


# ==================== MÓDULO: RESUMEN ====================

PERIODO_TEXTO = {"diario": "hoy", "semanal": "últimos 7 días", "mensual": "últimos 30 días"}
PERIODO_DIAS = {"diario": 1, "semanal": 7, "mensual": 30}


def resumen_menu():
    render("¿Ingresos o gastos?", [[("Ingresos", "resumen:tipo:ingreso"), ("Gastos", "resumen:tipo:gasto")],
                                   [("Volver", "menu:main")]])


def resumen_periodo_menu(tipo):
    render("¿Diario, semanal o mensual?",
           [[("Diario", f"resumen:ver:{tipo}:diario"), ("Semanal", f"resumen:ver:{tipo}:semanal"),
             ("Mensual", f"resumen:ver:{tipo}:mensual")], [("Volver", "resumen:menu")]])


def resumen_mostrar(tipo, periodo):
    con = conectar()
    if periodo == "diario":
        desde = datetime.now(UTC_MENOS_4).strftime("%Y-%m-%d")
    else:
        desde = (datetime.now(UTC_MENOS_4) - timedelta(days=PERIODO_DIAS[periodo])).isoformat()
    filas_db = con.execute("SELECT categoria, monto, moneda, monto_usdt FROM movimientos WHERE tipo=? AND fecha >= ?",
                           (tipo, desde)).fetchall()
    con.close()
    tipo_label = "Ingresos" if tipo == "ingreso" else "Gastos"
    if not filas_db:
        texto = f"No hay {tipo_label.lower()} registrados en {PERIODO_TEXTO[periodo]}."
    else:
        por_categoria_usdt, por_moneda_real, total_usdt = {}, {}, 0.0
        for categoria, monto, moneda, monto_usdt in filas_db:
            por_categoria_usdt[categoria] = por_categoria_usdt.get(categoria, 0) + monto_usdt
            por_moneda_real[moneda] = por_moneda_real.get(moneda, 0) + monto
            total_usdt += monto_usdt
        lineas = [f"{tipo_label} ({PERIODO_TEXTO[periodo]}):", ""]
        for cat, monto in por_categoria_usdt.items():
            lineas.append(f"{cat}: {round(monto, 2)} USDT")
        lineas.append("")
        lineas.append("En la moneda real que usaste:")
        for moneda_real, monto in por_moneda_real.items():
            lineas.append(f"  {round(monto, 2)} {moneda_real}")
        lineas.append("")
        lineas.append(f"Total: {round(total_usdt, 2)} USDT")
        texto = "\n".join(lineas)
    render(texto, [[("Volver", "resumen:menu")]])


# ==================== APP ====================

class JoiApp(App):
    def build(self):
        iniciar_db()
        sm = ScreenManager()
        global PANTALLA
        PANTALLA = MainScreen(name="main")
        sm.add_widget(PANTALLA)
        PANTALLA.build()
        return sm


if __name__ == "__main__":
    JoiApp().run()
