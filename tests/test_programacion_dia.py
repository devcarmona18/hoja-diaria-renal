"""R2 / R7: programar el día siguiente con la hoja de la página principal y cambios
de un día vs. permanentes. Datos FICTICIOS (semilla). Cada prueba usa sus propias
fechas y deja la base de pacientes como estaba."""
from datetime import date, timedelta

import pytest

import hoja_dia
import models
from database import SessionLocal

LUN = date(2027, 3, 1)          # lunes
assert LUN.weekday() == 0


def dia(semana: int, wd: int) -> str:
    """Fecha ISO: semana N (desde LUN) y día 0=lunes … 5=sábado."""
    return (LUN + timedelta(weeks=semana, days=wd)).isoformat()


@pytest.fixture
def base(admin):
    """Restaura pacientes y borra lo creado en las fechas de prueba (>= LUN)."""
    with SessionLocal() as db:
        foto = {p.id: (p.turno, p.estacion, p.cama, p.dias, p.activo)
                for p in db.query(models.Paciente).all()}
    yield admin
    with SessionLocal() as db:
        desde = LUN.isoformat()
        db.query(models.AsignacionDia).filter(models.AsignacionDia.fecha >= desde).delete()
        ses = [s.id for s in db.query(models.Sesion).filter(models.Sesion.fecha >= desde)]
        if ses:
            db.query(models.Registro).filter(models.Registro.sesion_id.in_(ses)).delete()
            db.query(models.Sesion).filter(models.Sesion.id.in_(ses)).delete()
        db.query(models.Programacion).filter(models.Programacion.fecha >= desde).delete()
        for p in db.query(models.Paciente).all():
            p.turno, p.estacion, p.cama, p.dias, p.activo = foto[p.id]
        db.commit()


def pac(c, turno, est, cama):
    return next(p for p in c.get(f"/api/pacientes?turno={turno}").json()
                if p["estacion"] == est and p["cama"] == cama)


def set_dias(pid, dias):
    with SessionLocal() as db:
        db.get(models.Paciente, pid).dias = dias
        db.commit()


def hoja(c, fecha, turno="M"):
    r = c.get(f"/api/asignaciones/hoja/{fecha}/{turno}")
    assert r.status_code == 200, r.text
    return r.json()


def puesto(h, pid):
    return next((x for x in h["puestos"] if x["paciente"]["id"] == pid), None)


def ocupantes(h, est, cama):
    return [x["paciente"]["id"] for x in h["puestos"] if (x["estacion"], x["cama"]) == (est, cama)]


def mover(c, fecha, pid, est, cama, turno="M", **extra):
    return c.post("/api/asignaciones", json={"fecha": fecha, "turno": turno, "paciente_id": pid,
                                             "estacion": est, "cama": cama, **extra})


def liberar_cama(c, est=3, cama=16, turno="M"):
    """El paciente de esa cama pasa a LMV: martes/jueves/sábado la cama queda libre."""
    p = pac(c, turno, est, cama)
    set_dias(p["id"], "LMV")
    return p


def registros(c, fecha, turno="M"):
    s = c.get(f"/api/sesiones/{fecha}/{turno}").json()
    return s, {r["paciente_id"]: r for r in c.get(f"/api/sesiones/{s['id']}/registros").json()}


# ── Próximo día de diálisis ───────────────────────────────────────────────────

@pytest.mark.parametrize("desde,esperado", [
    ("2027-03-01", "2027-03-02"),   # lunes → martes
    ("2027-03-05", "2027-03-06"),   # viernes → sábado
    ("2027-03-06", "2027-03-08"),   # sábado → lunes (salta domingo)
    ("2027-03-07", "2027-03-08"),   # domingo → lunes
    ("2026-12-31", "2027-01-01"),   # cambio de año
    ("2027-01-30", "2027-02-01"),   # sábado fin de mes → lunes del mes siguiente
])
def test_proximo_dia_dialisis(admin, desde, esperado):
    assert hoja_dia.proximo_dia_dialisis(date.fromisoformat(desde)).isoformat() == esperado
    r = admin.get(f"/api/asignaciones/proximo-dia?desde={desde}")
    assert r.status_code == 200 and r.json()["fecha"] == esperado


def test_proximo_dia_grupo_y_fecha_invalida(admin):
    r = admin.get("/api/asignaciones/proximo-dia?desde=2027-03-06").json()
    assert r["dia_semana"] == "lunes" and r["grupo_dias"] == "LMV"
    assert admin.get("/api/asignaciones/proximo-dia?desde=2027-03-01").json()["grupo_dias"] == "MJS"
    assert admin.get("/api/asignaciones/proximo-dia?desde=ayer").status_code == 400


def test_dias_de_dialisis_definen_la_hoja(base):
    p = pac(base, "M", 1, 2)
    set_dias(p["id"], "MJS")
    assert puesto(hoja(base, dia(0, 1)), p["id"]) is not None      # martes: le toca
    assert puesto(hoja(base, dia(0, 2)), p["id"]) is None          # miércoles: no
    set_dias(p["id"], "TJS")                                       # código histórico = MJS
    assert puesto(hoja(base, dia(0, 3)), p["id"]) is not None
    assert len(hoja(base, dia(0, 2))["puestos"]) == 47


# ── Cambio de un día vs. permanente ───────────────────────────────────────────

def test_cambio_de_un_dia_no_se_ve_el_jueves(base):
    libre = liberar_cama(base)
    p = pac(base, "M", 1, 1)
    mar, jue = dia(0, 1), dia(0, 3)

    r = mover(base, mar, p["id"], 3, 16)
    assert r.status_code == 201, r.text
    pu = puesto(r.json(), p["id"])
    assert (pu["estacion"], pu["cama"], pu["tipo"]) == (3, 16, "mover")
    assert pu["asignacion"]["creado_por"] == "admin"
    assert ocupantes(r.json(), 1, 1) == []

    # Jueves: ubicación habitual; la base del paciente no cambió.
    pj = puesto(hoja(base, jue), p["id"])
    assert (pj["estacion"], pj["cama"], pj["tipo"]) == (1, 1, "base")
    assert pac(base, "M", 1, 1)["id"] == p["id"]

    # La hoja principal usa base + cambios del día (con ubicación guardada en el registro).
    _, regs = registros(base, mar)
    assert (regs[p["id"]]["estacion"], regs[p["id"]]["cama"]) == (3, 16)
    assert regs[p["id"]]["paciente"]["estacion_base"] == 1
    assert libre["id"] not in regs
    _, regs_j = registros(base, jue)
    assert (regs_j[p["id"]]["estacion"], regs_j[p["id"]]["cama"]) == (1, 1)


def test_cambio_permanente_se_ve_el_jueves_y_no_altera_historial(base):
    liberar_cama(base)                            # cama 48: LMV
    p = pac(base, "M", 1, 3)
    set_dias(p["id"], "MJS")                      # no se cruza con el dueño LMV de la cama 48
    mar, jue, mar_sig = dia(0, 1), dia(0, 3), dia(1, 1)

    # Sesión del martes cerrada con la ubicación vieja.
    s_mar, _ = registros(base, mar)
    assert base.post(f"/api/cierre/{s_mar['id']}/cerrar").status_code == 200

    r = mover(base, jue, p["id"], 3, 16, permanente=True)
    assert r.status_code == 201, r.text
    assert puesto(r.json(), p["id"])["tipo"] == "base"            # ya es su ubicación habitual
    with SessionLocal() as db:
        assert db.query(models.AsignacionDia).filter_by(paciente_id=p["id"]).count() == 0
    pj = puesto(hoja(base, mar_sig), p["id"])
    assert (pj["estacion"], pj["cama"]) == (3, 16)

    # El martes (cerrado) sigue mostrando la cama 3 de la estación 1.
    reg = {r["paciente_id"]: r for r in base.get(f"/api/sesiones/{s_mar['id']}/registros").json()}
    assert (reg[p["id"]]["estacion"], reg[p["id"]]["cama"]) == (1, 3)


def test_hacer_permanente_un_cambio_existente(base):
    liberar_cama(base)
    p = pac(base, "M", 2, 5)
    set_dias(p["id"], "MJS")
    mar = dia(1, 1)
    a = puesto(mover(base, mar, p["id"], 3, 16).json(), p["id"])["asignacion"]
    r = base.post(f"/api/asignaciones/{a['id']}/permanente")
    assert r.status_code == 200, r.text
    assert puesto(hoja(base, dia(1, 5)), p["id"])["cama_global"] == 48


def test_permanente_rechaza_cama_habitual_de_otro(base):
    otro = liberar_cama(base)                     # LMV: el martes su cama está libre…
    p = pac(base, "M", 1, 4)                      # …pero p no tiene días: se cruzan
    r = mover(base, dia(0, 1), p["id"], 3, 16, permanente=True)
    assert r.status_code == 409
    assert otro["nombre"] in r.json()["detail"]
    assert puesto(hoja(base, dia(0, 1)), p["id"])["cama"] == 4   # todo o nada


# ── Conflictos, intercambio y deshacer ────────────────────────────────────────

def test_cama_ocupada_se_reporta_y_se_puede_intercambiar(base):
    a, b = pac(base, "M", 1, 5), pac(base, "M", 2, 6)
    mar = dia(0, 1)
    r = mover(base, mar, a["id"], 2, 6)
    assert r.status_code == 409
    assert "ocupada" in r.json()["detail"] and b["nombre"] in r.json()["detail"]

    r = mover(base, mar, a["id"], 2, 6, intercambiar=True)
    assert r.status_code == 201, r.text
    h = r.json()
    assert ocupantes(h, 2, 6) == [a["id"]] and ocupantes(h, 1, 5) == [b["id"]]
    assert h["conflictos"] == []
    grupo = {puesto(h, a["id"])["asignacion"]["grupo"], puesto(h, b["id"])["asignacion"]["grupo"]}
    assert len(grupo) == 1 and None not in grupo

    # Deshacer uno deshace el intercambio completo.
    r = base.delete(f"/api/asignaciones/{puesto(h, a['id'])['asignacion']['id']}")
    assert r.status_code == 200, r.text
    assert ocupantes(r.json(), 1, 5) == [a["id"]] and ocupantes(r.json(), 2, 6) == [b["id"]]


def test_editar_cambio_y_volver_a_la_base_lo_borra(base):
    liberar_cama(base, 3, 16)
    liberar_cama(base, 3, 15)
    p = pac(base, "M", 1, 7)
    mar = dia(0, 1)
    mover(base, mar, p["id"], 3, 16)
    h = mover(base, mar, p["id"], 3, 15).json()               # editar el mismo cambio
    assert puesto(h, p["id"])["cama"] == 15
    with SessionLocal() as db:
        assert db.query(models.AsignacionDia).filter_by(fecha=mar, paciente_id=p["id"]).count() == 1
    h = mover(base, mar, p["id"], 1, 7).json()                # vuelve a su cama
    assert puesto(h, p["id"])["tipo"] == "base"


def test_deshacer_con_cama_habitual_ocupada_da_conflicto(base):
    liberar_cama(base)
    p = pac(base, "M", 1, 8)
    x = pac(base, "T", 1, 1)
    mar = dia(0, 1)
    h = mover(base, mar, p["id"], 3, 16).json()
    a_id = puesto(h, p["id"])["asignacion"]["id"]
    h = mover(base, mar, x["id"], 1, 8).json()                # transitorio en la cama libre
    assert puesto(h, x["id"])["tipo"] == "transitorio"
    r = base.delete(f"/api/asignaciones/{a_id}")
    assert r.status_code == 409 and "No se puede deshacer" in r.json()["detail"]
    assert puesto(hoja(base, mar), p["id"])["cama"] == 16     # sin cambios


def test_transitorio_de_otro_turno_sale_de_su_turno_ese_dia(base):
    liberar_cama(base)
    x = pac(base, "T", 2, 2)
    mar = dia(0, 1)
    h = mover(base, mar, x["id"], 3, 16).json()
    assert puesto(h, x["id"])["tipo"] == "transitorio"
    ht = hoja(base, mar, "T")
    assert puesto(ht, x["id"]) is None
    assert any(e["paciente"]["id"] == x["id"] for e in ht["excluidos"])
    assert puesto(hoja(base, dia(0, 3), "T"), x["id"]) is not None   # jueves: en su turno

    base.delete(f"/api/asignaciones/{puesto(h, x['id'])['asignacion']['id']}")
    assert puesto(hoja(base, mar, "T"), x["id"]) is not None


def test_reemplazo_programado_llega_a_la_hoja_principal(base):
    q = pac(base, "M", 2, 9)
    s = pac(base, "N", 2, 9)
    mie = dia(0, 2)
    r = base.post("/api/asignaciones", json={"fecha": mie, "turno": "M", "paciente_id": s["id"],
                                             "tipo": "reemplazo", "reemplaza_paciente_id": q["id"]})
    assert r.status_code == 201, r.text
    h = r.json()
    assert ocupantes(h, 2, 9) == [s["id"]]
    assert puesto(h, s["id"])["reemplaza"]["id"] == q["id"]
    assert [d["paciente"]["id"] for d in h["desplazados"]] == [q["id"]]
    assert puesto(hoja(base, mie, "N"), s["id"]) is None

    sesion, regs = registros(base, mie)
    assert regs[q["id"]]["asistencia"] == "H"
    assert regs[q["id"]]["transitorio_paciente"]["id"] == s["id"]
    assert s["id"] not in regs

    # Con la hoja abierta (sin datos anotados) también se puede deshacer.
    a_id = puesto(h, s["id"])["asignacion"]["id"]
    assert base.post(f"/api/asignaciones/{a_id}/permanente").status_code == 409
    assert base.delete(f"/api/asignaciones/{a_id}").status_code == 200
    _, regs = registros(base, mie)
    assert regs[q["id"]]["asistencia"] is None and regs[q["id"]]["transitorio_paciente"] is None


def test_sesion_abierta_se_sincroniza_y_protege_datos(base):
    liberar_cama(base)
    x = pac(base, "T", 3, 3)
    mar = dia(2, 1)
    sesion, regs = registros(base, mar)
    h = mover(base, mar, x["id"], 3, 16).json()
    _, regs = registros(base, mar)
    assert (regs[x["id"]]["estacion"], regs[x["id"]]["cama"]) == (3, 16)
    base.patch(f"/api/sesiones/registros/{regs[x['id']]['id']}", json={"peso_entrada": 70.1})
    r = base.delete(f"/api/asignaciones/{puesto(h, x['id'])['asignacion']['id']}")
    assert r.status_code == 409 and "datos anotados" in r.json()["detail"]


def test_hoja_cerrada_no_admite_cambios(base):
    a, b = pac(base, "M", 1, 10), pac(base, "M", 1, 11)
    jue = dia(0, 3)
    s, _ = registros(base, jue)
    base.post(f"/api/cierre/{s['id']}/cerrar")
    r = mover(base, jue, a["id"], 1, 11, intercambiar=True)
    assert r.status_code == 409 and "cerrada" in r.json()["detail"]
    assert hoja(base, jue)["editable"] is False


def test_validaciones(base):
    p = pac(base, "M", 1, 12)
    assert mover(base, dia(0, 1), p["id"], 4, 1).status_code == 422
    assert mover(base, dia(0, 1), p["id"], 1, 17).status_code == 422
    assert mover(base, "2027-02-30", p["id"], 1, 1).status_code == 409
    assert mover(base, dia(0, 1), 999999, 1, 1).status_code == 409
    assert base.get("/api/asignaciones/hoja/2027-03-02/X").status_code == 400
    assert base.delete("/api/asignaciones/999999").status_code == 409


def test_demo_solo_lectura(base, demo):
    p = pac(demo, "M", 1, 13)
    assert demo.get(f"/api/asignaciones/hoja/{dia(0, 1)}/M").status_code == 200
    assert mover(demo, dia(0, 1), p["id"], 1, 14, intercambiar=True).status_code == 403
    assert demo.delete("/api/asignaciones/1").status_code == 403


# ── Búsqueda ──────────────────────────────────────────────────────────────────

def test_buscar_paciente(base):
    p = pac(base, "M", 1, 1)
    apellido = p["nombre"].split(",")[0].split()[0]          # p. ej. «García»
    sin_tilde = apellido.translate(str.maketrans("áéíóúÁÉÍÓÚ", "aeiouAEIOU")).upper()
    res = base.get(f"/api/asignaciones/buscar?q={sin_tilde}&fecha={dia(0, 1)}").json()
    hit = next(x for x in res if x["paciente"]["id"] == p["id"])
    assert hit["en_hoja"] == {"turno": "M", "estacion": 1, "cama": 1, "cama_global": 1, "tipo": "base"}
    assert hit["le_toca"] is True

    digitos = p["cedula"].replace("V-", "")
    res = base.get(f"/api/asignaciones/buscar?q={digitos}").json()
    assert [x["paciente"]["id"] for x in res] == [p["id"]] and res[0]["en_hoja"] is None
    assert base.get("/api/asignaciones/buscar?q=").status_code == 422
    assert base.get("/api/asignaciones/buscar?q=zzzzqq").json() == []


def test_programacion_epo_y_lista_siguen_funcionando(base):
    """La lista programada (EPO/Fe/incluir) sigue mandando y se combina con los cambios."""
    pacs = base.get("/api/pacientes?turno=M").json()
    mie = dia(3, 2)
    items = [{"paciente_id": p["id"], "epo_programado": i == 0, "hierro_programado": False}
             for i, p in enumerate(pacs[:-1])]                      # el último no se incluye
    assert base.post("/api/programacion", json={"fecha": mie, "turno": "M", "items": items}).status_code == 201
    h = hoja(base, mie)
    assert h["programado"] and len(h["puestos"]) == 47
    assert puesto(h, pacs[0]["id"])["epo"] is True
    assert any(e["paciente"]["id"] == pacs[-1]["id"] for e in h["excluidos"])
    # La cama del no incluido queda libre para un transitorio.
    x = pac(base, "N", 1, 1)
    last = pacs[-1]
    r = mover(base, mie, x["id"], last["estacion"], last["cama"])
    assert r.status_code == 201, r.text
    _, regs = registros(base, mie)
    assert len(regs) == 48 and regs[pacs[0]["id"]]["epo"] is True


def test_migracion_aditiva_en_bd_existente(tmp_path):
    """Una BD previa (sin columnas nuevas) se actualiza sin perder datos y fija la ubicación."""
    from sqlalchemy import create_engine, inspect, text
    eng = create_engine(f"sqlite:///{tmp_path}/vieja.db")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE pacientes (id INTEGER PRIMARY KEY, nombre TEXT, cedula TEXT, "
                       "estacion INTEGER, cama INTEGER, turno TEXT, activo BOOLEAN)"))
        c.execute(text("CREATE TABLE registros (id INTEGER PRIMARY KEY, sesion_id INTEGER, "
                       "paciente_id INTEGER, asistencia TEXT)"))
        c.execute(text("INSERT INTO pacientes VALUES (1, 'Paciente Ficticio', 'V-1', 2, 7, 'M', 1)"))
        c.execute(text("INSERT INTO registros VALUES (1, 1, 1, 'A')"))
    assert set(hoja_dia.asegurar_esquema(eng)) == {"registros.estacion", "registros.cama"}
    assert hoja_dia.asegurar_esquema(eng) == []                       # idempotente
    assert inspect(eng).has_table("asignaciones_dia")
    with eng.connect() as c:
        assert c.execute(text("SELECT estacion, cama, asistencia FROM registros")).one() == (2, 7, "A")
    eng.dispose()
