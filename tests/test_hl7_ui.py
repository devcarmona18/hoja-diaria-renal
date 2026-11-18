"""Interfaz «Próximamente»: presente para todos y sin bandeja mientras HL7 esté apagado."""


def test_ui_proximamente_presente(anonimo):
    html = anonimo.get("/static/index.html").text
    assert '/static/js/hl7.js' in html and '/static/css/hl7.css' in html
    js = anonimo.get("/static/js/hl7.js").text
    assert "Próximamente" in js and "/api/hl7/estado" in js
    assert "/static/media/hl7-proximamente.mp4" in js and "/static/media/hl7-proximamente.jpg" in js
    assert "Disponible próximamente. Requiere autorización de la unidad" in js
    assert "habilitado" in js  # la bandeja solo se monta si el backend la habilita
