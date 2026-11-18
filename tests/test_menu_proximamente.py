"""R8 — «Próximamente»: burbuja solo en inicio y sección del menú en la última posición."""
import re


def _app_js(c):
    return c.get("/static/js/app.js").text


def test_menu_proximamente_es_la_ultima_seccion(anonimo):
    js = _app_js(anonimo)
    bloque = js[js.index("const MENU_INICIO = ["):]
    bloque = bloque[:bloque.index("\n]\n")]
    ids = re.findall(r'\{ id: "([a-z]+)"', bloque)
    assert ids[-1] == "proximamente"
    assert ids.count("proximamente") == 1
    assert {"historial", "epo"} <= set(ids)        # convive con Historial y EPO
    assert "renderProximamente()" in bloque


def test_seccion_y_burbuja_comparten_contenido(anonimo):
    js = anonimo.get("/static/js/hl7.js").text
    assert "function renderProximamente()" in js
    assert js.count("_hl7CuerpoHTML(") >= 3          # definición + modal + sección
    assert 'G.vista === "dashboard"' in js            # burbuja solo en inicio
    assert "cont.hidden = !enInicio" in js
    # el flag HL7 no cambia: la bandeja sigue condicionada a habilitado
    assert "_hl7Estado.habilitado === true" in js


def test_hl7_estado_apagado_por_defecto(admin):
    r = admin.get("/api/hl7/estado")
    assert r.status_code == 200 and r.json()["habilitado"] is False
