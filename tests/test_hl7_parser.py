"""Parser HL7 v2, mapeo AK 98 y marco MLLP / ACK / firma (sin app). Datos FICTICIOS."""
from datetime import datetime, timedelta, timezone

import pytest

from hl7 import firma, mllp
from hl7.mapeo import aplicar_mapeo, cargar_mapeo, determinar_turno
from hl7.parser import (ErrorHL7, Separadores, codificar_escapes, decodificar_escapes,
                        parsear, parsear_fecha_hora, parsear_numero)

ORU = "\r".join([
    r"MSH|^~\&|AK98|AK98-01|HOJA-DIARIA|UNIDAD-RENAL|20261117103000||ORU^R01^ORU_R01|CTRL0001|P|2.5",
    "PID|1||AK-SIM-0001^^^AK98||FICTICIO^PACIENTE 0001",
    "OBR|1|||HD^Sesion^AK98L|||20261117063000|20261117103000",
    "OBX|1|NM|AK98-PESO-PRE^Peso pre^AK98L||72.4|kg|||||F",
    "OBX|2|NM|AK98-PESO-POST^Peso post^AK98L||70.1|kg|||||F",
    "OBX|3|NM|AK98-UF-TOTAL^UF^AK98L||2500|mL|||||F",
    "OBX|4|NM|AK98-KTV^Kt/V^AK98L||1.35||||||F",
    "OBX|5|SN|AK98-PA^TA^AK98L||^128^/^76|mm[Hg]|||||F",
    "OBX|6|NM|AK98-FC^FC^AK98L||78|/min|||||F",
    r"OBX|7|ST|AK98-ALARMA^Alarmas^AK98L||PRESION VENOSA ALTA~AIRE \T\ LINEA||||||F",
    r"OBX|8|TX|AK98-NOTA^Nota^AK98L||Sin novedad\.br\control \S\ ok||||||F",
    "OBX|9|NM|XYZ-DESCONOCIDO^Otro||1||||||F",
]) + "\r"


# ── Parser ───────────────────────────────────────────────────────────────────

def test_parsea_oru_valido():
    m = parsear(ORU)
    m.validar_oru_r01()
    assert (m.tipo, m.evento, m.control_id, m.version) == ("ORU", "R01", "CTRL0001", "2.5")
    assert m.instalacion_emisora == "AK98-01"
    assert m.id_paciente() == "AK-SIM-0001"
    assert m.inicio_observacion == datetime(2026, 11, 17, 6, 30)
    assert m.fin_observacion == datetime(2026, 11, 17, 10, 30)
    assert m.msh.campo(1) == "|" and m.msh.campo(2) == "^~\\&"


def test_multiples_obx_y_tipos():
    obs = parsear(ORU).observaciones
    assert len(obs) == 9
    assert [o.set_id for o in obs] == [str(i) for i in range(1, 10)]
    assert obs[0].valor_numerico == 72.4 and obs[0].unidad == "kg"
    assert obs[4].valor_sn == ("", 128.0, "/", 76.0)
    assert obs[6].valores == ["PRESION VENOSA ALTA", "AIRE & LINEA"]
    assert obs[7].valor == "Sin novedad\ncontrol ^ ok"


def test_escapes():
    sep = Separadores()
    assert decodificar_escapes(r"a\F\b\S\c\T\d\R\e\E\f", sep) == "a|b^c&d~e\\f"
    assert decodificar_escapes(r"\X41\\X4243\ y \H\negrita\N\ \.br\fin", sep) == "A" + "BC y negrita \nfin"
    assert decodificar_escapes(r"sin cerrar \F", sep) == r"sin cerrar \F"
    original = "TA 120/80 | nota ^ & ~ \\ fin\nlinea"
    assert decodificar_escapes(codificar_escapes(original, sep), sep) == original


def test_separadores_personalizados_y_saltos_de_linea():
    texto = ("MSH#!$\\%#AK98#AK98-02###20261117##ORU!R01#C-77#P#2.4\r\n"
             "PID#1##AK-SIM-0009\n"
             "OBX#1#NM#AK98-KTV!Kt/V##1,42\n")
    m = parsear(texto)
    assert m.separadores == Separadores("#", "!", "$", "\\", "%")
    assert m.control_id == "C-77" and m.tipo == "ORU" and m.evento == "R01"
    assert m.observaciones[0].valor_numerico == 1.42


def test_bytes_latin1_y_marco_mllp():
    datos = mllp.enmarcar(ORU.replace("Sin novedad", "Sesión sin novedad").encode("latin-1"))
    m = parsear(datos)  # el parser tolera el marco y la codificación ISO-8859-1
    assert m.observaciones[7].valor.startswith("Sesión")


@pytest.mark.parametrize("texto", [
    "", "hola", "PID|1||x", "MSH|", "MSHA^~\\&|x",
    "MSH|^~\\&|A|B|C|D|20260101\rOBX|1",            # sin MSH-9
    "MSH|^~\\&|A|B|C|D|2026||ORU^R01|1|P|2.5\robx|roto",
    "MSH|^~\\&|A|B|C|D|2026||ORU^R01|1|P|2.5\rMSH|^~\\&|otra",
])
def test_malformados(texto):
    with pytest.raises(ErrorHL7):
        parsear(texto)


def test_validar_oru():
    m = parsear(ORU.replace("ORU^R01^ORU_R01", "ADT^A01"))
    with pytest.raises(ErrorHL7, match="no soportado"):
        m.validar_oru_r01()
    sin_pid = "\r".join(l for l in ORU.split("\r") if not l.startswith("PID"))
    with pytest.raises(ErrorHL7, match="PID"):
        parsear(sin_pid).validar_oru_r01()
    sin_obx = "\r".join(l for l in ORU.split("\r") if not l.startswith("OBX"))
    with pytest.raises(ErrorHL7, match="OBX"):
        parsear(sin_obx).validar_oru_r01()


def test_fechas_y_numeros():
    assert parsear_fecha_hora("2026") == datetime(2026, 1, 1)
    assert parsear_fecha_hora("202611171030") == datetime(2026, 11, 17, 10, 30)
    dt = parsear_fecha_hora("20261117103015.25-0500")
    assert dt.utcoffset() == timedelta(hours=-5) and dt.microsecond == 250000
    assert parsear_fecha_hora("20261399") is None and parsear_fecha_hora("abc") is None
    assert parsear_numero("72,5") == 72.5 and parsear_numero("1e2") == 100
    assert parsear_numero("") is None and parsear_numero("NaN") is None and parsear_numero("x") is None


# ── Mapeo ────────────────────────────────────────────────────────────────────

def test_mapeo_ak98():
    res = aplicar_mapeo(parsear(ORU), cargar_mapeo())
    v = res.valores
    assert res.id_paciente == "AK-SIM-0001"
    assert (v["peso_entrada"], v["peso_salida"], v["ktv"]) == (72.4, 70.1, 1.35)
    assert v["uf_litros"] == 2.5                      # mL → L
    assert (v["ta_sistolica"], v["ta_diastolica"]) == (128, 76)
    assert v["frecuencia_cardiaca"] == 78
    assert v["duracion_min"] == 240                    # calculada con OBR-7/OBR-8
    assert v["alarmas"] == ["PRESION VENOSA ALTA", "AIRE & LINEA"]
    assert "control ^ ok" in v["observaciones"]
    assert res.no_mapeados == ["XYZ-DESCONOCIDO"]
    assert (res.fecha, res.turno) == ("2026-11-17", "M")


def test_mapeo_unidad_desconocida_y_turnos():
    mapeo = cargar_mapeo()
    res = aplicar_mapeo(parsear(ORU.replace("72.4|kg", "72.4|lb")), mapeo)
    assert "peso_entrada" not in res.valores
    assert any("unidad no reconocida" in a for a in res.advertencias)

    assert determinar_turno(datetime(2026, 11, 17, 13, 0), mapeo) == ("2026-11-17", "T")
    assert determinar_turno(datetime(2026, 11, 17, 19, 0), mapeo) == ("2026-11-17", "N")
    assert determinar_turno(datetime(2026, 11, 18, 1, 30), mapeo) == ("2026-11-17", "N")  # madrugada
    utc = datetime(2026, 11, 17, 11, 30, tzinfo=timezone.utc)                         # 06:30 en Colombia
    assert determinar_turno(utc, mapeo) == ("2026-11-17", "M")


def test_mapeo_marca_identificadores_provisionales():
    mapeo = cargar_mapeo()
    assert mapeo["estado"] == "PROVISIONAL"
    assert "fabricante" in mapeo["_AVISO"]


# ── MLLP / ACK ───────────────────────────────────────────────────────────────

def test_marco_mllp():
    trama = mllp.enmarcar("MSH|x")
    assert trama == b"\x0bMSH|x\x1c\x0d"
    assert mllp.desenmarcar(trama) == b"MSH|x"
    with pytest.raises(mllp.ErrorMLLP):
        mllp.desenmarcar(b"MSH|x")
    with pytest.raises(mllp.ErrorMLLP):
        mllp.enmarcar(b"a\x1cb")


def test_lector_mllp_por_fragmentos():
    lector = mllp.LectorMLLP(tam_maximo=100)
    datos = b"basura" + mllp.enmarcar("UNO") + mllp.enmarcar("DOS")
    recibidos = []
    for i in range(0, len(datos), 3):
        recibidos += lector.alimentar(datos[i:i + 3])
    assert recibidos == [b"UNO", b"DOS"]
    with pytest.raises(mllp.ErrorMLLP):
        lector.alimentar(b"\x0b" + b"x" * 200)


def test_ack_aa_ae_ar():
    m = parsear(ORU)
    ack = mllp.construir_ack("AA", m)
    a = parsear(ack)
    assert a.tipo == "ACK" and a.evento == "R01"
    assert a.app_receptora == "AK98" and a.instalacion_receptora == "AK98-01"
    assert a.primero("MSA").valor(1) == "AA" and a.primero("MSA").valor(2) == "CTRL0001"
    assert mllp.codigo_ack(mllp.enmarcar(ack)) == "AA"

    ae = parsear(mllp.construir_ack("AE", m, texto="Falta PID | x"))
    assert ae.primero("MSA").valor(1) == "AE" and ae.primero("MSA").valor(3) == "Falta PID | x"
    assert ae.primero("ERR") is not None

    ar = mllp.construir_ack("AR", control_id_original="ROTO-1", texto="ilegible")
    assert mllp.codigo_ack(ar) == "AR" and parsear(ar).primero("MSA").valor(2) == "ROTO-1"


def test_control_id_de_mensaje_roto():
    assert mllp.control_id_desde_texto(b"MSH|^~\\&|A|B|C|D|2026||ORU^R01|ABC-9|P\robx|roto") == "ABC-9"
    assert mllp.control_id_desde_texto(b"basura") == ""


# ── Firma HMAC ───────────────────────────────────────────────────────────────

def test_firma_valida_mala_y_vencida():
    cuerpo, ahora = ORU.encode(), 1_800_000_000
    cab = firma.cabeceras_firmadas("secreto", cuerpo, ahora=ahora)
    ts, f = cab[firma.CABECERA_TIMESTAMP], cab[firma.CABECERA_FIRMA]
    firma.verificar_firma("secreto", cuerpo, ts, f, ahora=ahora + 10)  # no lanza

    with pytest.raises(firma.ErrorFirma, match="inválida"):
        firma.verificar_firma("otro-secreto", cuerpo, ts, f, ahora=ahora)
    with pytest.raises(firma.ErrorFirma, match="inválida"):
        firma.verificar_firma("secreto", cuerpo + b"x", ts, f, ahora=ahora)
    with pytest.raises(firma.ErrorFirma, match="ventana"):
        firma.verificar_firma("secreto", cuerpo, ts, f, ahora=ahora + 301)
    with pytest.raises(firma.ErrorFirma, match="ventana"):
        firma.verificar_firma("secreto", cuerpo, ts, f, ahora=ahora - 301)
    with pytest.raises(firma.ErrorFirma, match="Faltan"):
        firma.verificar_firma("secreto", cuerpo, None, None, ahora=ahora)
    with pytest.raises(firma.ErrorFirma, match="no configurado"):
        firma.verificar_firma("", cuerpo, ts, f, ahora=ahora)
