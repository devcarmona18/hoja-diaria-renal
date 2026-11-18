"""Puente local: cola durable, reintentos con espera exponencial y servidor MLLP. Datos FICTICIOS."""
import asyncio
import json
import logging
import random
from datetime import date

import pytest

from hl7 import firma, mllp, simulador_ak98
from hl7.puente import ColaDurable, FormatoJSON, Puente, validar_url

URL = "https://app.ejemplo.test/api/hl7/mensajes"


def _mensajes(n=1, malformado=0.0, semilla=7, ids=None):
    return [m for _, m in simulador_ak98.generar_lote(
        maquinas=n, por_maquina=1, fecha=date(2026, 11, 17), turno="M", ids=ids,
        prob_malformado=malformado, semilla=semilla)]


class ClienteFalso:
    """Devuelve, en orden, los códigos/excepciones programados y guarda lo enviado."""

    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.enviados = []

    async def enviar(self, url, cuerpo, cabeceras):
        self.enviados.append((url, cuerpo, cabeceras))
        r = self.respuestas.pop(0) if self.respuestas else 201
        if isinstance(r, Exception):
            raise r
        return r


def _puente(tmp_path, respuestas=()):
    cola = ColaDurable(str(tmp_path / "cola.db"), espera_base=5, espera_max=60, rng=random.Random(1))
    return Puente(url=URL, secreto="s3creto", cola=cola, cliente=ClienteFalso(respuestas))


def test_procesar_mensaje_aa_ae_ar(tmp_path):
    p = _puente(tmp_path)
    bueno = _mensajes()[0]
    assert mllp.codigo_ack(p.procesar_mensaje(bueno.encode())) == "AA"
    assert mllp.codigo_ack(p.procesar_mensaje(bueno.encode())) == "AA"   # reenvío: AA pero no duplica
    assert p.cola.estadisticas() == {"pendiente": 1}

    assert mllp.codigo_ack(p.procesar_mensaje(b"basura")) == "AE"
    sin_pid = "\r".join(l for l in bueno.split("\r") if not l.startswith("PID"))
    assert mllp.codigo_ack(p.procesar_mensaje(sin_pid.encode())) == "AE"
    adt = bueno.replace("ORU^R01^ORU_R01", "ADT^A01")
    assert mllp.codigo_ack(p.procesar_mensaje(adt.encode())) == "AR"
    assert p.cola.estadisticas() == {"pendiente": 1}


def test_reintento_con_espera_y_luego_entrega(tmp_path):
    p = _puente(tmp_path, [ConnectionRefusedError("sin red"), 503, 201])
    msg = _mensajes()[0]
    p.procesar_mensaje(msg.encode())
    ctrl = msg.split("\r")[0].split("|")[9]
    t0 = 1_000_000.0

    r = asyncio.run(p.enviar_pendientes_una_vez(ahora=t0))
    assert r == {"enviados": 0, "reintentos": 1, "fallidos": 0}
    estado, intentos, error = p.cola.estado_de(ctrl)
    assert (estado, intentos, error) == ("pendiente", 1, "ConnectionRefusedError")

    # Antes de que venza la espera no se reintenta
    assert asyncio.run(p.enviar_pendientes_una_vez(ahora=t0 + 1))["reintentos"] == 0
    # Vencida la espera: 503 → otro reintento con espera mayor
    assert asyncio.run(p.enviar_pendientes_una_vez(ahora=t0 + 10))["reintentos"] == 1
    assert p.cola.estado_de(ctrl)[:2] == ("pendiente", 2)
    assert asyncio.run(p.enviar_pendientes_una_vez(ahora=t0 + 13)) == {"enviados": 0, "reintentos": 0, "fallidos": 0}
    assert asyncio.run(p.enviar_pendientes_una_vez(ahora=t0 + 30))["enviados"] == 1
    assert p.cola.estado_de(ctrl)[0] == "enviado"

    # Cada intento va firmado y el cuerpo es el mensaje tal cual
    for url, cuerpo, cab in p.cliente.enviados:
        assert url == URL and cuerpo == msg.encode()
        firma.verificar_firma("s3creto", cuerpo, cab[firma.CABECERA_TIMESTAMP], cab[firma.CABECERA_FIRMA])


def test_errores_permanentes_y_404(tmp_path):
    p = _puente(tmp_path, [422, 404])
    a, b = _mensajes(2)
    p.procesar_mensaje(a.encode())
    p.procesar_mensaje(b.encode())
    r = asyncio.run(p.enviar_pendientes_una_vez(ahora=0))
    # 422: el mensaje es inválido → fallido. 404 (HL7 aún desactivado en la app) → se reintenta
    assert r == {"enviados": 0, "reintentos": 1, "fallidos": 1}
    assert p.cola.estadisticas() == {"fallido": 1, "pendiente": 1}


def test_espera_exponencial_con_tope(tmp_path):
    cola = ColaDurable(str(tmp_path / "c.db"), espera_base=5, espera_max=60, rng=random.Random(3))
    esperas = [cola.calcular_espera(n) for n in range(1, 8)]
    assert 4 <= esperas[0] <= 6 and 8 <= esperas[1] <= 12 and 16 <= esperas[2] <= 24
    assert all(e <= 72 for e in esperas) and esperas[-1] >= 48


def test_cola_sobrevive_reinicio_y_purga(tmp_path):
    ruta = str(tmp_path / "cola.db")
    c = ColaDurable(ruta)
    assert c.encolar("A", b"x", ahora=0) and not c.encolar("A", b"x", ahora=0)
    c.encolar("B", b"y", ahora=0)
    c.cerrar()
    c2 = ColaDurable(ruta)
    items = c2.listos(ahora=1)
    assert [i.control_id for i in items] == ["A", "B"]
    c2.marcar_enviado(items[0].id, ahora=0)
    assert c2.purgar_enviados(dias=1, ahora=86401) == 1
    assert c2.estadisticas() == {"pendiente": 1}


def test_url_debe_ser_https():
    validar_url("https://x.test/api/hl7/mensajes")
    validar_url("http://127.0.0.1:8000/api/hl7/mensajes")
    with pytest.raises(ValueError):
        validar_url("http://app.ejemplo.test/api/hl7/mensajes")


def test_logs_sin_datos_del_paciente(tmp_path, caplog):
    p = _puente(tmp_path, [503])
    msg = _mensajes(ids=["AK-PRIVADO-123"])[0]
    with caplog.at_level(logging.DEBUG, logger="hl7.puente"):
        p.procesar_mensaje(msg.encode())
        p.procesar_mensaje(b"MSH|^~\\&|A|B|C|D|2026||ORU^R01|X1|P|2.5\rPID|1||AK-PRIVADO-123\robx|roto")
        asyncio.run(p.enviar_pendientes_una_vez(ahora=0))
    fmt = FormatoJSON()
    salida = "\n".join(fmt.format(r) for r in caplog.records)
    assert caplog.records and all(json.loads(l) for l in salida.splitlines())
    assert "AK-PRIVADO-123" not in salida and "FICTICIO" not in salida and "OBX" not in salida


def test_servidor_mllp_con_simulador(tmp_path):
    """Simulador → servidor MLLP real del puente (puerto efímero) → ACK por mensaje."""
    p = _puente(tmp_path)

    async def escenario():
        servidor = await asyncio.start_server(p.manejar_conexion, "127.0.0.1", 0, limit=mllp.TAM_MAXIMO)
        puerto = servidor.sockets[0].getsockname()[1]
        async with servidor:
            buenos = _mensajes(2, semilla=11)
            roto = simulador_ak98.malograr(buenos[0], random.Random(0))
            return await simulador_ak98.enviar_maquina("127.0.0.1", puerto, buenos + [roto, "MSH|basura"], 0)

    codigos = asyncio.run(escenario())
    assert codigos[:2] == ["AA", "AA"] and codigos[2] in ("AE", "AR") and codigos[3] == "AE"
    assert p.cola.estadisticas() == {"pendiente": 2}


def test_simulador_valores_plausibles():
    from hl7.mapeo import aplicar_mapeo, cargar_mapeo
    from hl7.parser import parsear
    mapeo = cargar_mapeo()
    for msg in _mensajes(20, semilla=5):
        v = aplicar_mapeo(parsear(msg), mapeo).valores
        assert 1.1 <= v["ktv"] <= 1.6
        assert 200 <= v["duracion_min"] <= 260
        assert abs((v["peso_entrada"] - v["peso_salida"]) - v["uf_litros"]) < 0.8
        assert 90 <= v["ta_sistolica"] <= 170
