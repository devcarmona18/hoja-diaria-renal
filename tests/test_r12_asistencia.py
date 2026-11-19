"""R12 — asistencia mensual (programadas vs asistidas), cierre de mes inmutable, reapertura auditada, CSV."""
import pytest

import models
from database import SessionLocal
from tests.helpers_w2a import marcar, paciente_y_mes, registro_de
from services import asistencia as srv

MES = "2025-03"          # 3-mar-2025 es lunes; días LMV: 3, 5, 7, 10, 12, 14
FECHAS = ["2025-03-03", "2025-03-05", "2025-03-07", "2025-03-10", "2025-03-12", "2025-03-14"]


def _fila(cli, pid, mes=MES):
    anio, m = mes.split("-")
    d = cli.get(f"/api/estadisticas/asistencia/{anio}/{m}").json()
    return d, next((f for f in d["pacientes"] if f["paciente_id"] == pid), None)


def _periodo(pid, desde, hasta, origen="inactivo"):
    with SessionLocal() as db:
        db.add(models.PacienteInactividad(paciente_id=pid, desde=desde, hasta=hasta, origen=origen))
        db.commit()


def test_perfecta_asistencia_llega_a_100(admin):
    with paciente_y_mes(admin, "T-R12-001", MES) as p:
        for f in FECHAS:
            marcar(admin, f, "N", p["id"], asistencia="A")
        _, fila = _fila(admin, p["id"])
        assert (fila["programadas"], fila["asistidas"], fila["porcentaje"]) == (6, 6, 100.0)


def test_faltas_hospitalizado_e_inactivo(admin):
    """3 A + 1 NA = 3/4; el día H y los días inactivos NO cuentan como programados."""
    with paciente_y_mes(admin, "T-R12-002", MES) as p:
        for f in FECHAS[:3]:
            marcar(admin, f, "N", p["id"], asistencia="A")
        marcar(admin, FECHAS[3], "N", p["id"], asistencia="NA")
        marcar(admin, FECHAS[4], "N", p["id"], asistencia="H")          # 12-mar: hospitalizado
        marcar(admin, FECHAS[5], "N", p["id"])                          # 14-mar: sin marcar...
        _periodo(p["id"], "2025-03-14", "2025-03-20")                   # ...pero estaba inactivo
        d, fila = _fila(admin, p["id"])
        assert (fila["programadas"], fila["asistidas"], fila["faltas"], fila["excluidas"]) == (4, 3, 1, 2)
        assert fila["porcentaje"] == 75.0
        assert d["totales"]["pacientes_atendidos"] >= 1


def test_archivado_excluye_los_dias_posteriores_pero_conserva_los_previos(admin):
    with paciente_y_mes(admin, "T-R12-003", MES) as p:
        for f in FECHAS:
            marcar(admin, f, "N", p["id"], asistencia="A" if f < "2025-03-10" else "NA")
        _periodo(p["id"], "2025-03-10", None, origen="archivado")       # archivado desde el 10
        _, fila = _fila(admin, p["id"])
        assert (fila["programadas"], fila["asistidas"]) == (3, 3)
        assert fila["porcentaje"] == 100.0


def test_dia_asistido_estando_inactivo_cuenta(admin):
    with paciente_y_mes(admin, "T-R12-004", MES) as p:
        marcar(admin, FECHAS[0], "N", p["id"], asistencia="A")
        marcar(admin, FECHAS[1], "N", p["id"], asistencia="A")
        _periodo(p["id"], "2025-03-01", "2025-03-31")
        _, fila = _fila(admin, p["id"])
        assert (fila["programadas"], fila["asistidas"]) == (2, 2)      # asistió => estaba programado


def test_paciente_nuevo_no_cuenta_dias_anteriores_a_su_primera_hoja(admin):
    with paciente_y_mes(admin, "T-R12-005", MES) as p:
        # el paciente se crea DESPUÉS de las 3 primeras sesiones: sus filas empiezan el 10
        for f in FECHAS[:3]:
            admin.get(f"/api/sesiones/{f}/N")
        for f in FECHAS[3:]:
            marcar(admin, f, "N", p["id"], asistencia="A")
        with SessionLocal() as db:   # simula que no estaba en las hojas anteriores
            for s in db.query(models.Sesion).filter(models.Sesion.fecha.in_(FECHAS[:3])).all():
                db.query(models.Registro).filter_by(sesion_id=s.id, paciente_id=p["id"]).delete()
            db.commit()
        _, fila = _fila(admin, p["id"])
        assert (fila["programadas"], fila["asistidas"]) == (3, 3)


def test_consultar_cualquier_mes_y_totales(admin):
    with paciente_y_mes(admin, "T-R12-006", MES) as p:
        marcar(admin, FECHAS[0], "N", p["id"], asistencia="A")
        d, _ = _fila(admin, p["id"])
        t = d["totales"]
        assert t["sesiones_asistidas"] >= 1 and t["sesiones_programadas"] >= t["sesiones_asistidas"]
        assert t["pacientes_atendidos"] >= 1
        assert admin.get("/api/estadisticas/asistencia/2019/01").json()["pacientes"] == []   # mes sin datos
        assert admin.get("/api/estadisticas/asistencia/2025/13").status_code == 422


def test_cerrar_mes_es_inmutable_y_reabrir_se_audita(admin, demo):
    with paciente_y_mes(admin, "T-R12-007", MES) as p:
        for f in FECHAS:
            marcar(admin, f, "N", p["id"], asistencia="A")
        # el demo (solo lectura) no puede cerrar
        assert demo.post("/api/estadisticas/asistencia/2025/03/cerrar").status_code == 403
        r = admin.post("/api/estadisticas/asistencia/2025/03/cerrar")
        assert r.status_code == 200, r.text
        assert r.json()["cerrado"] is True and r.json()["cierre"]["cerrado_por"]
        # con el mes cerrado sus hojas son de solo lectura (decisión del responsable)
        hoja = admin.get(f"/api/sesiones/{FECHAS[0]}/N").json()
        assert hoja["cerrada"] is False and hoja["mes_cerrado"] is True
        _, reg = registro_de(admin, FECHAS[0], "N", p["id"])
        r = admin.patch(f"/api/sesiones/registros/{reg['id']}", json={"asistencia": "NA"})
        assert r.status_code == 409 and r.json()["detail"] == "El mes está cerrado; reábralo para editar"
        _, fila = _fila(admin, p["id"])
        assert (fila["programadas"], fila["asistidas"], fila["porcentaje"]) == (6, 6, 100.0)
        # no se puede cerrar dos veces
        assert admin.post("/api/estadisticas/asistencia/2025/03/cerrar").status_code == 409
        # ni modificar/borrar el registro guardado por ORM
        with SessionLocal() as db:
            reg = db.query(models.AsistenciaMensual).filter_by(mes=MES, paciente_id=p["id"]).one()
            reg.asistidas = 0
            with pytest.raises(ValueError):
                db.commit()
            db.rollback()
            db.delete(db.query(models.AsistenciaMensual).filter_by(mes=MES, paciente_id=p["id"]).one())
            with pytest.raises(ValueError):
                db.commit()
            db.rollback()
        # el mes cerrado tampoco se «limpia»
        assert admin.delete("/api/historial/mes/2025/03").status_code == 409
        # reabrir: motivo obligatorio, solo admin, queda auditado
        assert demo.post("/api/estadisticas/asistencia/2025/03/reabrir", json={"motivo": "xx corrección"}).status_code == 403
        assert admin.post("/api/estadisticas/asistencia/2025/03/reabrir", json={"motivo": "x"}).status_code == 422
        r = admin.post("/api/estadisticas/asistencia/2025/03/reabrir", json={"motivo": "Corrección de una falta"})
        assert r.status_code == 200 and r.json()["cerrado"] is False
        marcar(admin, FECHAS[0], "N", p["id"], asistencia="NA")          # reabierto: se edita
        _, fila = _fila(admin, p["id"])
        assert fila["asistidas"] == 5                                   # de nuevo en vivo
        aud = admin.get("/api/estadisticas/asistencia/2025/03/auditoria").json()
        assert [a["accion"] for a in aud] == ["reabrir", "cerrar"]
        assert aud[0]["motivo"] == "Corrección de una falta" and aud[0]["usuario"]
        # se puede volver a cerrar y el cierre anterior queda como historial
        assert admin.post("/api/estadisticas/asistencia/2025/03/cerrar").status_code == 200
        with SessionLocal() as db:
            assert db.query(models.CierreMes).filter_by(mes=MES).count() == 2


def test_no_se_cierra_el_mes_en_curso_sin_forzar(admin):
    from services.tiempo import hoy_local
    h = hoy_local()
    r = admin.post(f"/api/estadisticas/asistencia/{h.year}/{h.month}/cerrar")
    assert r.status_code == 409
    assert admin.post("/api/estadisticas/asistencia/2018/05/cerrar").status_code == 400   # sin datos


def test_csv_exporta_totales_y_neutraliza_formulas(admin):
    with paciente_y_mes(admin, "T-R12-008", MES, nombre="=CMD Ficticio, Prueba") as p:
        marcar(admin, FECHAS[0], "N", p["id"], asistencia="A")
        r = admin.get("/api/estadisticas/asistencia/2025/03/csv")
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
        assert "attachment" in r.headers["content-disposition"]
        txt = r.content.decode("utf-8-sig")
        lineas = txt.strip().splitlines()
        assert lineas[0].startswith("mes,estado_mes,paciente,cedula")
        assert "'=CMD Ficticio" in txt and "\n=CMD" not in txt
        assert lineas[-1].startswith("2025-03,abierto,TOTAL")


def test_regla_pura_validar_mes():
    with pytest.raises(srv.ReglaError):
        srv.validar_mes("2025-3")
