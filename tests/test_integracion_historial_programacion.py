"""Integración R2/R7 (programación por día) con R11–R13 (historial, inactividad, archivo).

- La hoja completa de Historial usa la cama de ESE día (registros.estacion/cama).
- Un paciente archivado sale de la composición del día y sus cambios de un día no cuentan.
- Los periodos de inactividad se registran por cualquier vía (toggle, PUT, archivar).
Datos FICTICIOS; cada prueba deja la base como estaba.
"""
import models
from database import SessionLocal
from tests.helpers_w2a import borrar_paciente_total, crear_paciente
from tests.test_programacion_dia import base, dia, hoja, mover, pac, puesto, registros, set_dias  # noqa: F401


def _periodos(pid):
    with SessionLocal() as db:
        return [(x.origen, x.hasta) for x in
                db.query(models.PacienteInactividad).filter_by(paciente_id=pid).order_by(models.PacienteInactividad.id)]


def test_historial_hoja_completa_usa_la_cama_del_dia(base):
    libre = pac(base, "M", 3, 16)
    set_dias(libre["id"], "LMV")                 # el martes la cama 3-16 queda libre
    p = pac(base, "M", 1, 1)
    set_dias(p["id"], "MJS")
    mar = dia(2, 1)
    assert mover(base, mar, p["id"], 3, 16).status_code == 201
    ses, regs = registros(base, mar)
    assert (regs[p["id"]]["estacion"], regs[p["id"]]["cama"]) == (3, 16)
    base.patch(f"/api/sesiones/registros/{regs[p['id']]['id']}", json={"asistencia": "A"})

    def fila():
        h = base.get(f"/api/historial/hoja?fecha={mar}&turno=M").json()
        return next(x for x in h["filas"] if x["paciente_id"] == p["id"])

    f = fila()
    assert (f["estacion"], f["cama"], f["cama_display"]) == (3, 16, 48)    # no su base 1-1
    assert base.post(f"/api/cierre/{ses['id']}/cerrar").status_code == 200
    f = fila()
    assert (f["estacion"], f["cama"], f["con_foto"], f["turno"]) == (3, 16, True, "M")


def test_archivado_sale_de_la_hoja_del_dia_y_de_sus_cambios(base):
    libre = pac(base, "M", 3, 16)
    set_dias(libre["id"], "LMV")
    x = crear_paciente(base, "T-INT-ARCH-1", turno="T", estacion=1, cama=1, dias="MJS")
    try:
        mar = dia(3, 1)
        assert mover(base, mar, x["id"], 3, 16).status_code == 201      # cambio de un día en M
        assert puesto(hoja(base, mar), x["id"]) is not None
        r = base.post(f"/api/pacientes/{x['id']}/archivar", json={"motivo": "Traslado a otra unidad"})
        assert r.status_code == 200, r.text
        h = hoja(base, mar)
        assert puesto(h, x["id"]) is None
        assert puesto(hoja(base, dia(3, 3), "T"), x["id"]) is None      # ni en su base
        _, regs = registros(base, dia(3, 5), "T")
        assert x["id"] not in regs
        r = mover(base, mar, x["id"], 3, 16)
        assert r.status_code in (400, 409) and "archivado" in r.text
        busq = base.get("/api/asignaciones/buscar", params={"q": "Zapata Ficticio"}).json()
        assert all(b["paciente"]["id"] != x["id"] for b in busq)
        assert _periodos(x["id"])[-1] == ("archivado", None)
        assert base.post(f"/api/pacientes/{x['id']}/restaurar").status_code == 200
        assert puesto(hoja(base, dia(3, 3), "T"), x["id"]) is not None
        assert _periodos(x["id"])[-1][0] == "archivado" and _periodos(x["id"])[-1][1] is not None
    finally:
        borrar_paciente_total("T-INT-ARCH-1")


def test_reemplazo_de_un_archivado_deja_al_suplente_como_transitorio(base):
    q = crear_paciente(base, "T-INT-ARCH-2", turno="M", estacion=3, cama=16, dias="MJS")
    s = crear_paciente(base, "T-INT-ARCH-3", turno="T", estacion=1, cama=1, dias="LMV")
    try:
        with SessionLocal() as db:   # la cama 3-16 de M solo para q ese martes
            for o in db.query(models.Paciente).filter_by(turno="M", estacion=3, cama=16).all():
                if o.id != q["id"]:
                    o.dias = "LMV"
            db.commit()
        mar = dia(4, 1)
        r = base.post("/api/asignaciones", json={"fecha": mar, "turno": "M", "paciente_id": s["id"],
                                                 "tipo": "reemplazo", "reemplaza_paciente_id": q["id"]})
        assert r.status_code == 201, r.text
        assert base.post(f"/api/pacientes/{q['id']}/archivar", json={"motivo": "Fallecido"}).status_code == 200
        h = hoja(base, mar)
        pu = puesto(h, s["id"])
        assert pu is not None and pu["tipo"] == "transitorio" and (pu["estacion"], pu["cama"]) == (3, 16)
        _, regs = registros(base, mar)
        assert q["id"] not in regs and s["id"] in regs
    finally:
        borrar_paciente_total("T-INT-ARCH-3")
        borrar_paciente_total("T-INT-ARCH-2")


def test_inactividad_se_registra_por_put_y_al_crear_inactivo(base):
    p = crear_paciente(base, "T-INT-INACT-1")
    q = None
    try:
        datos = {k: v for k, v in p.items() if k in models.Paciente.__table__.columns.keys() and k != "id"}
        r = base.put(f"/api/pacientes/{p['id']}", json={**datos, "activo": False, "motivo_inactivo": "otro"})
        assert r.status_code == 200, r.text
        assert _periodos(p["id"]) == [("inactivo", None)]
        r = base.put(f"/api/pacientes/{p['id']}", json={**datos, "activo": True})
        assert r.status_code == 200
        assert _periodos(p["id"])[0][1] is not None
        q = crear_paciente(base, "T-INT-INACT-2", activo=False, motivo_inactivo="hospitalizado")
        assert _periodos(q["id"]) == [("inactivo", None)]
    finally:
        borrar_paciente_total("T-INT-INACT-1")
        borrar_paciente_total("T-INT-INACT-2")
