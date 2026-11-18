"""R11 — hoja completa de un día cerrado «como quedó» + resumen del día (asistidos, EPO, Fe)."""
import models
from database import SessionLocal
from tests.helpers_w2a import marcar, paciente_y_mes

FECHA = "2025-04-02"
MES = "2025-04"


def _hoja(cli, turno="N", fecha=FECHA):
    return cli.get(f"/api/historial/hoja?fecha={fecha}" + (f"&turno={turno}" if turno else ""))


def test_hoja_completa_con_todas_las_columnas_y_resumen(admin):
    with paciente_y_mes(admin, "T-R11-001", MES, epo_dosis=8000.0, tipo_filtro="FX60", heparina_ui_kg=15) as p:
        ses, _ = marcar(admin, FECHA, "N", p["id"], asistencia="A", peso_entrada=72.5, peso_salida=70.4,
                        pa_pie_sistolica=118, pa_pie_diastolica=76, fc=70, ktv=1.45, epo=True, hierro=True,
                        observaciones="Sin novedades")
        h = _hoja(admin).json()
        assert h["sesiones"] == [{"id": ses["id"], "turno": "N", "cerrada": False}]
        f = next(x for x in h["filas"] if x["paciente_id"] == p["id"])
        assert (f["estacion"], f["cama"], f["cama_display"]) == (3, 16, 48)
        assert (f["peso_entrada"], f["peso_salida"], f["perdida"], f["ganancia"]) == (72.5, 70.4, 2.1, 2.5)
        assert (f["pa_pie_sistolica"], f["pa_pie_diastolica"], f["fc"], f["ktv"]) == (118, 76, 70, 1.45)
        assert (f["epo"], f["hierro"], f["tipo_filtro"], f["heparina_ui_kg"]) == (True, True, "FX60", 15)
        assert f["observaciones"] == "Sin novedades"
        r = h["resumen"]
        assert r["sesiones"] == 1 and r["asistidos"] == 1
        assert r["epo_aplicaciones"] == 1 and r["epo_ui"] == 8000 and r["epo_jeringas"] == 2.0
        assert r["fe_aplicado"] == 1 and r["epo_dosis_estimada"] == 0


def test_epo_sin_dosis_asume_una_jeringa_de_4000(admin):
    with paciente_y_mes(admin, "T-R11-002", MES) as p:
        marcar(admin, FECHA, "N", p["id"], asistencia="A", epo=True)
        marcar(admin, FECHA, "N", p["id"], asistencia="A", epo=True, hierro=False)
        r = _hoja(admin).json()["resumen"]
        assert (r["epo_ui"], r["epo_jeringas"], r["epo_dosis_estimada"]) == (4000, 1.0, 1)


def test_epo_y_fe_solo_cuentan_si_asistio(admin):
    with paciente_y_mes(admin, "T-R11-003", MES) as p:
        marcar(admin, FECHA, "N", p["id"], asistencia="NA", epo=True, hierro=True)
        r = _hoja(admin).json()["resumen"]
        assert (r["epo_aplicaciones"], r["fe_aplicado"], r["asistidos"]) == (0, 0, 0)
        assert r["no_asiste"] >= 1


def test_dia_cerrado_se_ve_como_quedo_aunque_el_paciente_cambie(admin):
    with paciente_y_mes(admin, "T-R11-004", MES) as p:
        ses, _ = marcar(admin, FECHA, "N", p["id"], asistencia="A", peso_entrada=75.0, peso_salida=71.0)
        assert admin.post(f"/api/cierre/{ses['id']}/cerrar").status_code == 200
        # después de cerrar: cambia de cama, de estación y de peso seco
        with SessionLocal() as db:
            pac = db.get(models.Paciente, p["id"])
            pac.estacion, pac.cama, pac.peso_seco = 1, 2, 60.0
            db.commit()
        f = next(x for x in _hoja(admin).json()["filas"] if x["paciente_id"] == p["id"])
        assert (f["estacion"], f["cama"], f["peso_seco"], f["ganancia"], f["con_foto"]) == (3, 16, 70.0, 5.0, True)
        # al reabrir vuelve a los datos vivos
        assert admin.post(f"/api/cierre/{ses['id']}/reabrir").status_code == 200
        f = next(x for x in _hoja(admin).json()["filas"] if x["paciente_id"] == p["id"])
        assert (f["estacion"], f["cama"], f["con_foto"]) == (1, 2, False)


def test_filtro_por_turno_y_errores(admin):
    with paciente_y_mes(admin, "T-R11-005", MES) as p:
        marcar(admin, FECHA, "N", p["id"], asistencia="A")
        admin.get(f"/api/sesiones/{FECHA}/T")
        todo = _hoja(admin, turno=None).json()
        assert [s["turno"] for s in todo["sesiones"]] == ["T", "N"] and todo["resumen"]["sesiones"] == 2
        assert {f["sesion_turno"] for f in todo["filas"]} == {"T", "N"}
        solo_n = _hoja(admin, "N").json()
        assert [s["turno"] for s in solo_n["sesiones"]] == ["N"] and solo_n["resumen"]["sesiones"] == 1
        assert _hoja(admin, "N", fecha="2001-01-01").status_code == 404
        assert _hoja(admin, "X").status_code == 422
        assert admin.get("/api/historial/hoja?fecha=hoy").status_code == 422


def test_demo_puede_consultar(admin, demo):
    with paciente_y_mes(admin, "T-R11-006", MES):
        admin.get(f"/api/sesiones/{FECHA}/N")
        assert _hoja(demo).status_code == 200
