"""
Puente local HL7 (MLLP → HTTPS) para correr en un PC DENTRO de la unidad renal.

    máquinas AK 98 ──MLLP/TCP──▶ puente ──HTTPS + HMAC──▶ app /api/hl7/mensajes

Qué hace:
  1. Escucha conexiones MLLP (asyncio) de las máquinas.
  2. Valida que cada mensaje sea un ORU^R01 legible y lo guarda en una cola
     durable local (archivo SQLite). Solo entonces responde ACK AA
     («almacenar y reenviar»). Mensajes dañados → AE; tipos no soportados → AR.
  3. Un bucle de envío reenvía la cola a la app por HTTPS con firma
     HMAC-SHA256 + sello de tiempo. Si no hay internet o la app falla,
     reintenta con espera exponencial; nada se pierde al reiniciar el PC.

Seguridad:
  - Los logs NUNCA incluyen datos del paciente ni el mensaje crudo: solo
    id de control, máquina emisora, número de OBX y estados.
  - El archivo de la cola contiene datos clínicos: se crea con permisos 0600 y
    los mensajes ya enviados se purgan tras HL7_PUENTE_RETENCION_DIAS.
  - Solo acepta https:// (http:// únicamente hacia localhost, para pruebas).
  - Lista opcional de IPs permitidas (las máquinas) con --ips-permitidas.
  - Dirección única: el puente nunca envía nada a las máquinas salvo el ACK.

Uso:
    export HL7_BRIDGE_SECRET=...        # el mismo valor configurado en la app
    python -m hl7.puente --url https://mi-app.example/api/hl7/mensajes --puerto 2575

Variables de entorno equivalentes: HL7_APP_URL, HL7_BRIDGE_SECRET, HL7_PUENTE_HOST,
HL7_PUENTE_PUERTO, HL7_PUENTE_COLA, HL7_PUENTE_IPS, HL7_CA_BUNDLE,
HL7_PUENTE_RETENCION_DIAS.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import signal
import sqlite3
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

if __package__ in (None, ""):  # ejecución directa: python hl7/puente.py
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from hl7 import mllp  # noqa: E402
from hl7.firma import cabeceras_firmadas  # noqa: E402
from hl7.parser import ErrorHL7, parsear  # noqa: E402

log = logging.getLogger("hl7.puente")

# Códigos HTTP que indican que el mensaje en sí es inválido: reintentar no sirve.
HTTP_PERMANENTES = {400, 413, 415, 422}


# ── Logging estructurado (sin PHI) ───────────────────────────────────────────

class FormatoJSON(logging.Formatter):
    """Una línea JSON por evento. Solo se registran los campos de `extra=` permitidos."""

    CAMPOS = ("evento", "control_id", "maquina", "obx", "estado", "intentos", "http", "espera_s",
              "pendientes", "error", "origen", "codigo_ack")

    def format(self, record: logging.LogRecord) -> str:
        datos = {"ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"), "nivel": record.levelname,
                 "msg": record.getMessage()}
        for c in self.CAMPOS:
            if hasattr(record, c):
                datos[c] = getattr(record, c)
        return json.dumps(datos, ensure_ascii=False)


def configurar_logging(nivel: str = "INFO") -> None:
    h = logging.StreamHandler()
    h.setFormatter(FormatoJSON())
    raiz = logging.getLogger("hl7")
    raiz.handlers[:] = [h]
    raiz.setLevel(nivel)
    raiz.propagate = False


# ── Cola durable ─────────────────────────────────────────────────────────────

@dataclass
class ItemCola:
    id: int
    control_id: str
    cuerpo: bytes
    intentos: int


class ColaDurable:
    """Cola persistente en SQLite. Sobrevive a reinicios y cortes de red."""

    def __init__(self, ruta: str, *, espera_base: float = 5.0, espera_max: float = 600.0,
                 rng: random.Random | None = None) -> None:
        self.ruta = ruta
        self.espera_base = espera_base
        self.espera_max = espera_max
        self._rng = rng or random.Random()
        self._lock = threading.Lock()
        nueva = ruta != ":memory:" and not os.path.exists(ruta)
        self._con = sqlite3.connect(ruta, check_same_thread=False, isolation_level=None)
        if nueva:
            try:
                os.chmod(ruta, 0o600)
            except OSError:
                pass
        self._con.execute("PRAGMA journal_mode=WAL")
        self._con.execute("""
            CREATE TABLE IF NOT EXISTS cola (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                control_id TEXT NOT NULL UNIQUE,
                cuerpo BLOB NOT NULL,
                estado TEXT NOT NULL DEFAULT 'pendiente',   -- pendiente | enviado | fallido
                intentos INTEGER NOT NULL DEFAULT 0,
                proximo_intento REAL NOT NULL DEFAULT 0,
                ultimo_error TEXT,
                creado_en REAL NOT NULL,
                enviado_en REAL
            )""")

    def encolar(self, control_id: str, cuerpo: bytes, ahora: float | None = None) -> bool:
        """Guarda un mensaje. False si ese id de control ya estaba (reenvío de la máquina)."""
        with self._lock:
            try:
                self._con.execute(
                    "INSERT INTO cola (control_id, cuerpo, creado_en) VALUES (?, ?, ?)",
                    (control_id, cuerpo, ahora if ahora is not None else time.time()))
                return True
            except sqlite3.IntegrityError:
                return False

    def listos(self, ahora: float | None = None, limite: int = 50) -> list[ItemCola]:
        ahora = ahora if ahora is not None else time.time()
        with self._lock:
            filas = self._con.execute(
                "SELECT id, control_id, cuerpo, intentos FROM cola "
                "WHERE estado='pendiente' AND proximo_intento <= ? ORDER BY id LIMIT ?",
                (ahora, limite)).fetchall()
        return [ItemCola(*f) for f in filas]

    def calcular_espera(self, intentos: int) -> float:
        """Espera exponencial con variación aleatoria ±20 % (evita ráfagas sincronizadas)."""
        base = min(self.espera_base * (2 ** max(intentos - 1, 0)), self.espera_max)
        return round(base * self._rng.uniform(0.8, 1.2), 2)

    def marcar_enviado(self, item_id: int, ahora: float | None = None) -> None:
        with self._lock:
            self._con.execute("UPDATE cola SET estado='enviado', enviado_en=?, intentos=intentos+1, "
                              "ultimo_error=NULL WHERE id=?",
                              (ahora if ahora is not None else time.time(), item_id))

    def marcar_reintento(self, item_id: int, error: str, ahora: float | None = None) -> float:
        ahora = ahora if ahora is not None else time.time()
        with self._lock:
            (intentos,) = self._con.execute("SELECT intentos FROM cola WHERE id=?", (item_id,)).fetchone()
            espera = self.calcular_espera(intentos + 1)
            self._con.execute("UPDATE cola SET intentos=?, proximo_intento=?, ultimo_error=? WHERE id=?",
                              (intentos + 1, ahora + espera, error[:200], item_id))
        return espera

    def marcar_fallido(self, item_id: int, error: str) -> None:
        with self._lock:
            self._con.execute("UPDATE cola SET estado='fallido', intentos=intentos+1, ultimo_error=? WHERE id=?",
                              (error[:200], item_id))

    def purgar_enviados(self, dias: float, ahora: float | None = None) -> int:
        """Borra los mensajes ya entregados con más de `dias` de antigüedad (minimiza PHI en disco)."""
        limite = (ahora if ahora is not None else time.time()) - dias * 86400
        with self._lock:
            cur = self._con.execute("DELETE FROM cola WHERE estado='enviado' AND enviado_en < ?", (limite,))
            return cur.rowcount

    def estadisticas(self) -> dict[str, int]:
        with self._lock:
            filas = self._con.execute("SELECT estado, COUNT(*) FROM cola GROUP BY estado").fetchall()
        return {e: n for e, n in filas}

    def estado_de(self, control_id: str) -> tuple[str, int, str | None] | None:
        with self._lock:
            return self._con.execute("SELECT estado, intentos, ultimo_error FROM cola WHERE control_id=?",
                                     (control_id,)).fetchone()

    def cerrar(self) -> None:
        with self._lock:
            self._con.close()


# ── Cliente HTTP ─────────────────────────────────────────────────────────────

class ClienteHTTP(Protocol):
    """Interfaz mínima: devuelve el código HTTP; lanza OSError si no hay conexión."""

    async def enviar(self, url: str, cuerpo: bytes, cabeceras: dict[str, str]) -> int: ...


class ClienteUrllib:
    """Cliente HTTPS con la biblioteca estándar (verificación TLS activada)."""

    def __init__(self, ca_bundle: str | None = None, timeout: float = 20.0) -> None:
        self._ctx = ssl.create_default_context(cafile=ca_bundle) if ca_bundle else ssl.create_default_context()
        self._timeout = timeout

    def _enviar_sync(self, url: str, cuerpo: bytes, cabeceras: dict[str, str]) -> int:
        req = urllib.request.Request(url, data=cuerpo, method="POST", headers={
            "Content-Type": "application/hl7-v2; charset=utf-8", "User-Agent": "hoja-diaria-puente-hl7/1.0",
            **cabeceras})
        try:
            with urllib.request.urlopen(req, timeout=self._timeout, context=self._ctx) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    async def enviar(self, url: str, cuerpo: bytes, cabeceras: dict[str, str]) -> int:
        return await asyncio.to_thread(self._enviar_sync, url, cuerpo, cabeceras)


def validar_url(url: str) -> None:
    """Exige HTTPS salvo hacia localhost (pruebas locales)."""
    u = urlparse(url)
    if u.scheme == "https":
        return
    if u.scheme == "http" and u.hostname in ("localhost", "127.0.0.1", "::1"):
        return
    raise ValueError("La URL de la app debe usar https:// (http:// solo se permite hacia localhost)")


# ── Puente ───────────────────────────────────────────────────────────────────

class Puente:
    def __init__(self, *, url: str, secreto: str, cola: ColaDurable, cliente: ClienteHTTP,
                 ips_permitidas: set[str] | None = None, intervalo: float = 2.0,
                 retencion_dias: float = 7.0) -> None:
        if not secreto:
            raise ValueError("HL7_BRIDGE_SECRET es obligatorio")
        validar_url(url)
        self.url, self._secreto = url, secreto
        self.cola, self.cliente = cola, cliente
        self.ips_permitidas = ips_permitidas or set()
        self.intervalo = intervalo
        self.retencion_dias = retencion_dias

    # Recepción MLLP ----------------------------------------------------------
    def procesar_mensaje(self, datos: bytes) -> str:
        """Valida y encola un mensaje; devuelve el ACK (texto) que se responde a la máquina."""
        try:
            msg = parsear(datos)
        except ErrorHL7 as e:
            ctrl = mllp.control_id_desde_texto(datos)
            log.warning("mensaje ilegible", extra={"evento": "rechazado", "control_id": ctrl, "error": str(e),
                                                   "codigo_ack": "AE"})
            return mllp.construir_ack("AE", control_id_original=ctrl, texto=str(e))
        extra = {"control_id": msg.control_id, "maquina": msg.instalacion_emisora, "obx": len(msg.todos("OBX"))}
        if msg.tipo != "ORU":
            log.warning("tipo no soportado", extra={**extra, "evento": "rechazado", "codigo_ack": "AR"})
            return mllp.construir_ack("AR", msg, texto="Solo se aceptan mensajes ORU^R01")
        try:
            msg.validar_oru_r01()
        except ErrorHL7 as e:
            log.warning("ORU incompleto", extra={**extra, "evento": "rechazado", "error": str(e), "codigo_ack": "AE"})
            return mllp.construir_ack("AE", msg, texto=str(e))
        try:
            nuevo = self.cola.encolar(msg.control_id, datos)
        except sqlite3.Error as e:
            log.error("no se pudo guardar en la cola", extra={**extra, "evento": "error_cola", "error": type(e).__name__})
            return mllp.construir_ack("AE", msg, texto="Error interno del puente")
        log.info("mensaje encolado" if nuevo else "duplicado (ya en cola)",
                 extra={**extra, "evento": "encolado" if nuevo else "duplicado", "codigo_ack": "AA"})
        return mllp.construir_ack("AA", msg)

    async def manejar_conexion(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        pe = writer.get_extra_info("peername")
        origen = pe[0] if pe else "?"
        if self.ips_permitidas and origen not in self.ips_permitidas:
            log.warning("conexión rechazada", extra={"evento": "ip_no_permitida", "origen": origen})
            writer.close()
            return
        log.info("conexión", extra={"evento": "conexion", "origen": origen})
        try:
            while True:
                try:
                    datos = await mllp.leer_mensaje(reader)
                except mllp.ErrorMLLP as e:
                    log.warning("trama inválida", extra={"evento": "trama_invalida", "origen": origen, "error": str(e)})
                    break
                if datos is None:
                    break
                ack = self.procesar_mensaje(datos)
                writer.write(mllp.enmarcar(ack))
                await writer.drain()
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            writer.close()

    # Envío a la app ----------------------------------------------------------
    async def enviar_pendientes_una_vez(self, ahora: float | None = None) -> dict[str, int]:
        """Intenta enviar todo lo que esté listo. Devuelve conteos {enviados, reintentos, fallidos}."""
        res = {"enviados": 0, "reintentos": 0, "fallidos": 0}
        for item in self.cola.listos(ahora):
            extra = {"control_id": item.control_id, "intentos": item.intentos + 1}
            cabeceras = cabeceras_firmadas(self._secreto, item.cuerpo)  # se firma en cada intento
            try:
                status = await self.cliente.enviar(self.url, item.cuerpo, cabeceras)
            except (OSError, asyncio.TimeoutError) as e:
                espera = self.cola.marcar_reintento(item.id, type(e).__name__, ahora)
                log.warning("sin conexión con la app", extra={**extra, "evento": "reintento",
                                                              "error": type(e).__name__, "espera_s": espera})
                res["reintentos"] += 1
                break  # si no hay red, no tiene sentido probar el resto ahora
            if 200 <= status < 300:
                self.cola.marcar_enviado(item.id, ahora)
                log.info("entregado", extra={**extra, "evento": "enviado", "http": status})
                res["enviados"] += 1
            elif status in HTTP_PERMANENTES:
                self.cola.marcar_fallido(item.id, f"HTTP {status}")
                log.error("rechazado por la app", extra={**extra, "evento": "fallido", "http": status})
                res["fallidos"] += 1
            else:  # 401/403/404 (p. ej. HL7 aún desactivado), 429, 5xx…
                espera = self.cola.marcar_reintento(item.id, f"HTTP {status}", ahora)
                log.warning("la app no aceptó el mensaje; se reintentará",
                            extra={**extra, "evento": "reintento", "http": status, "espera_s": espera})
                res["reintentos"] += 1
        return res

    async def bucle_envio(self, parar: asyncio.Event) -> None:
        ultima_purga = 0.0
        while not parar.is_set():
            try:
                await self.enviar_pendientes_una_vez()
                if time.time() - ultima_purga > 3600:
                    self.cola.purgar_enviados(self.retencion_dias)
                    ultima_purga = time.time()
            except Exception as e:  # el bucle nunca debe morir
                log.error("error en el bucle de envío", extra={"evento": "error_envio", "error": type(e).__name__})
            try:
                await asyncio.wait_for(parar.wait(), timeout=self.intervalo)
            except asyncio.TimeoutError:
                pass

    async def ejecutar(self, host: str, puerto: int) -> None:
        parar = asyncio.Event()
        loop = asyncio.get_running_loop()
        for s in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(s, parar.set)
            except (NotImplementedError, RuntimeError):  # Windows
                pass
        servidor = await asyncio.start_server(self.manejar_conexion, host, puerto, limit=mllp.TAM_MAXIMO)
        log.info("puente escuchando", extra={"evento": "inicio", "pendientes": self.cola.estadisticas().get("pendiente", 0)})
        envio = asyncio.create_task(self.bucle_envio(parar))
        try:
            async with servidor:
                await parar.wait()
        finally:
            servidor.close()
            await envio
            log.info("puente detenido", extra={"evento": "fin"})


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Puente HL7 MLLP → HTTPS (Hoja Diaria Renal)")
    p.add_argument("--url", default=os.getenv("HL7_APP_URL", ""), help="URL completa de /api/hl7/mensajes")
    p.add_argument("--host", default=os.getenv("HL7_PUENTE_HOST", "127.0.0.1"),
                   help="interfaz donde escuchar (IP de la red de las máquinas)")
    p.add_argument("--puerto", type=int, default=int(os.getenv("HL7_PUENTE_PUERTO", "2575")))
    p.add_argument("--cola", default=os.getenv("HL7_PUENTE_COLA", "puente_hl7_cola.db"), help="archivo SQLite de la cola")
    p.add_argument("--ips-permitidas", default=os.getenv("HL7_PUENTE_IPS", ""),
                   help="IPs de las máquinas separadas por coma (vacío = todas)")
    p.add_argument("--ca-bundle", default=os.getenv("HL7_CA_BUNDLE") or None, help="certificados CA adicionales")
    p.add_argument("--retencion-dias", type=float, default=float(os.getenv("HL7_PUENTE_RETENCION_DIAS", "7")))
    p.add_argument("--intervalo", type=float, default=2.0, help="segundos entre rondas de envío")
    p.add_argument("--nivel-log", default="INFO")
    args = p.parse_args(argv)

    configurar_logging(args.nivel_log)
    secreto = os.getenv("HL7_BRIDGE_SECRET", "")
    if not args.url or not secreto:
        p.error("Faltan --url (o HL7_APP_URL) y/o la variable HL7_BRIDGE_SECRET")
    try:
        puente = Puente(url=args.url, secreto=secreto, cola=ColaDurable(args.cola),
                        cliente=ClienteUrllib(args.ca_bundle),
                        ips_permitidas={x.strip() for x in args.ips_permitidas.split(",") if x.strip()},
                        intervalo=args.intervalo, retencion_dias=args.retencion_dias)
    except ValueError as e:
        p.error(str(e))
    asyncio.run(puente.ejecutar(args.host, args.puerto))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
