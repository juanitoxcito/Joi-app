"""
Joi -- servicio de alarmas (Fase 3).
Este script NO es la app -- es un proceso aparte y liviano que Android
despierta a la hora programada (mañana/mediodía/noche), sin abrir toda
la interfaz. Calcula el aviso, muestra la notificación, se reprograma
para el día siguiente, y se apaga solo.

Sin imports de Kivy a propósito -- en un servicio de fondo no hay
pantalla, y cargar Kivy aquí sería lento e innecesario.
"""
import os
import time
import sqlite3
from datetime import datetime, timedelta, timezone

import requests

DB_PATH = "joi.db"
UTC_MENOS_4 = timezone(timedelta(hours=-4))


def conectar():
    return sqlite3.connect(DB_PATH)


# ==================== TASAS Y CONVERSIÓN (igual que en main.py) ====================

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


# ==================== ESTATUS Y TOTALES (subconjunto de main.py) ====================

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
        return {"saldo_total_usdt": round(saldo_total_usdt, 2), "estado": "Sin gastos fijos"}
    semanas = saldo_total_usdt / costo_semanal
    if semanas < 1:
        estado = "Crítico"
    elif semanas < 4:
        estado = "Saludable"
    else:
        estado = "Óptimo"
    return {"saldo_total_usdt": round(saldo_total_usdt, 2), "estado": estado}


def calcular_totales_dia(con):
    hoy = datetime.now(UTC_MENOS_4).strftime("%Y-%m-%d")
    gastos = con.execute(
        "SELECT categoria, SUM(monto_usdt) FROM movimientos WHERE tipo='gasto' AND fecha>=? GROUP BY categoria",
        (hoy,)).fetchall()
    ingresos_total = con.execute(
        "SELECT COALESCE(SUM(monto_usdt),0) FROM movimientos WHERE tipo='ingreso' AND fecha>=?", (hoy,)
    ).fetchone()[0]
    total_gastos = sum(m for _, m in gastos)
    return round(total_gastos, 2), round(ingresos_total, 2)


# ==================== MENSAJE SEGÚN EL TURNO ====================

def construir_mensaje(slot):
    con = conectar()
    r = estatus_calcular(con)
    if slot == "manana":
        titulo = "Joi -- buenos días"
        mensaje = f"Estatus: {r['estado']} ({r['saldo_total_usdt']} USDT en total). Abre la app para confirmar tus cuentas."
    elif slot == "mediodia":
        gastos, ingresos = calcular_totales_dia(con)
        titulo = "Joi -- corte de las 5:30"
        mensaje = f"Hoy llevas: Gastos ${gastos}, Ingresos ${ingresos}. Estatus: {r['estado']}."
    else:
        gastos, ingresos = calcular_totales_dia(con)
        titulo = "Joi -- cierre del día"
        mensaje = f"Gastos ${gastos}, Ingresos ${ingresos}. Estatus: {r['estado']}. ¡Buenas noches!"
    con.close()
    return titulo, mensaje


# ==================== NOTIFICACIÓN Y REPROGRAMACIÓN (contexto: el propio servicio) ====================

def mostrar_notificacion_servicio(titulo, mensaje):
    from jnius import autoclass
    PythonService = autoclass("org.kivy.android.PythonService")
    contexto = PythonService.mService
    Context = autoclass("android.content.Context")
    NotificationManager = autoclass("android.app.NotificationManager")
    NotificationChannel = autoclass("android.app.NotificationChannel")
    NotificationBuilder = autoclass("android.app.Notification$Builder")
    BuildVersion = autoclass("android.os.Build$VERSION")

    servicio_notif = contexto.getSystemService(Context.NOTIFICATION_SERVICE)
    canal_id = "joi_canal"
    if BuildVersion.SDK_INT >= 26:
        canal = NotificationChannel(canal_id, "Joi", NotificationManager.IMPORTANCE_HIGH)
        servicio_notif.createNotificationChannel(canal)
        builder = NotificationBuilder(contexto, canal_id)
    else:
        builder = NotificationBuilder(contexto)
    builder.setContentTitle(titulo)
    builder.setContentText(mensaje)
    builder.setSmallIcon(contexto.getApplicationInfo().icon)
    builder.setAutoCancel(True)
    servicio_notif.notify(2, builder.build())


def reprogramar_para_manana(slot):
    """Vuelve a programar esta misma alarma para dentro de 24 horas,
    para que se repita todos los días."""
    from jnius import autoclass
    PythonService = autoclass("org.kivy.android.PythonService")
    contexto = PythonService.mService
    Context = autoclass("android.content.Context")
    AlarmManager = autoclass("android.app.AlarmManager")
    PendingIntent = autoclass("android.app.PendingIntent")
    Calendar = autoclass("java.util.Calendar")
    ServiceJoialarm = autoclass(contexto.getPackageName() + ".ServiceJoialarm")

    intent = ServiceJoialarm.getDefaultIntent(contexto, "", "Joi", "Aviso programado", slot)
    codigo_peticion = {"manana": 100, "mediodia": 101, "noche": 102}[slot]
    flags = PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
    pendiente = PendingIntent.getService(contexto, codigo_peticion, intent, flags)

    objetivo = Calendar.getInstance()
    objetivo.add(Calendar.DAY_OF_MONTH, 1)

    gestor_alarmas = contexto.getSystemService(Context.ALARM_SERVICE)
    gestor_alarmas.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, objetivo.getTimeInMillis(), pendiente)


# ==================== PUNTO DE ENTRADA DEL SERVICIO ====================

def main():
    slot = os.environ.get("PYTHON_SERVICE_ARGUMENT", "").strip()
    if slot not in ("manana", "mediodia", "noche"):
        print(f"[SERVICIO JOI] Turno desconocido: '{slot}'")
        return
    try:
        titulo, mensaje = construir_mensaje(slot)
        mostrar_notificacion_servicio(titulo, mensaje)
    except Exception as e:
        try:
            mostrar_notificacion_servicio("Joi -- error", f"{type(e).__name__}: {e}")
        except Exception:
            print(f"[SERVICIO JOI] Error: {type(e).__name__}: {e}")
    finally:
        try:
            reprogramar_para_manana(slot)
        except Exception as e:
            print(f"[SERVICIO JOI] No se pudo reprogramar: {e}")


main()
