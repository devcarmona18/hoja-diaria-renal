"""R13 — panel por estado (bajo/normal/alto/muy alto), rangos configurables y comparativa."""
import pytest

from services import labs as srv
from tests.helpers_w2a import borrar_paciente_total, crear_paciente

MEDICO = "Dr. Prueba Ficticio"


@pytest.fixture
def pacientes(admin):
    """4 pacientes ficticios con Hb en cada estado + uno sin dato."""
    cedulas = []
    ids = {}
    for i, (clave, hb) in enumerate([("bajo", 8.0), ("normal", 11.0), ("alto", 13.0), ("muy_alto", 15.0),
                                     ("sin_dato", None)]):
        ced = f"T-R13L-00{i}"
        cedulas.append(ced)
        p = crear_paciente(admin, ced, nombre=f"Lab {clave} Ficticio, Prueba", medico=MEDICO, dias="LMV")
        ids[clave] = p["id"]
        if hb is not None:
            admin.post("/api/laboratorios", json={"paciente_id": p["id"], "fecha": "2026-10-01", "tipo": "Hb", "valor": hb})
    yield ids
    for c in cedulas:
        borrar_paciente_total(c)


def test_estado_de_un_valor_con_rangos_por_defecto():
    rango = {"minimo": 10, "maximo": 12, "muy_alto": 14}
    assert [srv.estado(v, rango) for v in (9.9, 10, 12, 12.1, 14, 14.1)] == \
        ["bajo", "normal", "normal", "alto", "alto", "muy_alto"]
    assert srv.estado(None, rango) == "sin_dato"
    assert srv.estado(5, {"minimo": None, "maximo": None, "muy_alto": None}) == "sin_rango"
    assert srv.estado(1.0, {"minimo": 1.2, "maximo": None, "muy_alto": None}) == "bajo"
    assert srv.validar_rango(10, 12, 14) is None and srv.validar_rango(12, 10, None) is not None


def test_filtrar_por_estado(admin, pacientes):
    def ids(estado):
        d = admin.get(f"/api/labs/panel?tipo=Hb&estado={estado}&medico={MEDICO}").json()
        return {f["paciente_id"] for f in d["pacientes"]}
    assert ids("bajo") == {pacientes["bajo"]}
    assert ids("normal") == {pacientes["normal"]}
    assert ids("alto") == {pacientes["alto"]}
    assert ids("muy_alto") == {pacientes["muy_alto"]}
    assert ids("sin_dato") == {pacientes["sin_dato"]}
    assert ids("alto,muy_alto") == {pacientes["alto"], pacientes["muy_alto"]}
    d = admin.get(f"/api/labs/panel?tipo=Hb&medico={MEDICO}").json()
    assert d["total"] == 5 and d["conteo"] == {"bajo": 1, "normal": 1, "alto": 1, "muy_alto": 1, "sin_dato": 1}
    assert d["rango"]["minimo"] == 10 and d["rango"]["muy_alto"] == 14


def test_la_tabla_trae_valor_estado_ultima_muestra_y_medico(admin, pacientes):
    admin.post("/api/laboratorios", json={"paciente_id": pacientes["bajo"], "fecha": "2026-11-05", "tipo": "Hb", "valor": 9.5})
    d = admin.get(f"/api/labs/panel?tipo=Hb&estado=bajo&medico={MEDICO}").json()
    fila = d["pacientes"][0]
    assert (fila["valor"], fila["estado"], fila["fecha"], fila["medico"]) == (9.5, "bajo", "2026-11-05", MEDICO)
    assert fila["unidad"] == "g/dL" and fila["iniciales"] == "LBFP"


def test_panel_valida_parametros(admin):
    assert admin.get("/api/labs/panel?tipo=Zzz").status_code == 400
    assert admin.get("/api/labs/panel?tipo=Hb&estado=rarisimo").status_code == 422


def test_panel_excluye_archivados_e_inactivos(admin, pacientes):
    admin.post(f"/api/pacientes/{pacientes['bajo']}/archivar", json={"motivo": "Traslado"})
    admin.patch(f"/api/pacientes/{pacientes['alto']}/toggle-activo", json={"motivo": "otro"})
    d = admin.get(f"/api/labs/panel?tipo=Hb&medico={MEDICO}").json()
    assert {f["paciente_id"] for f in d["pacientes"]} == {pacientes["normal"], pacientes["muy_alto"], pacientes["sin_dato"]}


def test_rangos_configurables_solo_admin_y_se_restablecen(admin, demo):
    assert demo.put("/api/labs/rangos/Hb", json={"minimo": 11, "maximo": 12, "muy_alto": 13}).status_code == 403
    assert admin.put("/api/labs/rangos/Hb", json={"minimo": 12, "maximo": 10}).status_code == 422
    assert admin.put("/api/labs/rangos/Zzz", json={"minimo": 1}).status_code == 404
    try:
        r = admin.put("/api/labs/rangos/Hb", json={"minimo": 11, "maximo": 12, "muy_alto": 13}).json()
        assert r["personalizado"] is True and r["minimo"] == 11
        assert {x["tipo"]: x for x in admin.get("/api/labs/rangos").json()}["Hb"]["muy_alto"] == 13
    finally:
        r = admin.delete("/api/labs/rangos/Hb").json()
    assert (r["minimo"], r["maximo"], r["muy_alto"], r["personalizado"]) == (10, 12, 14, False)


def test_cambiar_el_rango_cambia_el_estado(admin, pacientes):
    try:
        admin.put("/api/labs/rangos/Hb", json={"minimo": 11.5, "maximo": 12, "muy_alto": 12.5})
        d = admin.get(f"/api/labs/panel?tipo=Hb&medico={MEDICO}").json()
        est = {f["paciente_id"]: f["estado"] for f in d["pacientes"]}
        assert est[pacientes["normal"]] == "bajo" and est[pacientes["alto"]] == "muy_alto"
    finally:
        admin.delete("/api/labs/rangos/Hb")


def test_comparativa_por_toma_y_por_mes(admin, pacientes):
    pid = pacientes["normal"]
    for f, v in [("2026-08-05", 9.0), ("2026-08-25", 11.0), ("2026-09-10", 12.5), ("2026-10-10", 14.5)]:
        admin.post("/api/laboratorios", json={"paciente_id": pid, "fecha": f, "tipo": "Hb", "valor": v})
    d = admin.get(f"/api/labs/comparativa/{pid}?tipo=Hb").json()
    assert [t["valor"] for t in d["tomas"]] == [9.0, 11.0, 12.5, 11.0, 14.5]     # orden por fecha
    assert [t["estado"] for t in d["tomas"]] == ["bajo", "normal", "alto", "normal", "muy_alto"]
    m = {x["mes"]: x for x in d["meses"]}
    assert m["2026-08"]["promedio"] == 10.0 and m["2026-08"]["tomas"] == 2 and m["2026-08"]["variacion"] is None
    assert m["2026-09"]["variacion"] == 2.5 and m["2026-09"]["estado"] == "alto"
    assert m["2026-10"]["promedio"] == 12.75 and m["2026-10"]["estado"] == "alto"   # 11.0 y 14.5
    assert admin.get(f"/api/labs/comparativa/{pid}?tipo=Zzz").status_code == 400
    assert admin.get("/api/labs/comparativa/999999?tipo=Hb").status_code == 404
