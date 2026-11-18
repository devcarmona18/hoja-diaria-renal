"""R5/R6 — motor de reglas del pedido de insumos (funciones puras, sin BD)."""
from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from services import insumos_reglas as ir

R = ir.cargar_por_defecto()
LUNES = date(2027, 3, 1)
assert LUNES.weekday() == 0
DIAS = {n: LUNES + timedelta(days=i) for i, n in enumerate(ir.DIAS[:6])}   # lunes … sábado


def cant(res: ir.Resultado) -> dict:
    return {li.codigo: li.cantidad for li in res.lineas}


def fav(calibre=16, filtro="B-18", **kw):
    return ir.DatosPaciente(acceso="FAV", calibre=calibre, filtro=filtro, estado_fav="limpia", **kw)


def cy(citrato=False, heparina=False, filtro="R-300", sitio="yugular"):
    return ir.DatosPaciente(acceso="CY", filtro=filtro, citrato=citrato, heparina_sodica=heparina, sitio=sitio)


# ── FAV ───────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("calibre", [15, 16, 17])
def test_fav_lleva_agujas_de_su_calibre(calibre):
    res = ir.calcular(fav(calibre), LUNES, R)
    assert cant(res) == {"kit_fistula": 1, f"aguja_fav_{calibre}": 2, "linea": 1,
                         "ssn_1000": 1, "filtro_B-18": 1}
    assert res.alertas == []
    aguja = next(li for li in res.lineas if li.codigo.startswith("aguja"))
    assert aguja.nombre == f"Aguja de fístula calibre {calibre}"


@pytest.mark.parametrize("dia", list(DIAS))
def test_fav_nunca_lleva_guantes_ni_material_de_cateter(dia):
    c = cant(ir.calcular(fav(citrato=True, heparina_sodica=True), DIAS[dia], R))
    assert not {"guantes_esteriles_6_5", "aposito_iv3000", "tego", "tapas_luer_lock", "kit_cateter"} & set(c)


def test_fav_sin_calibre_avisa_y_no_adivina():
    res = ir.calcular(fav(calibre=None), LUNES, R)
    assert "Calibre faltante" in res.alertas
    assert not any(c.startswith("aguja") for c in cant(res))
    assert cant(res) == {"kit_fistula": 1, "linea": 1, "ssn_1000": 1, "filtro_B-18": 1}


@pytest.mark.parametrize("filtro", [None, "", "   "])
def test_sin_filtro_avisa(filtro):
    res = ir.calcular(fav(filtro=filtro), LUNES, R)
    assert "Filtro faltante" in res.alertas
    assert not any(c.startswith("filtro") for c in cant(res))


def test_el_filtro_es_el_del_paciente():
    res = ir.calcular(cy(filtro="FX80"), LUNES, R)
    li = next(x for x in res.lineas if x.codigo.startswith("filtro"))
    assert (li.codigo, li.nombre, li.cantidad) == ("filtro_FX80", "Filtro FX80", 1)


def test_sin_acceso_solo_avisa():
    res = ir.calcular(ir.DatosPaciente(acceso=None, filtro="B-18"), LUNES, R)
    assert res.lineas == [] and res.alertas == [ir.AVISO_SIN_ACCESO]


# ── CY ────────────────────────────────────────────────────────────────────────

BASE_CY = {"kit_cateter": 1, "linea": 1, "ssn_1000": 1, "filtro_R-300": 1}


@pytest.mark.parametrize("dia", ["lunes", "martes"])
def test_cy_lunes_martes_sin_citrato_ni_heparina(dia):
    assert cant(ir.calcular(cy(), DIAS[dia], R)) == {
        **BASE_CY, "guantes_esteriles_6_5": 1, "aposito_iv3000": 1, "tego": 2}


@pytest.mark.parametrize("dia", ["miércoles", "jueves", "viernes", "sábado"])
def test_cy_otros_dias_sin_citrato_ni_heparina(dia):
    assert cant(ir.calcular(cy(), DIAS[dia], R)) == {**BASE_CY, "tego": 2}


@pytest.mark.parametrize("citrato,heparina", [(True, False), (False, True), (True, True)])
@pytest.mark.parametrize("dia", list(DIAS))
def test_cy_con_citrato_o_heparina_sodica(dia, citrato, heparina):
    c = cant(ir.calcular(cy(citrato, heparina), DIAS[dia], R))
    esperado = {**BASE_CY, "guantes_esteriles_6_5": 2, "tapas_luer_lock": 1}
    if dia in ("lunes", "martes"):
        esperado["aposito_iv3000"] = 1
    assert c == esperado
    assert "tego" not in c


def test_tapas_luer_lock_es_un_empaque_de_dos():
    li = next(x for x in ir.calcular(cy(citrato=True), LUNES, R).lineas if x.codigo == "tapas_luer_lock")
    assert (li.cantidad, li.unidad, li.detalle) == (1, "empaque", "1 empaque (2 tapas)")


@pytest.mark.parametrize("sitio", ["yugular", "femoral"])
def test_cy_yugular_y_femoral_iguales(sitio):
    assert cant(ir.calcular(cy(sitio=sitio), LUNES, R)) == cant(ir.calcular(cy(), LUNES, R))


def test_cy_no_lleva_agujas_ni_calibre_faltante():
    res = ir.calcular(cy(), LUNES, R)
    assert res.alertas == [] and not any(c.startswith("aguja") for c in cant(res))


# ── Reglas como datos ─────────────────────────────────────────────────────────

def test_reglas_por_defecto_validas_y_redondas():
    d = R.model_dump(exclude_none=True)
    assert ir.validar(d).model_dump(exclude_none=True) == d


def _con(**cambios):
    d = R.model_dump(exclude_none=True)
    d.update(cambios)
    return d


def test_regla_con_insumo_fuera_del_catalogo_es_invalida():
    with pytest.raises(ValidationError, match="no está en el catálogo"):
        ir.validar(_con(reglas=[{"insumo": "no_existe", "cantidad": 1}]))


def test_dia_invalido_y_marcador_desconocido():
    with pytest.raises(ValidationError, match="día inválido"):
        ir.validar(_con(reglas=[{"insumo": "linea", "si": {"dia_semana": ["lunez"]}, "cantidad": 1}]))
    with pytest.raises(ValidationError, match="marcador desconocido"):
        ir.validar(_con(insumos={"x_{talla}": {"nombre": "X"}}, reglas=[]))
    with pytest.raises(ValidationError):
        ir.validar(_con(reglas=[{"insumo": "linea", "si": {"color": "rojo"}, "cantidad": 1}]))
    with pytest.raises(ValidationError):
        ir.validar(_con(reglas=[{"insumo": "linea", "cantidad": -1}]))


def test_dias_sin_tilde_se_aceptan():
    r = ir.validar(_con(reglas=[{"insumo": "linea", "si": {"dia_semana": ["miercoles", "Sabado"]}, "cantidad": 1}]))
    assert r.reglas[0].si.dia_semana == ["miércoles", "sábado"]
    assert cant(ir.calcular(fav(), DIAS["miércoles"], r)) == {"linea": 1}
    assert cant(ir.calcular(fav(), DIAS["jueves"], r)) == {}


def test_reglas_repetidas_suman_y_casos_por_turno():
    r = ir.validar(_con(reglas=[
        {"insumo": "linea", "cantidad": 1},
        {"insumo": "linea", "si": {"turno": ["N"]}, "cantidad": [{"si": {"acceso": ["CY"]}, "cantidad": 3},
                                                                 {"cantidad": 1}]},
    ]))
    assert cant(ir.calcular(ir.DatosPaciente("CY", turno="N"), LUNES, r)) == {"linea": 4}
    assert cant(ir.calcular(ir.DatosPaciente("FAV", 16, turno="N"), LUNES, r)) == {"linea": 2}
    assert cant(ir.calcular(ir.DatosPaciente("FAV", 16, turno="M"), LUNES, r)) == {"linea": 1}


def test_sumar_totales():
    a = ir.calcular(fav(16), LUNES, R).lineas
    b = ir.calcular(fav(17), LUNES, R).lineas
    c = ir.calcular(cy(), LUNES, R).lineas
    tot = {li.codigo: li.cantidad for li in ir.sumar([a, b, c])}
    assert tot["linea"] == 3 and tot["ssn_1000"] == 3
    assert tot["aguja_fav_16"] == 2 and tot["aguja_fav_17"] == 2
    assert tot["kit_fistula"] == 2 and tot["kit_cateter"] == 1
    # sumar no altera las líneas originales
    assert next(x for x in a if x.codigo == "linea").cantidad == 1
