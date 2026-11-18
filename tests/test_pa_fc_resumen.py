"""R3 — PA de pie y FC por sesión + resumen de sesiones del paciente."""
import pytest

from tests.helpers_w1 import borrar_sesion

FECHAS = ["2026-06-01", "2026-06-03", "2026-06-10", "2026-04-01"]


@pytest.fixture
def sesiones(admin):
    yield admin
    for f in FECHAS:
        borrar_sesion(f, "T")


def _reg(admin, fecha, idx=0):
    ses = admin.get(f"/api/sesiones/{fecha}/T").json()
    return ses, admin.get(f"/api/sesiones/{ses['id']}/registros").json()[idx]


def test_guarda_pa_pie_y_fc(sesiones):
    admin = sesiones
    _, reg = _reg(admin, "2026-06-01")
    r = admin.patch(f"/api/sesiones/registros/{reg['id']}",
                    json={"pa_pie_sistolica": 120, "pa_pie_diastolica": 80, "fc": 72})
    assert r.status_code == 200, r.text
    assert (r.json()["pa_pie_sistolica"], r.json()["pa_pie_diastolica"], r.json()["fc"]) == (120, 80, 72)
    # persiste
    ses = admin.get("/api/sesiones/2026-06-01/T").json()
    assert admin.get(f"/api/sesiones/{ses['id']}/registros").json()[0]["fc"] == 72
    # se puede borrar con null
    r = admin.patch(f"/api/sesiones/registros/{reg['id']}", json={"fc": None})
    assert r.json()["fc"] is None


@pytest.mark.parametrize("payload", [
    {"pa_pie_sistolica": 49}, {"pa_pie_sistolica": 261}, {"pa_pie_diastolica": 29}, {"pa_pie_diastolica": 151},
    {"fc": 29}, {"fc": 221}, {"fc": "rápido"},
])
def test_rangos_invalidos(sesiones, payload):
    admin = sesiones
    _, reg = _reg(admin, "2026-06-01")
    assert admin.patch(f"/api/sesiones/registros/{reg['id']}", json=payload).status_code == 422


@pytest.mark.parametrize("payload", [
    {"pa_pie_sistolica": 50, "pa_pie_diastolica": 30, "fc": 30},
    {"pa_pie_sistolica": 260, "pa_pie_diastolica": 150, "fc": 220},
])
def test_limites_validos(sesiones, payload):
    admin = sesiones
    _, reg = _reg(admin, "2026-06-01")
    assert admin.patch(f"/api/sesiones/registros/{reg['id']}", json=payload).status_code == 200


def test_sistolica_debe_superar_diastolica(sesiones):
    admin = sesiones
    _, reg = _reg(admin, "2026-06-01")
    url = f"/api/sesiones/registros/{reg['id']}"
    assert admin.patch(url, json={"pa_pie_diastolica": 90}).status_code == 200
    assert admin.patch(url, json={"pa_pie_sistolica": 85}).status_code == 422    # contra lo guardado
    assert admin.patch(url, json={"pa_pie_sistolica": 90}).status_code == 422
    assert admin.patch(url, json={"pa_pie_sistolica": 130}).status_code == 200


def test_demo_no_puede_escribir_pa(demo, admin):
    _, reg = _reg(admin, "2026-06-01")
    try:
        assert demo.patch(f"/api/sesiones/registros/{reg['id']}", json={"fc": 70}).status_code == 403
    finally:
        borrar_sesion("2026-06-01", "T")


def test_resumen_sesiones(sesiones):
    admin = sesiones
    datos = {}
    for fecha, (ent, sal, fc, ktv) in {"2026-06-01": (72.0, 69.5, 70, 1.4), "2026-06-03": (71.0, 69.0, 75, 1.5),
                                        "2026-06-10": (70.5, 68.5, 80, 1.6), "2026-04-01": (70.0, 68.0, 60, 1.2)}.items():
        ses, reg = _reg(admin, fecha)
        datos[fecha] = reg
        assert admin.patch(f"/api/sesiones/registros/{reg['id']}", json={
            "asistencia": "A", "peso_entrada": ent, "peso_salida": sal, "fc": fc, "ktv": ktv,
            "pa_pie_sistolica": 118, "pa_pie_diastolica": 76, "observaciones": f"obs {fecha}"}).status_code == 200
    pid = datos["2026-06-01"]["paciente_id"]
    peso_seco = datos["2026-06-01"]["paciente"]["peso_seco"]

    r = admin.get(f"/api/pacientes/{pid}/resumen-sesiones?hasta=2026-06-10&dias=14")
    assert r.status_code == 200, r.text
    res = r.json()
    assert (res["desde"], res["hasta"]) == ("2026-05-28", "2026-06-10")
    assert [s["fecha"] for s in res["sesiones"]] == ["2026-06-10", "2026-06-03", "2026-06-01"]   # sin 2026-04-01
    s = res["sesiones"][0]
    assert s["turno"] == "T" and s["asistencia"] == "A"
    assert (s["peso_entrada"], s["peso_salida"], s["peso_seco"]) == (70.5, 68.5, peso_seco)
    assert s["perdida"] == 2.0 and s["ganancia"] == round(70.5 - peso_seco, 2)
    assert (s["pa_pie_sistolica"], s["pa_pie_diastolica"], s["fc"], s["ktv"]) == (118, 76, 80, 1.6)
    assert s["observaciones"] == "obs 2026-06-10"

    # ventana de 3 días: solo la última
    r = admin.get(f"/api/pacientes/{pid}/resumen-sesiones?hasta=2026-06-10&dias=3").json()
    assert [s["fecha"] for s in r["sesiones"]] == ["2026-06-10"]
    # sin sesiones en el período
    assert admin.get(f"/api/pacientes/{pid}/resumen-sesiones?hasta=2025-01-01").json()["sesiones"] == []


def test_resumen_errores(admin):
    assert admin.get("/api/pacientes/999999/resumen-sesiones").status_code == 404
    pid = admin.get("/api/pacientes").json()[0]["id"]
    assert admin.get(f"/api/pacientes/{pid}/resumen-sesiones?hasta=ayer").status_code == 422
    assert admin.get(f"/api/pacientes/{pid}/resumen-sesiones?dias=0").status_code == 422
    assert admin.get(f"/api/pacientes/{pid}/resumen-sesiones?dias=61").status_code == 422


def test_resumen_demo_puede_leer(demo):
    pid = demo.get("/api/pacientes").json()[0]["id"]
    assert demo.get(f"/api/pacientes/{pid}/resumen-sesiones").status_code == 200
