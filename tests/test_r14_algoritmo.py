"""R14 — algoritmo puro del reparto mensual de EPO (jeringas 4.000 UI) y hierro."""
import random
from datetime import date

import pytest

from services.epo_fe_algoritmo import (
    PacienteFe, bloques, cuantas_antes, dias_lab_por_defecto, posiciones_uniformes,
    repartir_epo, repartir_fe, sesiones_del_mes,
)

LMV, MJS = (0, 2, 4), (1, 3, 5)


def _gaps(idx):
    return [b - a for a, b in zip(idx, idx[1:])]


def _indices(sesiones, fechas):
    pos = {s: i for i, s in enumerate(sesiones)}
    return sorted(pos[f] for f in fechas)


# ── Calendario ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("anio", [2025, 2026, 2027, 2028])
def test_dias_lab_segundo_miercoles_y_jueves_siguiente_todos_los_meses(anio):
    for mes in range(1, 13):
        x, j = dias_lab_por_defecto(anio, mes)
        assert x.weekday() == 2 and 8 <= x.day <= 14          # miércoles de la «segunda semana» (8-14)
        assert j.weekday() == 3 and (j - x).days == 1          # jueves de esa misma semana


def test_dias_lab_ejemplos():
    assert dias_lab_por_defecto(2026, 12) == [date(2026, 12, 9), date(2026, 12, 10)]   # 1-dic martes
    assert dias_lab_por_defecto(2026, 10) == [date(2026, 10, 14), date(2026, 10, 15)]  # 1-oct jueves
    assert dias_lab_por_defecto(2025, 9) == [date(2025, 9, 10), date(2025, 9, 11)]     # 1-sep lunes


def test_sesiones_sin_domingos_y_con_periodo_inactivo():
    feb = sesiones_del_mes(2026, 2, LMV)                       # febrero 2026 empieza en domingo
    assert len(feb) == 12 and all(d.weekday() in LMV for d in feb)
    assert sesiones_del_mes(2026, 2, (0, 6)) == [d for d in feb if d.weekday() == 0]   # domingo nunca
    fuera = [date(2026, 2, d) for d in range(9, 16)]
    con = sesiones_del_mes(2026, 2, LMV, excluir=fuera)
    assert len(con) == 9 and not set(con) & set(fuera)
    assert len(sesiones_del_mes(2024, 2, MJS)) == 13           # febrero bisiesto


# ── Espaciado uniforme ────────────────────────────────────────────────────────

def test_posiciones_uniformes_ejemplo_del_requerimiento():
    assert posiciones_uniformes(13, 4) == [1, 4, 8, 11]        # 4 EPO en 13 sesiones: ~cada 3
    assert posiciones_uniformes(13, 1) == [6]
    assert posiciones_uniformes(5, 9) == [0, 1, 2, 3, 4]
    assert posiciones_uniformes(0, 3) == [] and posiciones_uniformes(4, 0) == []


@pytest.mark.parametrize("m", range(1, 28))
def test_posiciones_uniformes_saltos_parejos(m):
    for k in range(1, m + 1):
        p = posiciones_uniformes(m, k)
        assert len(set(p)) == k and all(0 <= i < m for i in p)
        g = _gaps(p)
        if g:
            assert max(g) - min(g) <= 1                        # nunca amontonadas
        assert p[0] <= m - 1 - p[-1] + 1 and m - 1 - p[-1] <= p[0] + 1   # centradas


def test_bloques_cubren_todo_sin_vacios():
    for m in range(1, 20):
        for k in range(1, m + 1):
            b = bloques(m, k)
            assert b[0][0] == 0 and b[-1][1] == m
            assert all(hi > lo for lo, hi in b) and all(b[i][1] == b[i + 1][0] for i in range(k - 1))


# ── EPO ───────────────────────────────────────────────────────────────────────

def test_epo_4_jeringas_en_13_sesiones_cada_tres_y_sin_laboratorio():
    ses = sesiones_del_mes(2025, 9, LMV)                       # 13 sesiones; lab miércoles 10
    lab = dias_lab_por_defecto(2025, 9)
    assert len(ses) == 13
    plan = repartir_epo(ses, 4, lab)
    assert sum(plan.values()) == 4 and set(plan.values()) == {1}
    assert date(2025, 9, 10) not in plan
    normales = [s for s in ses if s not in lab]
    assert _gaps(_indices(normales, plan)) == [3, 3, 3]


def test_epo_14_jeringas_en_13_sesiones_lleva_dobles_repartidas():
    ses = sesiones_del_mes(2025, 9, LMV)
    plan = repartir_epo(ses, 14)                               # sin días de laboratorio: 13 sesiones
    assert sum(plan.values()) == 14 and len(plan) == 13
    assert sorted(plan.values()).count(2) == 1
    lab = dias_lab_por_defecto(2025, 9)
    plan = repartir_epo(ses, 14, lab)                          # con laboratorio: 12 normales → 2 dobles
    assert sum(plan.values()) == 14 and date(2025, 9, 10) not in plan
    dobles = [s for s, v in plan.items() if v == 2]
    assert len(dobles) == 2
    normales = [s for s in ses if s not in lab]
    i, j = _indices(normales, dobles)
    assert j - i == 6                                          # separadas medio mes


def test_epo_inevitable_usa_dias_de_laboratorio():
    ses = sesiones_del_mes(2025, 9, LMV)
    lab = dias_lab_por_defecto(2025, 9)
    plan = repartir_epo(ses, 25, lab)                          # 12 normales × 2 = 24 < 25
    assert sum(plan.values()) == 25 and plan[date(2025, 9, 10)] == 1
    assert max(plan.values()) == 2
    plan = repartir_epo(ses, 30, lab)                          # > 2 por sesión: parejo en todas
    assert sum(plan.values()) == 30 and max(plan.values()) - min(plan.values()) <= 1


def test_epo_casos_limite():
    assert repartir_epo([], 5) == {} and repartir_epo(sesiones_del_mes(2025, 9, LMV), 0) == {}
    solo_lab = [date(2025, 9, 10)]
    assert repartir_epo(solo_lab, 1, solo_lab) == {date(2025, 9, 10): 1}


@pytest.mark.parametrize("anio,mes", [(a, m) for a in (2026, 2027) for m in range(1, 13)])
@pytest.mark.parametrize("grupo", [LMV, MJS])
def test_epo_total_exacto_y_sin_laboratorio_cuando_cabe(anio, mes, grupo):
    ses = sesiones_del_mes(anio, mes, grupo)
    lab = dias_lab_por_defecto(anio, mes)
    normales = [s for s in ses if s not in lab]
    for e in range(0, 2 * len(normales) + 1):
        plan = repartir_epo(ses, e, lab)
        assert sum(plan.values()) == e
        assert not set(plan) & set(lab)
        assert all(v in (1, 2) for v in plan.values())
        if e <= len(normales):
            assert all(v == 1 for v in plan.values())
            g = _gaps(_indices(normales, plan))
            assert not g or max(g) - min(g) <= 1


# ── Hierro ────────────────────────────────────────────────────────────────────

def test_cuantas_antes_mayoria():
    assert cuantas_antes(4, 0, 4, 4, 8) == (3, 1)
    assert cuantas_antes(1, 0, 1, 4, 8) == (1, 0)
    assert cuantas_antes(2, 0, 2, 4, 8) == (2, 0)
    assert cuantas_antes(5, 0, 5, 2, 8) == (2, 3)              # antes solo hay 2 sesiones
    assert cuantas_antes(10, 0, 10, 4, 5) == (4, 5)            # después no caben: se adelantan
    assert cuantas_antes(4, 2, 2, 4, 8) == (1, 1)              # ya hay 2 fijas antes


def test_fe_mayoria_antes_del_laboratorio_y_nunca_en_laboratorio():
    ses = sesiones_del_mes(2025, 9, LMV)
    lab = dias_lab_por_defecto(2025, 9)
    r = repartir_fe([PacienteFe(1, ses, 4)], lab)
    fe = r.asignado[1]
    assert len(fe) == 4 and not fe & set(lab)
    assert sum(1 for d in fe if d < lab[0]) == 3               # ⌊4/2⌋+1 antes del miércoles 10
    assert r.sin_cupo == {} and r.en_lab == {}


def test_fe_dosis_espaciadas_un_bloque_cada_una():
    ses = sesiones_del_mes(2025, 9, MJS)
    r = repartir_fe([PacienteFe(1, ses, 4)], [])               # sin laboratorio: 4 en 13
    idx = _indices(ses, r.asignado[1])
    assert min(_gaps(idx)) >= 2 and max(_gaps(idx)) <= 5


def test_fe_inevitable_en_laboratorio_y_sin_cupo():
    ses = sesiones_del_mes(2025, 9, LMV)                       # 13 sesiones, 1 de laboratorio
    lab = dias_lab_por_defecto(2025, 9)
    r = repartir_fe([PacienteFe(1, ses, 13)], lab)
    assert len(r.asignado[1]) == 13 and r.en_lab == {1: 1}
    r = repartir_fe([PacienteFe(1, ses, 12)], lab)
    assert date(2025, 9, 10) not in r.asignado[1] and r.en_lab == {}
    r = repartir_fe([PacienteFe(1, ses, 15)], lab)
    assert r.sin_cupo == {1: 2} and len(r.asignado[1]) == 13


def _pacientes(n, rng, grupos=(LMV, MJS), anio=2026, mes=3):
    return [PacienteFe(i, sesiones_del_mes(anio, mes, grupos[i % len(grupos)]), rng.randint(1, 6))
            for i in range(1, n + 1)]


def test_fe_balancea_la_carga_diaria_de_la_unidad():
    rng = random.Random(14)
    ps = [PacienteFe(i, sesiones_del_mes(2026, 3, LMV), 2) for i in range(1, 61)]   # 120 dosis, 13 días
    r = repartir_fe(ps, [])
    cargas = [r.carga.get(d, 0) for d in sesiones_del_mes(2026, 3, LMV)]
    assert sum(cargas) == 120
    assert max(cargas) == 10                                   # óptimo: ⌈120/13⌉ = 10
    assert min(cargas) >= 8
    ps = _pacientes(144, rng)
    r = repartir_fe(ps, [])
    for grupo in (LMV, MJS):
        dias = sesiones_del_mes(2026, 3, grupo)
        cargas = [r.carga.get(d, 0) for d in dias]
        total = sum(p.dosis for p in ps if p.sesiones == dias)
        assert sum(cargas) == total
        assert max(cargas) <= -(-total // len(dias)) + 2      # a lo sumo 2 sobre el promedio


def test_fe_balanceo_con_laboratorio_respeta_mayoria_y_reparte_tramos():
    ps = [PacienteFe(i, sesiones_del_mes(2025, 9, LMV), 3) for i in range(1, 41)]
    lab = dias_lab_por_defecto(2025, 9)
    r = repartir_fe(ps, lab)
    antes = [d for d in sesiones_del_mes(2025, 9, LMV) if d < lab[0]]     # 1, 3, 5, 8
    despues = [d for d in sesiones_del_mes(2025, 9, LMV) if d > lab[0]]
    assert all(sum(1 for d in r.asignado[p.pid] if d < lab[0]) == 2 for p in ps)
    assert sorted(r.carga.get(d, 0) for d in antes) == [20, 20, 20, 20]  # 80 dosis en 4 días: parejo
    post = [r.carga.get(d, 0) for d in despues]
    assert sum(post) == 40 and max(post) - min(post) <= 1
    assert not any(r.carga.get(d) for d in lab)


def test_fe_carga_base_de_otros_dias_se_respeta():
    ses = sesiones_del_mes(2026, 3, LMV)
    base = {ses[1]: 50}
    r = repartir_fe([PacienteFe(1, ses, 13 // 2)], [], base)
    assert ses[1] not in r.asignado[1]


def test_fe_determinista_e_independiente_del_orden():
    rng = random.Random(7)
    ps = _pacientes(80, rng)
    lab = dias_lab_por_defecto(2026, 3)
    a = repartir_fe(ps, lab).asignado
    ps2 = [PacienteFe(p.pid, list(reversed(p.sesiones)), p.dosis) for p in reversed(ps)]
    b = repartir_fe(ps2, lab).asignado
    assert a == b


@pytest.mark.parametrize("mes", range(1, 13))
def test_fe_propiedades_todo_el_anio(mes):
    rng = random.Random(mes)
    ps = _pacientes(60, rng, anio=2027, mes=mes)
    lab = dias_lab_por_defecto(2027, mes)
    r = repartir_fe(ps, lab)
    for p in ps:
        fe = r.asignado[p.pid]
        normales = [s for s in p.sesiones if s not in lab]
        assert len(fe) == min(p.dosis, len(p.sesiones))
        assert fe <= set(p.sesiones)
        if p.dosis <= len(normales):
            assert not fe & set(lab)
            antes = sum(1 for d in fe if d < lab[0])
            n_antes = sum(1 for d in normales if d < lab[0])
            assert antes == min(p.dosis // 2 + 1, n_antes, p.dosis) or antes >= p.dosis - sum(
                1 for d in normales if d > lab[0])


def test_fe_libres_y_fijas():
    ses = sesiones_del_mes(2025, 9, LMV)
    fija = ses[0]
    r = repartir_fe([PacienteFe(1, ses, 2, libres=ses[2:], dosis_mes=3, fijas_antes=1, fijas={fija})], [])
    assert len(r.asignado[1]) == 2 and fija not in r.asignado[1] and ses[1] not in r.asignado[1]
