"""R13 — «Eliminar paciente» = archivar: visibilidad, ventana ARCHIVO_DIAS, restauración y datos conservados."""
from datetime import timedelta

import config
import models
from database import SessionLocal
from services import pacientes as srv
from tests.helpers_w2a import marcar, paciente_y_mes

MES = "2025-05"
FECHA = "2025-05-05"     # lunes


def _ids(r):
    return {x["id"] for x in r.json()} if isinstance(r.json(), list) else {x["id"] for x in r.json()["pacientes"]}


def _envejecer(pid, dias):
    with SessionLocal() as db:
        db.get(models.Paciente, pid).archivado_en = srv.ahora_utc() - timedelta(days=dias)
        db.commit()


def test_archivar_oculta_de_listas_hoja_y_programacion(admin):
    with paciente_y_mes(admin, "T-R13A-001", MES) as p:
        pid = p["id"]
        admin.post("/api/programacion", json={"fecha": "2999-01-04", "turno": "N",
                                              "items": [{"paciente_id": pid}]})
        r = admin.post(f"/api/pacientes/{pid}/archivar", json={"motivo": "Fallecimiento"})
        assert r.status_code == 200, r.text
        assert r.json()["motivo"] == "Fallecimiento" and r.json()["dias_restantes"] == config.ARCHIVO_DIAS
        assert pid not in _ids(admin.get("/api/pacientes"))
        assert pid not in _ids(admin.get("/api/pacientes?activo=true"))
        assert pid not in _ids(admin.get("/api/pacientes?activo=false"))
        assert pid not in _ids(admin.get("/api/pacientes?turno=N"))
        with SessionLocal() as db:
            assert pid not in srv.ids_activos(db) and pid not in {x.id for x in srv.listar_activos(db)}
            assert db.query(models.Programacion).filter_by(paciente_id=pid).count() == 0
        # una hoja nueva ya no lo incluye
        ses = admin.get(f"/api/sesiones/{FECHA}/N").json()
        regs = admin.get(f"/api/sesiones/{ses['id']}/registros").json()
        assert pid not in {r["paciente_id"] for r in regs}
        assert admin.post(f"/api/sesiones/{ses['id']}/paciente/{pid}").status_code == 400
        # aparece en «Archivados»
        arch = admin.get("/api/pacientes/archivados").json()
        assert arch["archivo_dias"] == config.ARCHIVO_DIAS and pid in _ids(admin.get("/api/pacientes/archivados"))
        # no se edita ni se alterna estando archivado
        assert admin.patch(f"/api/pacientes/{pid}/toggle-activo", json={}).status_code == 409
        assert admin.put(f"/api/pacientes/{pid}", json={**p, "nombre": "Otro"}).status_code == 409
        assert admin.post(f"/api/pacientes/{pid}/archivar", json={"motivo": "de nuevo"}).status_code == 409


def test_archivado_conserva_sesiones_labs_y_asistencia(admin):
    with paciente_y_mes(admin, "T-R13A-002", MES) as p:
        pid = p["id"]
        marcar(admin, FECHA, "N", pid, asistencia="A", peso_entrada=71.0, peso_salida=70.0)
        admin.post("/api/laboratorios", json={"paciente_id": pid, "fecha": "2025-05-05", "tipo": "Hb", "valor": 9.1})
        assert admin.post(f"/api/pacientes/{pid}/archivar", json={"motivo": "Traslado"}).status_code == 200
        # pasada la ventana: sale de la lista pero nada se borra
        _envejecer(pid, config.ARCHIVO_DIAS + 1)
        assert pid not in _ids(admin.get("/api/pacientes/archivados"))
        with SessionLocal() as db:
            assert db.get(models.Paciente, pid).archivado_en is not None
            assert db.query(models.Registro).filter_by(paciente_id=pid).count() >= 1
        # sigue visible en Historial, Estadísticas y laboratorios
        h = admin.get(f"/api/historial/hoja?fecha={FECHA}&turno=N").json()
        fila = next(f for f in h["filas"] if f["paciente_id"] == pid)
        assert fila["asistencia"] == "A" and fila["peso_entrada"] == 71.0
        est = admin.get("/api/estadisticas/asistencia/2025/05").json()
        assert next(f for f in est["pacientes"] if f["paciente_id"] == pid)["archivado"] is True
        assert len(admin.get(f"/api/laboratorios/{pid}").json()) == 1
        assert admin.get(f"/api/labs/comparativa/{pid}?tipo=Hb").json()["tomas"][0]["valor"] == 9.1


def test_ventana_configurable_y_restauracion(admin, monkeypatch):
    with paciente_y_mes(admin, "T-R13A-003", MES) as p:
        pid = p["id"]
        admin.post(f"/api/pacientes/{pid}/archivar", json={"motivo": "Retiro voluntario"})
        _envejecer(pid, 10)
        assert pid in _ids(admin.get("/api/pacientes/archivados"))           # 10 d < 180 d
        monkeypatch.setattr(config, "ARCHIVO_DIAS", 7)
        assert pid not in _ids(admin.get("/api/pacientes/archivados"))       # 10 d > 7 d
        assert admin.post(f"/api/pacientes/{pid}/restaurar").status_code == 409   # fuera de ventana
        monkeypatch.setattr(config, "ARCHIVO_DIAS", 180)
        r = admin.post(f"/api/pacientes/{pid}/restaurar")
        assert r.status_code == 200 and r.json()["activo"] is True
        assert pid in _ids(admin.get("/api/pacientes?activo=true"))
        assert pid not in _ids(admin.get("/api/pacientes/archivados"))
        assert admin.post(f"/api/pacientes/{pid}/restaurar").status_code == 409   # ya no está archivado


def test_solo_admin_archiva_y_restaura(admin, demo, anonimo):
    with paciente_y_mes(admin, "T-R13A-004", MES) as p:
        pid = p["id"]
        assert demo.post(f"/api/pacientes/{pid}/archivar", json={"motivo": "xx"}).status_code == 403
        assert anonimo.post(f"/api/pacientes/{pid}/archivar", json={"motivo": "xx"}).status_code == 401
        assert admin.post(f"/api/pacientes/{pid}/archivar", json={"motivo": ""}).status_code == 422
        admin.post(f"/api/pacientes/{pid}/archivar", json={"motivo": "Fallecimiento"})
        assert demo.get("/api/pacientes/archivados").status_code == 200      # lectura permitida
        assert demo.post(f"/api/pacientes/{pid}/restaurar").status_code == 403
        assert admin.post("/api/pacientes/999999/archivar", json={"motivo": "xx"}).status_code == 404


def test_archivar_no_borra_filas_con_datos_de_hojas_abiertas(admin):
    """Una hoja abierta con datos del paciente conserva su fila; una vacía sí se retira."""
    with paciente_y_mes(admin, "T-R13A-005", MES) as p:
        pid = p["id"]
        ses, _ = marcar(admin, FECHA, "N", pid, asistencia="A", peso_entrada=70.0)
        admin.get(f"/api/sesiones/2025-05-07/N")        # hoja abierta SIN datos del paciente
        admin.post(f"/api/pacientes/{pid}/archivar", json={"motivo": "Traslado"})
        with SessionLocal() as db:
            fechas = {f for (f,) in db.query(models.Sesion.fecha).join(
                models.Registro, models.Registro.sesion_id == models.Sesion.id).filter(
                models.Registro.paciente_id == pid).all()}
        assert FECHA in fechas and "2025-05-07" not in fechas


def test_archivar_y_restaurar_registran_periodos_de_inactividad(admin):
    with paciente_y_mes(admin, "T-R13A-006", MES) as p:
        pid = p["id"]
        admin.post(f"/api/pacientes/{pid}/archivar", json={"motivo": "Traslado"})
        with SessionLocal() as db:
            per = db.query(models.PacienteInactividad).filter_by(paciente_id=pid).all()
            assert [(x.origen, x.hasta) for x in per] == [("archivado", None)]
        admin.post(f"/api/pacientes/{pid}/restaurar")
        with SessionLocal() as db:
            per = db.query(models.PacienteInactividad).filter_by(paciente_id=pid).all()
            assert len(per) == 1 and per[0].hasta is not None


def test_inactivar_por_r10_abre_periodo(admin):
    with paciente_y_mes(admin, "T-R13A-007", MES) as p:
        pid = p["id"]
        admin.patch(f"/api/pacientes/{pid}/toggle-activo", json={"motivo": "hospitalizado"})
        with SessionLocal() as db:
            per = db.query(models.PacienteInactividad).filter_by(paciente_id=pid).all()
            assert [(x.origen, x.hasta, x.motivo) for x in per] == [("inactivo", None, "hospitalizado")]
        admin.patch(f"/api/pacientes/{pid}/toggle-activo", json={})
        with SessionLocal() as db:
            assert db.query(models.PacienteInactividad).filter_by(paciente_id=pid).one().hasta is not None


def test_ventana_por_defecto_es_de_seis_meses(monkeypatch):
    monkeypatch.delenv("ARCHIVO_DIAS", raising=False)
    import importlib
    import config as cfg
    try:
        assert importlib.reload(cfg).ARCHIVO_DIAS == 180
    finally:
        importlib.reload(cfg)
