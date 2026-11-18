"""Endpoints /api/hl7/* (flag, firma, idempotencia, borradores, confirmación). Datos FICTICIOS."""
import time
from datetime import datetime

import pytest

import config
from hl7 import firma
from hl7.simulador_ak98 import SesionFicticia, construir_oru
from routers import hl7 as router_hl7

SECRETO = "secreto-hl7-solo-tests"
_n = 0


@pytest.fixture
def hl7_on(monkeypatch):
    monkeypatch.setattr(config, "HL7_ENABLED", True)
    monkeypatch.setattr(config, "HL7_BRIDGE_SECRET", SECRETO)


def oru(id_paciente, fecha="2026-08-03", hora="06:15", control=None, **valores):
    global _n
    _n += 1
    base = dict(peso_entrada=72.0, peso_salida=69.6, uf_litros=2.6, ktv=1.32, ta_sistolica=130,
                ta_diastolica=80, frecuencia=76, duracion_min=240, alarmas=[], nota="Sin novedad")
    base.update(valores)
    s = SesionFicticia(maquina="AK98-07", id_paciente=id_paciente,
                       inicio=datetime.fromisoformat(f"{fecha}T{hora}"), **base)
    return construir_oru(s, control or f"TEST-{_n:05d}-{time.time_ns()}")


def enviar(cliente, mensaje, secreto=SECRETO, ahora=None):
    cuerpo = mensaje.encode() if isinstance(mensaje, str) else mensaje
    return cliente.post("/api/hl7/mensajes", content=cuerpo,
                        headers={"Content-Type": "application/hl7-v2",
                                 **firma.cabeceras_firmadas(secreto, cuerpo, ahora=ahora)})


def paciente(cliente, turno="M", i=0):
    return cliente.get(f"/api/pacientes?turno={turno}").json()[i]


# ── Flag apagado (valor por defecto) ─────────────────────────────────────────

def test_flag_apagado_por_defecto(admin, anonimo):
    assert config.HL7_ENABLED is False
    assert admin.get("/api/hl7/estado").json() == {"habilitado": False}
    cuerpo = oru("V-10000000").encode()
    cab = firma.cabeceras_firmadas(SECRETO, cuerpo)
    assert anonimo.post("/api/hl7/mensajes", content=cuerpo, headers=cab).status_code == 404
    assert admin.post("/api/hl7/mensajes", content=cuerpo, headers=cab).status_code == 404
    for ruta in ("/api/hl7/borradores", "/api/hl7/borradores/1", "/api/hl7/vinculos", "/api/hl7/auditoria"):
        assert admin.get(ruta).status_code == 404, ruta
    assert admin.post("/api/hl7/borradores/1/confirmar", json={}).status_code == 404
    assert admin.post("/api/hl7/borradores/1/descartar", json={}).status_code == 404
    assert "/api/hl7/mensajes" not in admin.get("/openapi.json").json()["paths"]


def test_estado_requiere_sesion_y_demo_lo_ve(anonimo, demo):
    assert anonimo.get("/api/hl7/estado").status_code == 401
    assert demo.get("/api/hl7/estado").json() == {"habilitado": False}


# ── Firma ────────────────────────────────────────────────────────────────────

def test_firma_invalida_o_vencida(hl7_on, anonimo):
    msg = oru("V-10000000")
    assert enviar(anonimo, msg, secreto="otro").status_code == 401
    assert enviar(anonimo, msg, ahora=time.time() - 3600).status_code == 401
    assert anonimo.post("/api/hl7/mensajes", content=msg.encode()).status_code == 401
    r = anonimo.post("/api/hl7/mensajes", content=msg.encode(),
                     headers={**firma.cabeceras_firmadas(SECRETO, b"otro cuerpo")})
    assert r.status_code == 401


def test_sin_secreto_configurado_rechaza(hl7_on, monkeypatch, anonimo):
    monkeypatch.setattr(config, "HL7_BRIDGE_SECRET", "")
    assert enviar(anonimo, oru("V-10000000"), secreto="").status_code == 401


# ── Recepción, idempotencia y banderas ───────────────────────────────────────

def test_recepcion_crea_borrador_e_idempotencia(hl7_on, anonimo, admin):
    p = paciente(admin)
    msg = oru(p["cedula"], control="IDEMP-0001")
    r = enviar(anonimo, msg)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["estado"] == "procesado" and body["control_id"] == "IDEMP-0001"
    assert "vinculado_por_cedula" in body["banderas"]

    r2 = enviar(anonimo, msg)
    assert r2.status_code == 200
    assert r2.json() == {"estado": "duplicado", "control_id": "IDEMP-0001", "borrador_id": body["borrador_id"]}

    b = admin.get(f"/api/hl7/borradores/{body['borrador_id']}").json()
    assert b["estado"] == "pendiente" and b["paciente"]["id"] == p["id"]
    assert (b["fecha"], b["turno"]) == ("2026-08-03", "M")
    assert b["valores"]["peso_entrada"] == 72.0 and b["valores"]["uf_litros"] == 2.6
    assert sum(1 for x in admin.get("/api/hl7/borradores").json() if x["control_id"] == "IDEMP-0001") == 1


def test_mensaje_malformado(hl7_on, anonimo, admin):
    roto = "\r".join(l for l in oru("V-1").split("\r") if not l.startswith("PID"))
    r = enviar(anonimo, roto)
    assert r.status_code == 422 and r.json()["estado"] == "error"
    assert enviar(anonimo, roto).json()["estado"] == "duplicado"
    r = enviar(anonimo, "esto no es HL7")
    assert r.status_code == 422 and r.json()["control_id"].startswith("SIN-CTRL-")


def test_banderas_de_validacion(hl7_on, anonimo, admin):
    p = paciente(admin, "T", 0)
    # Sesión previa con peso de salida conocido, cargada a mano por la vía normal
    s = admin.get("/api/sesiones/2026-08-04/T").json()
    reg = next(x for x in admin.get(f"/api/sesiones/{s['id']}/registros").json() if x["paciente_id"] == p["id"])
    admin.patch(f"/api/sesiones/registros/{reg['id']}", json={"asistencia": "A", "peso_entrada": 70, "peso_salida": 66.0})

    msg = oru(p["cedula"], fecha="2026-08-06", hora="13:00",
              peso_entrada=71.5, peso_salida=69.0, uf_litros=4.9, ktv=5.0)
    body = enviar(anonimo, msg).json()
    codigos = set(body["banderas"])
    assert {"salto_peso", "uf_inconsistente", "fuera_de_rango"} <= codigos
    assert "turno_distinto" not in codigos

    otro = oru(p["cedula"], fecha="2026-08-06", hora="19:00", alarmas=["DETECTOR DE AIRE"])
    codigos = set(enviar(anonimo, otro).json()["banderas"])
    assert {"turno_distinto", "alarmas_maquina"} <= codigos

    desconocido = enviar(anonimo, oru("AK-NO-EXISTE-1")).json()
    assert "paciente_desconocido" in desconocido["banderas"]


# ── Confirmación / descarte ──────────────────────────────────────────────────

def test_confirmar_aplica_valores_y_audita(hl7_on, anonimo, admin):
    p = paciente(admin, "M", 5)
    bid = enviar(anonimo, oru(p["cedula"], fecha="2026-08-10", alarmas=["CONDUCTIVIDAD"])).json()["borrador_id"]

    r = admin.post(f"/api/hl7/borradores/{bid}/confirmar", json={})
    assert r.status_code == 200, r.text
    out = r.json()
    reg = out["registro"]
    assert (reg["peso_entrada"], reg["peso_salida"], reg["ktv"], reg["asistencia"]) == (72.0, 69.6, 1.32, "A")
    assert reg["perdida_real"] == 2.4                     # cálculo existente de la hoja
    assert "AK98: TA 130/80" in reg["observaciones"] and "CONDUCTIVIDAD" in reg["observaciones"]
    assert out["borrador"]["estado"] == "confirmado" and out["borrador"]["resuelto_por"] == "admin"

    # El valor queda en la hoja oficial del día
    s = admin.get("/api/sesiones/2026-08-10/M").json()
    hoja = next(x for x in admin.get(f"/api/sesiones/{s['id']}/registros").json() if x["paciente_id"] == p["id"])
    assert hoja["peso_entrada"] == 72.0

    assert admin.post(f"/api/hl7/borradores/{bid}/confirmar", json={}).status_code == 409
    aud = admin.get("/api/hl7/auditoria").json()
    conf = next(a for a in aud if a["accion"] == "confirmar" and a["borrador_id"] == bid)
    assert conf["usuario"] == "admin" and conf["momento"] and "peso_entrada" in conf["detalle"]["aplicados"]


def test_no_sobrescribe_lo_escrito_a_mano(hl7_on, anonimo, admin):
    p = paciente(admin, "M", 6)
    s = admin.get("/api/sesiones/2026-08-11/M").json()
    reg = next(x for x in admin.get(f"/api/sesiones/{s['id']}/registros").json() if x["paciente_id"] == p["id"])
    admin.patch(f"/api/sesiones/registros/{reg['id']}", json={"peso_entrada": 75.0})

    bid = enviar(anonimo, oru(p["cedula"], fecha="2026-08-11")).json()["borrador_id"]
    b = admin.get(f"/api/hl7/borradores/{bid}").json()
    assert b["registro_actual"]["peso_entrada"] == 75.0
    out = admin.post(f"/api/hl7/borradores/{bid}/confirmar", json={}).json()
    assert out["registro"]["peso_entrada"] == 75.0 and out["registro"]["peso_salida"] == 69.6
    assert out["conflictos"] == [{"campo": "peso_entrada", "hoja": 75.0, "maquina": 72.0}]

    bid2 = enviar(anonimo, oru(p["cedula"], fecha="2026-08-11", peso_entrada=73.0)).json()["borrador_id"]
    out2 = admin.post(f"/api/hl7/borradores/{bid2}/confirmar", json={"sobrescribir": True}).json()
    assert out2["registro"]["peso_entrada"] == 73.0


def test_confirmar_requiere_admin(hl7_on, anonimo, admin, demo):
    p = paciente(admin, "M", 7)
    bid = enviar(anonimo, oru(p["cedula"], fecha="2026-08-12")).json()["borrador_id"]
    assert demo.get("/api/hl7/borradores").status_code == 200           # puede ver (solo lectura)
    assert demo.post(f"/api/hl7/borradores/{bid}/confirmar", json={}).status_code == 403
    assert demo.post(f"/api/hl7/borradores/{bid}/descartar", json={}).status_code == 403
    assert anonimo.post(f"/api/hl7/borradores/{bid}/confirmar", json={}).status_code == 401
    assert admin.get(f"/api/hl7/borradores/{bid}").json()["estado"] == "pendiente"


def test_solo_admin_aunque_pase_el_middleware(hl7_on, monkeypatch, admin):
    """Defensa en profundidad: el endpoint revisa el rol por sí mismo."""
    monkeypatch.setattr(router_hl7.auth, "rol_actual", lambda request: "demo")
    assert admin.post("/api/hl7/borradores/1/confirmar", json={}).status_code == 403


def test_sesion_cerrada_bloquea_confirmacion(hl7_on, anonimo, admin):
    p = paciente(admin, "M", 8)
    s = admin.get("/api/sesiones/2026-08-13/M").json()
    assert admin.post(f"/api/cierre/{s['id']}/cerrar").status_code == 200
    r = enviar(anonimo, oru(p["cedula"], fecha="2026-08-13"))
    assert "sesion_cerrada" in r.json()["banderas"]
    bid = r.json()["borrador_id"]
    assert admin.post(f"/api/hl7/borradores/{bid}/confirmar", json={}).status_code == 400
    assert admin.get(f"/api/hl7/borradores/{bid}").json()["estado"] == "pendiente"
    reg = next(x for x in admin.get(f"/api/sesiones/{s['id']}/registros").json() if x["paciente_id"] == p["id"])
    assert reg["peso_entrada"] is None


def test_paciente_desconocido_se_vincula_al_confirmar(hl7_on, anonimo, admin):
    p = paciente(admin, "N", 2)
    bid = enviar(anonimo, oru("AK-SIM-7777", fecha="2026-08-14", hora="18:40")).json()["borrador_id"]
    assert admin.post(f"/api/hl7/borradores/{bid}/confirmar", json={}).status_code == 422
    r = admin.post(f"/api/hl7/borradores/{bid}/confirmar", json={"paciente_id": p["id"]})
    assert r.status_code == 200, r.text
    assert any(v["id_externo"] == "AK-SIM-7777" and v["paciente_id"] == p["id"]
               for v in admin.get("/api/hl7/vinculos").json())
    # El siguiente mensaje de ese id ya llega con el paciente identificado
    nuevo = enviar(anonimo, oru("AK-SIM-7777", fecha="2026-08-16", hora="18:40")).json()
    assert "paciente_desconocido" not in nuevo["banderas"]
    assert admin.get(f"/api/hl7/borradores/{nuevo['borrador_id']}").json()["paciente"]["id"] == p["id"]


def test_descartar(hl7_on, anonimo, admin):
    bid = enviar(anonimo, oru("AK-SIM-8888", fecha="2026-08-15")).json()["borrador_id"]
    r = admin.post(f"/api/hl7/borradores/{bid}/descartar", json={"motivo": "Prueba de máquina"})
    assert r.status_code == 200 and r.json()["estado"] == "descartado"
    assert all(b["id"] != bid for b in admin.get("/api/hl7/borradores").json())
    assert any(b["id"] == bid for b in admin.get("/api/hl7/borradores?estado=descartado").json())
    assert admin.post(f"/api/hl7/borradores/{bid}/confirmar", json={}).status_code == 409


def test_tablas_hl7_se_crean_sin_tocar_las_existentes(tmp_path):
    from sqlalchemy import create_engine, inspect, text

    import models  # noqa: F401
    import models_hl7
    eng = create_engine(f"sqlite:///{tmp_path}/m.db")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE pacientes (id INTEGER PRIMARY KEY, nombre TEXT, extra TEXT)"))
        c.execute(text("INSERT INTO pacientes (nombre, extra) VALUES ('Ficticio', 'x')"))
    models_hl7.crear_tablas(eng)
    models_hl7.crear_tablas(eng)  # idempotente
    insp = inspect(eng)
    assert {"hl7_mensaje", "hl7_paciente_id", "hl7_borrador_sesion", "hl7_auditoria"} <= set(insp.get_table_names())
    assert "sesiones" not in insp.get_table_names()
    assert [c["name"] for c in insp.get_columns("pacientes")] == ["id", "nombre", "extra"]
    with eng.connect() as c:
        assert c.execute(text("SELECT extra FROM pacientes")).scalar() == "x"
