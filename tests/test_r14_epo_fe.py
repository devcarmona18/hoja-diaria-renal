"""R14 — programación mensual EPO / hierro: API, llenado de la hoja, inasistencias y ajustes."""
import contextlib

import models
from database import SessionLocal
from services import epo_fe as srv
from tests.helpers_w2a import borrar_mes, borrar_paciente_total, crear_paciente, marcar, registro_de

# Septiembre 2025: el 1 es lunes. Laboratorio por defecto: miércoles 10 y jueves 11.
# LMV: 1 3 5 8 (10) 12 15 17 19 22 24 26 29  ·  MJS: 2 4 6 9 (11) 13 16 18 20 23 25 27 30
MES = "2025-09"
LAB = {"2025-09-10", "2025-09-11"}


def _limpiar_mes(mes):
    with SessionLocal() as db:
        for t in (models.EpoFeCelda, models.EpoFeMovimiento, models.EpoFeMesPaciente,
                  models.EpoFeConfigMes, models.EpoFeAuditoria):
            db.query(t).filter_by(mes=mes).delete()
        db.commit()
    borrar_mes(mes)


@contextlib.contextmanager
def pacientes(cliente, *specs, mes=MES):
    creados = []
    try:
        for ced, extra in specs:
            creados.append(crear_paciente(cliente, ced, **extra))
        yield creados
    finally:
        _limpiar_mes(mes)
        for ced, _ in specs:
            borrar_paciente_total(ced)


def _grilla(c, mes=MES):
    r = c.get(f"/api/epo-fe/{mes}")
    assert r.status_code == 200, r.text
    return r.json()


def _fila(g, pid):
    return next(f for f in g["filas"] if f["paciente_id"] == pid)


def _generar(c, mes=MES, regenerar=False):
    r = c.post(f"/api/epo-fe/{mes}/generar", json={"regenerar": regenerar})
    assert r.status_code == 200, r.text
    return r.json()


def _cerrar(c, sesion_id):
    r = c.post(f"/api/cierre/{sesion_id}/cerrar")
    assert r.status_code == 200, r.text


def _con_epo(fila):
    return sorted(f for f, x in fila["celdas"].items() if x["epo"])


def _con_fe(fila):
    return sorted(f for f, x in fila["celdas"].items() if x["fe"])


LMV4 = dict(dias="LMV", epo_mensual=16000.0, hierro_mensual=4, medico="Dra. Valeria Montoya")


def test_generar_grilla_totales_iniciales_y_sin_laboratorio(admin):
    with pacientes(admin, ("T-R14-001", LMV4),
                   ("T-R14-002", dict(dias="MJS", epo_mensual=56000.0, hierro_mensual=2))) as (a, b):
        g = _grilla(admin)
        assert g["generado"] is False and g["dias_lab"] == sorted(LAB) and g["dias_lab_por_defecto"]
        assert all(d["dow"] != "D" for d in g["dias"]) and len(g["dias"]) == 26
        res = _generar(admin)
        assert res["nuevos"] >= 2
        g = _grilla(admin)
        fa, fb = _fila(g, a["id"]), _fila(g, b["id"])
        assert (fa["epo_mes"], fa["fe_mes"], fa["iniciales"]) == (4, 4, "VM")
        assert (fb["epo_mes"], fb["fe_mes"]) == (14, 2)
        assert len(fa["celdas"]) == 13 and all(_d_semana(f) in (0, 2, 4) for f in fa["celdas"])
        assert all(_d_semana(f) in (1, 3, 5) for f in fb["celdas"])
        assert _con_epo(fa) == ["2025-09-03", "2025-09-12", "2025-09-19", "2025-09-26"]
        assert sum(x["epo"] for x in fb["celdas"].values()) == 14
        assert sorted(x["epo_ui"] for x in fb["celdas"].values() if x["epo"] == 2) == [8000, 8000]
        assert len(_con_fe(fa)) == 4 and sum(1 for f in _con_fe(fa) if f < "2025-09-10") == 2   # ⌈4/2⌉
        for f in (fa, fb):
            assert not any(f["celdas"].get(d, {}).get("epo") or f["celdas"].get(d, {}).get("fe") for d in LAB)
            assert f["avisos"] == []
        # generar otra vez no duplica ni cambia nada
        _generar(admin)
        assert _fila(_grilla(admin), a["id"])["celdas"] == fa["celdas"]


def _d_semana(f):
    from datetime import date
    return date.fromisoformat(f).weekday()


def test_demo_lee_pero_no_cambia(admin, demo):
    with pacientes(admin, ("T-R14-003", LMV4)) as (a,):
        _generar(admin)
        assert demo.get(f"/api/epo-fe/{MES}").status_code == 200
        assert demo.post(f"/api/epo-fe/{MES}/generar", json={}).status_code == 403
        assert demo.post(f"/api/epo-fe/{MES}/recalcular").status_code == 403
        assert demo.put(f"/api/epo-fe/{MES}/pacientes/{a['id']}", json={"epo_jeringas": 1}).status_code == 403
        assert demo.delete(f"/api/epo-fe/{MES}").status_code == 403


def test_cambiar_totales_reparte_de_nuevo(admin):
    with pacientes(admin, ("T-R14-004", LMV4)) as (a,):
        _generar(admin)
        r = admin.put(f"/api/epo-fe/{MES}/pacientes/{a['id']}", json={"epo_jeringas": 14, "fe_dosis": 1})
        assert r.status_code == 200, r.text
        f = _fila(_grilla(admin), a["id"])
        assert f["epo_programada"] == 14 and f["fe_programado"] == 1
        assert sum(1 for x in f["celdas"].values() if x["epo"] == 2) == 2
        assert _con_fe(f)[0] < "2025-09-10"


def test_ajuste_manual_persiste_al_recalcular_y_regenerar_lo_quita(admin):
    with pacientes(admin, ("T-R14-005", LMV4)) as (a,):
        _generar(admin)
        r = admin.put(f"/api/epo-fe/{MES}/celdas", json={"paciente_id": a["id"], "fecha": "2025-09-01", "epo": 2})
        assert r.status_code == 200, r.text
        f = _fila(_grilla(admin), a["id"])
        c = f["celdas"]["2025-09-01"]
        assert c["manual"] and c["epo"] == 2 and f["epo_programada"] == 4    # el resto se ajusta al total
        assert admin.post(f"/api/epo-fe/{MES}/recalcular").status_code == 200
        admin.put(f"/api/epo-fe/{MES}/pacientes/{a['id']}", json={"fe_dosis": 3})
        c = _fila(_grilla(admin), a["id"])["celdas"]["2025-09-01"]
        assert c["manual"] and c["epo"] == 2
        _generar(admin, regenerar=True)
        f = _fila(_grilla(admin), a["id"])
        assert not f["celdas"]["2025-09-01"]["manual"] and f["celdas"]["2025-09-01"]["epo"] == 0
        assert f["epo_programada"] == 4 and f["fe_programado"] == 3
        acciones = {x["accion"] for x in _grilla(admin)["auditoria"]}
        assert {"generar", "celda", "totales", "regenerar"} <= acciones


def test_ajuste_invalido(admin):
    with pacientes(admin, ("T-R14-006", LMV4)) as (a,):
        _generar(admin)
        r = admin.put(f"/api/epo-fe/{MES}/celdas", json={"paciente_id": a["id"], "fecha": "2025-09-02", "epo": 1})
        assert r.status_code == 422                                   # martes: no le toca
        r = admin.put(f"/api/epo-fe/{MES}/celdas", json={"paciente_id": a["id"], "fecha": "2025-10-01", "epo": 1})
        assert r.status_code == 422


def test_la_hoja_se_llena_sola_y_el_personal_puede_cambiarla(admin):
    with pacientes(admin, ("T-R14-007", LMV4)) as (a,):
        _generar(admin)
        f = _fila(_grilla(admin), a["id"])
        fecha_epo = _con_epo(f)[0]
        fecha_fe = _con_fe(f)[0]
        _, reg = registro_de(admin, fecha_epo, "N", a["id"])
        assert reg["epo"] is True and reg["epo_jeringas"] == 1
        _, reg = registro_de(admin, fecha_fe, "N", a["id"])
        assert reg["hierro"] is True
        _, reg = registro_de(admin, "2025-09-01", "N", a["id"])
        assert (reg["epo"], reg["epo_jeringas"]) == (False, 0)
        # el personal cambia la fila: la programación no la vuelve a pisar
        _, reg = marcar(admin, "2025-09-01", "N", a["id"], epo_jeringas=2)
        assert reg["epo"] is True and reg["epo_fe_manual"] is True
        admin.post(f"/api/epo-fe/{MES}/recalcular")
        _, reg = registro_de(admin, "2025-09-01", "N", a["id"])
        assert reg["epo_jeringas"] == 2
        # un cambio de la programación llega a la hoja ABIERTA de un día no editado a mano
        admin.put(f"/api/epo-fe/{MES}/celdas", json={"paciente_id": a["id"], "fecha": fecha_epo, "epo": 2})
        _, reg = registro_de(admin, fecha_epo, "N", a["id"])
        assert reg["epo_jeringas"] == 2
        # la programación de «Programar próxima» muestra lo del mes
        h = admin.get(f"/api/asignaciones/hoja/{fecha_epo}/N").json()
        pu = next(x for x in h["puestos"] if x["paciente"]["id"] == a["id"])
        assert pu["epo"] is True and pu["epo_jeringas"] == 2 and pu["epo_fe_mes"] is True


def test_inasistencia_pasa_la_epo_a_la_siguiente_sesion_8000_ui(admin):
    with pacientes(admin, ("T-R14-008", dict(LMV4, epo_mensual=52000.0))) as (a,):   # 13 jeringas: 1 por sesión
        _generar(admin)
        f = _fila(_grilla(admin), a["id"])
        assert f["celdas"]["2025-09-03"]["epo"] == 1 and f["celdas"]["2025-09-05"]["epo"] == 1
        ses, _ = marcar(admin, "2025-09-03", "N", a["id"], asistencia="NA")
        _cerrar(admin, ses["id"])
        f = _fila(_grilla(admin), a["id"])
        assert f["celdas"]["2025-09-03"]["epo"] == 0 and f["celdas"]["2025-09-03"]["estado"] == "falto"
        assert f["celdas"]["2025-09-03"]["sale"] == [{"tipo": "epo", "cantidad": 1, "hacia": "2025-09-05"}] \
            or {"tipo": "epo", "cantidad": 1, "hacia": "2025-09-05"} in f["celdas"]["2025-09-03"]["sale"]
        c5 = f["celdas"]["2025-09-05"]
        assert c5["epo"] == 2 and c5["epo_ui"] == 8000 and c5["llega"][0]["desde"] == "2025-09-03"
        _, reg = registro_de(admin, "2025-09-05", "N", a["id"])
        assert reg["epo_jeringas"] == 2                                 # la hoja del viernes ya lo trae
        assert any(x["accion"] == "reprogramar" for x in _grilla(admin)["auditoria"])
        # recalcular es idempotente
        admin.post(f"/api/epo-fe/{MES}/recalcular")
        assert _fila(_grilla(admin), a["id"])["celdas"]["2025-09-05"]["epo"] == 2
        # falta también el viernes: se acumula (1 + 2 = 3) el lunes 8
        ses5, _ = marcar(admin, "2025-09-05", "N", a["id"], asistencia="NA")
        _cerrar(admin, ses5["id"])
        f = _fila(_grilla(admin), a["id"])
        assert f["celdas"]["2025-09-08"]["epo"] == 3 and any("jeringas" in x for x in f["avisos"])


def test_vino_con_peso_de_entrada_no_se_reprograma_y_corregir_asistencia_revierte(admin):
    with pacientes(admin, ("T-R14-009", dict(LMV4, epo_mensual=52000.0))) as (a,):
        _generar(admin)
        ses, _ = marcar(admin, "2025-09-01", "N", a["id"], peso_entrada=72.0)   # sin «A» pero con peso: vino
        _cerrar(admin, ses["id"])
        f = _fila(_grilla(admin), a["id"])
        assert f["celdas"]["2025-09-01"]["estado"] == "asistio" and f["celdas"]["2025-09-03"]["epo"] == 1
        ses3, _ = marcar(admin, "2025-09-03", "N", a["id"], asistencia="NA")
        _cerrar(admin, ses3["id"])
        assert _fila(_grilla(admin), a["id"])["celdas"]["2025-09-05"]["epo"] == 2
        assert admin.post(f"/api/cierre/{ses3['id']}/reabrir").status_code == 200
        f = _fila(_grilla(admin), a["id"])
        assert f["celdas"]["2025-09-05"]["epo"] == 1 and f["celdas"]["2025-09-03"]["epo"] == 1
        marcar(admin, "2025-09-03", "N", a["id"], asistencia="A")
        _cerrar(admin, ses3["id"])
        assert _fila(_grilla(admin), a["id"])["celdas"]["2025-09-05"]["epo"] == 1
        assert any(x["accion"] == "revertir" for x in _grilla(admin)["auditoria"])


def test_inasistencia_pasa_el_hierro_a_una_sesion_sin_hierro_que_no_sea_laboratorio(admin):
    with pacientes(admin, ("T-R14-010", dict(LMV4, epo_mensual=None, hierro_mensual=4))) as (a,):
        _generar(admin)
        f = _fila(_grilla(admin), a["id"])
        primera = _con_fe(f)[0]
        ses, _ = marcar(admin, primera, "N", a["id"], asistencia="NA")
        _cerrar(admin, ses["id"])
        f = _fila(_grilla(admin), a["id"])
        sale = f["celdas"][primera]["sale"]
        assert len(sale) == 1 and sale[0]["tipo"] == "fe"
        destino = sale[0]["hacia"]
        assert destino > primera and destino not in LAB
        assert f["celdas"][destino]["fe"] == 1 and f["celdas"][destino]["fe_plan"] == 0
        assert len(_con_fe(f)) == 4                                     # sigue habiendo 4 dosis en el mes
        assert all(x["fe"] <= 1 for x in f["celdas"].values())


def test_hierro_sin_sesion_libre_queda_pendiente(admin):
    with pacientes(admin, ("T-R14-011", dict(LMV4, epo_mensual=None, hierro_mensual=13))) as (a,):
        _generar(admin)
        f = _fila(_grilla(admin), a["id"])
        assert len(_con_fe(f)) == 13 and any("laboratorio" in x for x in f["avisos"])
        ses, _ = marcar(admin, "2025-09-29", "N", a["id"], asistencia="NA")   # última sesión del mes
        _cerrar(admin, ses["id"])
        f = _fila(_grilla(admin), a["id"])
        assert any("Pendiente sin sesión" in x for x in f["avisos"])


def test_paciente_sin_fila_en_su_hoja_cerrada_cuenta_como_falta(admin):
    with pacientes(admin, ("T-R14-012", dict(LMV4, epo_mensual=52000.0))) as (a,):
        _generar(admin)
        ses, reg = registro_de(admin, "2025-09-01", "N", a["id"])
        with SessionLocal() as db:
            db.delete(db.get(models.Registro, reg["id"]))
            db.commit()
        _cerrar(admin, ses["id"])
        f = _fila(_grilla(admin), a["id"])
        assert f["celdas"]["2025-09-01"]["estado"] == "falto" and f["celdas"]["2025-09-03"]["epo"] == 2


def test_periodo_inactivo_no_se_programa_ni_se_reprograma(admin):
    with pacientes(admin, ("T-R14-013", dict(LMV4, epo_mensual=52000.0))) as (a,):
        with SessionLocal() as db:
            db.add(models.PacienteInactividad(paciente_id=a["id"], desde="2025-09-15", hasta="2025-09-22",
                                              origen="inactivo"))
            db.commit()
        _generar(admin)
        f = _fila(_grilla(admin), a["id"])
        assert not {"2025-09-15", "2025-09-17", "2025-09-19"} & set(f["celdas"])
        assert len(f["celdas"]) == 10 and f["epo_programada"] == 13
        assert max(x["epo"] for x in f["celdas"].values()) == 2


def test_inactivos_y_archivados_no_entran_al_generar(admin):
    with pacientes(admin, ("T-R14-014", dict(LMV4, activo=False, motivo_inactivo="hospitalizado")),
                   ("T-R14-015", LMV4)) as (a, b):
        admin.post(f"/api/pacientes/{b['id']}/archivar", json={"motivo": "Prueba ficticia"})
        _generar(admin)
        ids = {f["paciente_id"] for f in _grilla(admin)["filas"]}
        assert a["id"] not in ids and b["id"] not in ids


def test_dias_de_laboratorio_configurables_por_mes(admin):
    with pacientes(admin, ("T-R14-016", dict(LMV4, hierro_mensual=4))) as (a,):
        _generar(admin)
        r = admin.put(f"/api/epo-fe/{MES}/laboratorio", json={"fechas": ["2025-09-17", "2025-09-18"]})
        assert r.status_code == 200, r.text
        g = _grilla(admin)
        assert g["dias_lab"] == ["2025-09-17", "2025-09-18"] and not g["dias_lab_por_defecto"]
        f = _fila(g, a["id"])
        assert "2025-09-17" not in _con_fe(f) and "2025-09-17" not in _con_epo(f)
        assert sum(1 for x in _con_fe(f) if x < "2025-09-17") >= 2                        # ⌈4/2⌉
        assert admin.put(f"/api/epo-fe/{MES}/laboratorio", json={"fechas": ["2025-09-07"]}).status_code == 422
        admin.put(f"/api/epo-fe/{MES}/laboratorio", json={"fechas": None})
        assert _grilla(admin)["dias_lab"] == sorted(LAB)


def test_csv_y_borrado_del_mes(admin):
    with pacientes(admin, ("T-R14-017", LMV4)) as (a,):
        _generar(admin)
        r = admin.get(f"/api/epo-fe/{MES}/csv")
        assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
        texto = r.content.decode("utf-8-sig")
        assert "EPO del mes (jeringas)" in texto and "X 10 LAB" in texto and "4.000" in texto
        assert admin.delete(f"/api/epo-fe/{MES}").status_code == 200            # mes ya terminado
        assert _grilla(admin)["generado"] is False
        assert any(x["accion"] == "borrar" for x in _grilla(admin)["auditoria"])


def test_no_se_borra_el_mes_en_curso(admin):
    from services.tiempo import hoy_local
    mes = hoy_local().strftime("%Y-%m")
    assert admin.delete(f"/api/epo-fe/{mes}").status_code == 409


def test_mes_invalido(admin):
    assert admin.get("/api/epo-fe/2025-13").status_code == 422


def test_cierre_cuenta_jeringas(admin):
    with pacientes(admin, ("T-R14-018", dict(LMV4, epo_mensual=56000.0))) as (a,):   # 14: hay sesiones con 2
        _generar(admin)
        f = _fila(_grilla(admin), a["id"])
        doble = next(d for d, x in f["celdas"].items() if x["epo"] == 2)
        ses, _ = marcar(admin, doble, "N", a["id"], asistencia="A")
        tot = admin.get(f"/api/cierre/{ses['id']}").json()["totales"]
        assert tot["epo_jeringas"] >= 2
        h = admin.get(f"/api/historial/hoja?fecha={doble}&turno=N").json()
        fila = next(x for x in h["filas"] if x["paciente_id"] == a["id"])
        assert fila["epo_jeringas"] == 2 and h["resumen"]["epo_ui"] >= 8000


def test_valores_dia_sin_programacion_usa_la_programacion_del_dia(admin):
    with SessionLocal() as db:
        assert srv.valores_dia(db, "2019-01-02") == {}


# ── R12 + R14: mes cerrado = programación EPO / hierro de solo lectura ───────

MES_CERRADO = "2025-08"     # el 4 es lunes; LMV: 1 4 6 8 11 …
MSG_CERRADO = "El mes está cerrado; reábralo para editar"


def _es_409(r):
    assert r.status_code == 409, (r.status_code, r.text)
    assert r.json()["detail"] == MSG_CERRADO


def test_mes_cerrado_bloquea_la_programacion_y_el_recalculo(admin):
    with pacientes(admin, ("T-R14-030", LMV4), mes=MES_CERRADO) as (a,):
        _generar(admin, MES_CERRADO)
        f = _fila(_grilla(admin, MES_CERRADO), a["id"])
        dia = _con_epo(f)[0]
        ses, _ = marcar(admin, dia, "N", a["id"], asistencia="NA")
        _cerrar(admin, ses["id"])                 # mes abierto: se reprograma
        antes = _grilla(admin, MES_CERRADO)
        assert antes["mes_cerrado"] is False and _fila(antes, a["id"])["celdas"][dia]["estado"] == "falto"
        assert admin.post("/api/estadisticas/asistencia/2025/08/cerrar").status_code == 200
        try:
            g = _grilla(admin, MES_CERRADO)
            assert g["mes_cerrado"] is True
            _es_409(admin.post(f"/api/epo-fe/{MES_CERRADO}/generar", json={"regenerar": False}))
            _es_409(admin.post(f"/api/epo-fe/{MES_CERRADO}/generar", json={"regenerar": True}))
            _es_409(admin.post(f"/api/epo-fe/{MES_CERRADO}/recalcular", json={}))
            _es_409(admin.put(f"/api/epo-fe/{MES_CERRADO}/pacientes/{a['id']}", json={"epo_jeringas": 8}))
            otro = next(x for x in _con_epo(f) if x > dia and x not in LAB)
            _es_409(admin.put(f"/api/epo-fe/{MES_CERRADO}/celdas",
                              json={"paciente_id": a["id"], "fecha": otro, "epo": 3}))
            _es_409(admin.put(f"/api/epo-fe/{MES_CERRADO}/laboratorio", json={"fechas": []}))
            _es_409(admin.delete(f"/api/epo-fe/{MES_CERRADO}"))
            # el gancho del cierre de un día no toca las celdas de un mes cerrado
            with SessionLocal() as db:
                n_mov = db.query(models.EpoFeMovimiento).filter_by(mes=MES_CERRADO).count()
                db.query(models.EpoFeMovimiento).filter_by(mes=MES_CERRADO).update({"activo": False})
                srv.tras_cierre(db, dia, "prueba")
                db.flush()
                assert db.query(models.EpoFeMovimiento).filter_by(mes=MES_CERRADO, activo=True).count() == 0
                assert db.query(models.EpoFeMovimiento).filter_by(mes=MES_CERRADO).count() == n_mov
                assert srv.sincronizar_hojas(db, MES_CERRADO) == 0
                db.rollback()
            g2 = _grilla(admin, MES_CERRADO)
            assert _fila(g2, a["id"])["celdas"] == _fila(antes, a["id"])["celdas"]
            assert g2["auditoria"] == antes["auditoria"]
        finally:
            r = admin.post("/api/estadisticas/asistencia/2025/08/reabrir", json={"motivo": "Prueba ficticia"})
            assert r.status_code == 200, r.text
        assert admin.post(f"/api/epo-fe/{MES_CERRADO}/recalcular", json={}).status_code == 200


def test_vino_y_falto_es_la_misma_regla_que_insumos():
    import hoja_dia as hd
    from services import insumos
    casos = [("A", None), ("A", 70.0), (None, 70.0), ("NA", None), ("H", None), ("F", None), (None, None)]
    for asis, peso in casos:
        llego = hd.llego(asis, peso)
        assert llego == (asis == "A" or peso is not None)
        assert insumos.Asistencia(None, None, None, asis, peso).llego == llego
        # con la hoja cerrada «no vino» = «faltó» (devolución de insumos y reprogramación R14)
        assert hd.falto(asis, peso, hoja_cerrada=True) == (not llego)
    assert hd.falto(None, None, hoja_cerrada=False) is False      # aún sin marcar en hoja abierta
    assert hd.falto("NA", None, hoja_cerrada=False) is True
