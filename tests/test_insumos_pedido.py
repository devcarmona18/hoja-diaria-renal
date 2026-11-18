"""R5/R6 — pedido de insumos: día siguiente, cambios de un día, inactivos,
adicionales, devoluciones / revisar, foto inmutable, CSV y modo demo.
Datos FICTICIOS (semilla). Cada prueba deja pacientes y fechas como estaban."""
import csv
import io
from datetime import date

import pytest

import models
from database import SessionLocal

SAB, LUN, MAR = "2028-01-08", "2028-01-10", "2028-01-11"
assert date.fromisoformat(SAB).weekday() == 5 and date.fromisoformat(LUN).weekday() == 0
DESDE = "2028-01-01"
CAMPOS = ("turno", "estacion", "cama", "dias", "activo", "motivo_inactivo", "adicional", "citrato",
          "heparina_sodica", "acceso", "acceso_calibre", "acceso_estado", "acceso_sitio", "tipo_filtro")


@pytest.fixture
def c(admin):
    with SessionLocal() as db:
        foto = {p.id: tuple(getattr(p, k) for k in CAMPOS) for p in db.query(models.Paciente).all()}
    yield admin
    with SessionLocal() as db:
        db.query(models.PedidoInsumosItem).delete()
        db.query(models.PedidoInsumos).delete()
        db.query(models.InsumosConfig).delete()
        db.query(models.AsignacionDia).filter(models.AsignacionDia.fecha >= DESDE).delete()
        ses = [s.id for s in db.query(models.Sesion).filter(models.Sesion.fecha >= DESDE)]
        if ses:
            db.query(models.Registro).filter(models.Registro.sesion_id.in_(ses)).delete()
            db.query(models.Sesion).filter(models.Sesion.id.in_(ses)).delete()
        db.query(models.Programacion).filter(models.Programacion.fecha >= DESDE).delete()
        for p in db.query(models.Paciente).all():
            if p.id in foto:
                for k, v in zip(CAMPOS, foto[p.id]):
                    setattr(p, k, v)
        db.commit()


def pac(c, turno, est, cama):
    return next(p for p in c.get(f"/api/pacientes?turno={turno}").json()
                if p["estacion"] == est and p["cama"] == cama)


def set_pac(pid, **kw):
    with SessionLocal() as db:
        p = db.get(models.Paciente, pid)
        for k, v in kw.items():
            setattr(p, k, v)
        db.commit()


def pedido(c, fecha, **params):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    r = c.get(f"/api/insumos/pedido?fecha={fecha}" + (f"&{q}" if q else ""))
    assert r.status_code == 200, r.text
    return r.json()


def fila(d, seccion, pid):
    return next((f for f in d["secciones"][seccion] if f["paciente_id"] == pid), None)


def items(f):
    return {i["codigo"]: i["cantidad"] for i in f["items"]}


def total(d, seccion, codigo):
    return next((i["cantidad"] for i in d["totales"][seccion] if i["codigo"] == codigo), 0)


def registros(c, fecha, turno="M"):
    s = c.get(f"/api/sesiones/{fecha}/{turno}").json()
    regs = c.get(f"/api/sesiones/{s['id']}/registros").json()
    return s, {r["paciente_id"]: r for r in regs}


def marcar(c, rid, **kw):
    r = c.patch(f"/api/sesiones/registros/{rid}", json=kw)
    assert r.status_code == 200, r.text


# ── Próximo día ───────────────────────────────────────────────────────────────

def test_sabado_pide_para_el_lunes_y_solo_activos(c):
    fav = pac(c, "M", 1, 1)
    inactivo = pac(c, "M", 1, 2)
    set_pac(inactivo["id"], activo=False, motivo_inactivo="hospitalizado")
    d = pedido(c, SAB)
    assert (d["fecha_sesiones"], d["dia_sesiones"]) == (LUN, "lunes")
    assert d["confirmado"] is None
    ids = {f["paciente_id"] for f in d["secciones"]["pedido"]}
    assert fav["id"] in ids and inactivo["id"] not in ids
    assert len(ids) == 143                                   # 144 ficticios − 1 inactivo
    f = fila(d, "pedido", fav["id"])
    assert f["turno"] == "M" and f["cama_global"] == 1 and f["fecha_sesion"] == LUN
    assert items(f)[f"aguja_fav_{fav['acceso_calibre']}"] == 2
    # totales: un kit por sesión
    kits = total(d, "pedido", "kit_fistula") + total(d, "pedido", "kit_cateter")
    assert kits == 143 and total(d, "pedido", "linea") == 143
    # lunes → los CY sin citrato llevan guantes e IV3000
    n_cy = sum(1 for f in d["secciones"]["pedido"] if f["acceso"].startswith("Catéter"))
    assert total(d, "pedido", "aposito_iv3000") == n_cy > 0


def test_lunes_pide_para_el_martes_con_dias_de_dialisis(c):
    lmv, mjs = pac(c, "T", 2, 1), pac(c, "T", 2, 2)
    set_pac(lmv["id"], dias="LMV")
    set_pac(mjs["id"], dias="MJS")
    d = pedido(c, LUN)
    assert d["fecha_sesiones"] == MAR
    ids = {f["paciente_id"] for f in d["secciones"]["pedido"]}
    assert mjs["id"] in ids and lmv["id"] not in ids


def test_fecha_invalida_o_sesiones_no_posteriores(c):
    assert c.get("/api/insumos/pedido?fecha=2028-13-01").status_code == 400
    assert c.get(f"/api/insumos/pedido?fecha={LUN}&fecha_sesiones={LUN}").status_code == 400


def test_cambios_de_un_dia_se_reflejan(c):
    """Transitorio de otro turno en una cama libre del lunes: va con turno y cama del lunes."""
    libre = pac(c, "T", 3, 16)
    set_pac(libre["id"], dias="MJS")                         # el lunes su cama queda libre
    x = pac(c, "M", 3, 5)
    r = c.post("/api/asignaciones", json={"fecha": LUN, "turno": "T", "paciente_id": x["id"],
                                          "estacion": 3, "cama": 16})
    assert r.status_code == 201, r.text
    d = pedido(c, SAB)
    f = fila(d, "pedido", x["id"])
    assert (f["turno"], f["estacion"], f["cama"], f["tipo"]) == ("T", 3, 16, "transitorio")
    assert sum(1 for g in d["secciones"]["pedido"] if g["paciente_id"] == x["id"]) == 1
    assert fila(d, "pedido", libre["id"]) is None
    # el cambio es solo de ese día: el pedido del martes lo deja en su turno habitual
    f2 = fila(pedido(c, LUN), "pedido", x["id"])
    assert (f2["turno"], f2["estacion"], f2["cama"]) == ("M", 3, 5)


def test_reemplazo_pide_para_el_suplente(c):
    q = pac(c, "M", 2, 3)
    sup = pac(c, "T", 2, 3)
    set_pac(sup["id"], dias="MJS")                           # el lunes no le toca su turno
    r = c.post("/api/asignaciones", json={"fecha": LUN, "turno": "M", "paciente_id": sup["id"],
                                          "tipo": "reemplazo", "reemplaza_paciente_id": q["id"]})
    assert r.status_code == 201, r.text
    d = pedido(c, SAB)
    assert fila(d, "pedido", q["id"]) is None
    f = fila(d, "pedido", sup["id"])
    assert (f["turno"], f["cama_global"], f["tipo"]) == ("M", 19, "reemplazo")


def test_calibre_faltante_aparece_en_revisar(c):
    p = pac(c, "N", 1, 1)
    set_pac(p["id"], acceso="FAV", acceso_estado="limpia", acceso_calibre=None)
    d = pedido(c, SAB)
    f = fila(d, "pedido", p["id"])
    assert "Calibre faltante" in f["alertas"]
    assert not any(k.startswith("aguja") for k in items(f))
    assert "Calibre faltante" in fila(d, "revisar", p["id"])["motivo"]


def test_citrato_del_paciente_cambia_tego_por_tapas(c):
    p = pac(c, "M", 1, 5)                                    # idx 4 → CY yugular en la semilla
    assert p["acceso"] == "CY"
    sin = items(fila(pedido(c, SAB), "pedido", p["id"]))
    assert sin["tego"] == 2 and sin["guantes_esteriles_6_5"] == 1 and "tapas_luer_lock" not in sin
    set_pac(p["id"], citrato=True)
    con = items(fila(pedido(c, SAB), "pedido", p["id"]))
    assert con["tapas_luer_lock"] == 1 and con["guantes_esteriles_6_5"] == 2 and "tego" not in con


def test_filtros_por_turno_y_estacion(c):
    todo = pedido(c, SAB)
    m = pedido(c, SAB, turno="M")
    m2 = pedido(c, SAB, turno="M", estacion=2)
    assert {f["turno"] for f in m["secciones"]["pedido"]} == {"M"}
    assert {(f["turno"], f["estacion"]) for f in m2["secciones"]["pedido"]} == {("M", 2)}
    assert len(todo["secciones"]["pedido"]) == 144 and len(m["secciones"]["pedido"]) == 48
    assert len(m2["secciones"]["pedido"]) == 16 and total(m2, "pedido", "linea") == 16
    assert c.get(f"/api/insumos/pedido?fecha={SAB}&turno=X").status_code == 422


# ── Adicionales ───────────────────────────────────────────────────────────────

def test_paciente_adicional_va_al_pedido_del_dia_que_llega(c):
    a = pac(c, "M", 1, 3)
    set_pac(a["id"], adicional=True)
    # en el pedido del sábado (sesiones del lunes) NO va: solo como previsto
    d = pedido(c, SAB)
    assert fila(d, "pedido", a["id"]) is None
    assert any(x["nombre"] == a["nombre"] for x in d["adicionales_previstos"])
    # el lunes llega: va a «Adicionales» del pedido del lunes
    _, regs = registros(c, LUN)
    d = pedido(c, LUN)
    assert fila(d, "adicional", a["id"]) is None
    assert any(x["nombre"] == a["nombre"] and x["motivo"] == "Adicional aún sin llegar" for x in d["pendientes"])
    marcar(c, regs[a["id"]]["id"], asistencia="A", peso_entrada=70.2)
    d = pedido(c, LUN)
    f = fila(d, "adicional", a["id"])
    assert f and f["fecha_sesion"] == LUN and f["motivo"] == "Paciente adicional"
    assert fila(d, "pedido", a["id"]) is None and fila(d, "devolucion", a["id"]) is None
    assert total(d, "adicional", "linea") == 1


def test_adicional_de_un_dia_desde_la_hoja(c):
    b = pac(c, "T", 1, 4)
    set_pac(b["id"], dias="MJS")                             # el lunes no le toca
    s, _ = registros(c, LUN)
    r = c.post(f"/api/sesiones/{s['id']}/paciente/{b['id']}")   # admisión en el día
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    marcar(c, rid, asistencia="A", peso_entrada=61.0)
    d = pedido(c, LUN)
    assert fila(d, "adicional", b["id"]) is None
    assert "adicional" in fila(d, "revisar", b["id"])["motivo"]
    marcar(c, rid, adicional=True)
    _, regs = registros(c, LUN)
    assert regs[b["id"]]["adicional"] is True
    d = pedido(c, LUN)
    assert fila(d, "adicional", b["id"])["motivo"] == "Adicional de hoy"
    assert fila(d, "revisar", b["id"]) is None


def test_adicional_que_ya_estaba_en_el_pedido_no_se_duplica(c):
    p = pac(c, "M", 1, 6)
    _, regs = registros(c, LUN)
    marcar(c, regs[p["id"]]["id"], asistencia="A", peso_entrada=60.0, adicional=True)
    d = pedido(c, LUN)
    assert fila(d, "adicional", p["id"]) is None
    assert "ya estaba en el pedido" in fila(d, "revisar", p["id"])["motivo"]


# ── Devoluciones y revisar ────────────────────────────────────────────────────

def test_devoluciones_y_revisar(c):
    na, a_sin_peso, peso_sin_a, ok, sin_marcar, h = (pac(c, "M", 2, i) for i in range(1, 7))
    assert c.post("/api/insumos/pedido/confirmar", json={"fecha": SAB}).status_code == 201
    s, regs = registros(c, LUN)
    marcar(c, regs[na["id"]]["id"], asistencia="NA")
    marcar(c, regs[a_sin_peso["id"]]["id"], asistencia="A")
    marcar(c, regs[peso_sin_a["id"]]["id"], peso_entrada=66.0)
    marcar(c, regs[ok["id"]]["id"], asistencia="A", peso_entrada=64.0)
    marcar(c, regs[h["id"]]["id"], asistencia="H")
    d = pedido(c, LUN)
    assert d["origen_devoluciones"] == {"tipo": "confirmado", "fecha_pedido": SAB}
    dev = {f["paciente_id"]: f for f in d["secciones"]["devolucion"]}
    assert set(dev) == {na["id"], h["id"]}
    assert dev[na["id"]]["motivo"] == "No asistió" and dev[h["id"]]["motivo"] == "Hospitalizado"
    assert dev[na["id"]]["items"]                             # devuelve lo que se pidió
    rev = {f["paciente_id"]: f["motivo"] for f in d["secciones"]["revisar"]}
    assert "sin peso" in rev[a_sin_peso["id"]]
    assert "asistencia no es A" in rev[peso_sin_a["id"]]
    assert ok["id"] not in rev and ok["id"] not in dev
    assert sin_marcar["id"] not in rev and sin_marcar["id"] not in dev
    assert any(x["nombre"] == sin_marcar["nombre"] and x["motivo"] == "Asistencia sin marcar"
               for x in d["pendientes"])
    # turnos T y N: hoja sin abrir → pendientes, nunca devolución
    assert d["hojas_hoy"]["T"]["abierta"] is False
    assert all(f["turno"] == "M" for f in d["secciones"]["devolucion"])
    assert total(d, "devolucion", "linea") == 2
    neto = {i["codigo"]: i["cantidad"] for i in d["totales"]["neto"]}
    assert neto["linea"] == total(d, "pedido", "linea") - 2
    # al cerrar la hoja, el que quedó sin marcar y sin peso pasa a devolución
    assert c.post(f"/api/cierre/{s['id']}/cerrar", json={}).status_code == 200
    d = pedido(c, LUN)
    dev = {f["paciente_id"]: f for f in d["secciones"]["devolucion"]}
    assert dev[sin_marcar["id"]]["motivo"] == "Sin asistencia (hoja cerrada)"


def test_devoluciones_sin_pedido_confirmado_se_recalculan(c):
    p = pac(c, "M", 3, 1)
    _, regs = registros(c, LUN)
    marcar(c, regs[p["id"]]["id"], asistencia="NA")
    d = pedido(c, LUN)
    assert d["origen_devoluciones"]["tipo"] == "recalculado"
    assert fila(d, "devolucion", p["id"])["fecha_sesion"] == LUN


def test_pedido_sin_fila_en_la_hoja_va_a_revisar(c):
    p = pac(c, "M", 3, 2)
    assert c.post("/api/insumos/pedido/confirmar", json={"fecha": SAB}).status_code == 201
    s, regs = registros(c, LUN)
    with SessionLocal() as db:
        db.delete(db.get(models.Registro, regs[p["id"]]["id"]))
        db.commit()
    assert "no figura en la hoja" in fila(pedido(c, LUN), "revisar", p["id"])["motivo"]


# ── Foto inmutable ────────────────────────────────────────────────────────────

def test_confirmar_guarda_foto_inmutable(c):
    p = pac(c, "M", 1, 1)
    calibre = p["acceso_calibre"]
    r = c.post("/api/insumos/pedido/confirmar", json={"fecha": SAB})
    assert r.status_code == 201, r.text
    antes = r.json()
    assert antes["confirmado"]["por"] == "admin"
    # cambios posteriores: paciente y reglas
    set_pac(p["id"], acceso_calibre=15 if calibre != 15 else 17, tipo_filtro="OTRO-9", activo=False)
    reglas = c.get("/api/insumos/reglas").json()["reglas"]
    reglas["reglas"][1]["cantidad"] = 5                       # agujas ×5
    assert c.put("/api/insumos/reglas", json=reglas).status_code == 200
    despues = pedido(c, SAB)
    assert despues["secciones"]["pedido"] == antes["secciones"]["pedido"]
    assert despues["totales"]["pedido"] == antes["totales"]["pedido"]
    f = fila(despues, "pedido", p["id"])
    assert items(f)[f"aguja_fav_{calibre}"] == 2
    # confirmar dos veces no se puede
    assert c.post("/api/insumos/pedido/confirmar", json={"fecha": SAB}).status_code == 409
    assert c.get("/api/insumos/pedidos").json()[0]["fecha_pedido"] == SAB
    # anular vuelve al borrador en vivo (ya con los cambios)
    assert c.delete(f"/api/insumos/pedido/{SAB}").status_code == 200
    vivo = pedido(c, SAB)
    assert vivo["confirmado"] is None and fila(vivo, "pedido", p["id"]) is None
    assert c.delete(f"/api/insumos/pedido/{SAB}").status_code == 404


def test_archivado_sale_del_pedido_futuro_pero_no_del_confirmado(c):
    """R13: archivar no altera la foto de un pedido confirmado, pero el paciente
    ya no entra a la composición en vivo de pedidos futuros sin confirmar."""
    p = pac(c, "M", 1, 3)
    with SessionLocal() as db:
        max_inac = max([i.id for i in db.query(models.PacienteInactividad)] or [0])
        cols = [k.name for k in models.Programacion.__table__.columns]
        prog = [{k: getattr(r, k) for k in cols}
                for r in db.query(models.Programacion).filter_by(paciente_id=p["id"])]
    try:
        assert c.post("/api/insumos/pedido/confirmar", json={"fecha": SAB}).status_code == 201
        r = c.post(f"/api/pacientes/{p['id']}/archivar", json={"motivo": "Traslado"})
        assert r.status_code == 200, r.text
        confirmado = pedido(c, SAB)
        assert confirmado["confirmado"] is not None
        assert fila(confirmado, "pedido", p["id"]) is not None          # la foto no cambia
        futuro = pedido(c, LUN)                                          # sin confirmar: en vivo
        assert futuro["confirmado"] is None
        ids = {f["paciente_id"] for s in ("pedido", "adicional") for f in futuro["secciones"][s]}
        assert p["id"] not in ids
        assert c.delete(f"/api/insumos/pedido/{SAB}").status_code == 200
        assert fila(pedido(c, SAB), "pedido", p["id"]) is None          # recalculado: ya no está
    finally:
        with SessionLocal() as db:
            pa = db.get(models.Paciente, p["id"])
            pa.archivado_en = pa.archivado_motivo = None
            pa.activo = True
            db.query(models.PacienteInactividad).filter(
                models.PacienteInactividad.id > max_inac).delete(synchronize_session=False)
            existentes = {r.id for r in db.query(models.Programacion).filter_by(paciente_id=p["id"])}
            for fila_prog in prog:
                if fila_prog["id"] not in existentes:
                    db.add(models.Programacion(**fila_prog))
            db.commit()


def test_novedades_despues_de_confirmar(c):
    a = pac(c, "M", 1, 7)
    set_pac(a["id"], adicional=True)
    assert c.post("/api/insumos/pedido/confirmar", json={"fecha": LUN}).status_code == 201
    _, regs = registros(c, LUN)
    marcar(c, regs[a["id"]]["id"], asistencia="A", peso_entrada=70.0)
    d = pedido(c, LUN)
    assert fila(d, "adicional", a["id"]) is None              # no estaba en lo enviado
    assert any(n["paciente_id"] == a["id"] and n["seccion"] == "adicional" for n in d["novedades"])


# ── CSV ───────────────────────────────────────────────────────────────────────

def test_csv(c):
    r = c.get(f"/api/insumos/pedido.csv?fecha={SAB}&turno=M&estacion=1")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert f"pedido-insumos-{SAB}-M-est1.csv" in r.headers["content-disposition"]
    assert r.text.startswith("﻿")
    filas = list(csv.reader(io.StringIO(r.text.lstrip("﻿")), delimiter=";"))
    assert "BORRADOR" in filas[0][3]
    assert filas[1][:3] == ["Sección", "Fecha sesión", "Turno"]
    datos = [f for f in filas[2:] if f and f[0] == "Pedido"]
    assert {f[2] for f in datos} == {"M"} and {f[3] for f in datos} == {"1"}
    assert len({f[5] for f in datos}) == 16
    i = filas.index(["TOTALES", "Sección", "Insumo", "Cantidad", "Unidad", "Detalle"])
    tot = {(f[1], f[2]): int(f[3]) for f in filas[i + 1:] if f}
    assert tot[("Pedido", "Línea arteriovenosa")] == 16
    assert any(k[0].startswith("Neto") for k in tot)


# ── Reglas editables ──────────────────────────────────────────────────────────

def test_reglas_editables_y_restaurables(c):
    r = c.get("/api/insumos/reglas").json()
    assert r["origen"] == "predeterminadas"
    reglas = r["reglas"]
    reglas["reglas"].append({"insumo": "linea", "si": {"acceso": ["FAV"]}, "cantidad": 1})
    g = c.put("/api/insumos/reglas", json=reglas)
    assert g.status_code == 200 and g.json()["origen"] == "personalizadas"
    p = pac(c, "M", 1, 1)
    assert items(fila(pedido(c, SAB), "pedido", p["id"]))["linea"] == 2
    malo = c.put("/api/insumos/reglas", json={**reglas, "reglas": [{"insumo": "nada", "cantidad": 1}]})
    assert malo.status_code == 422 and "catálogo" in malo.json()["detail"]
    assert c.delete("/api/insumos/reglas").json()["origen"] == "predeterminadas"
    assert items(fila(pedido(c, SAB), "pedido", p["id"]))["linea"] == 1
    assert c.get("/api/insumos/reglas/por-defecto").json()["version"] == 1


# ── Demo y CRUD ───────────────────────────────────────────────────────────────

def test_demo_solo_lectura(demo):
    assert demo.get(f"/api/insumos/pedido?fecha={SAB}").status_code == 200
    assert demo.get(f"/api/insumos/pedido.csv?fecha={SAB}").status_code == 200
    assert demo.post("/api/insumos/pedido/confirmar", json={"fecha": SAB}).status_code == 403
    assert demo.put("/api/insumos/reglas", json={}).status_code == 403
    assert demo.delete("/api/insumos/reglas").status_code == 403


def test_crud_paciente_adicional_citrato_heparina(c):
    from helpers_w1 import paciente_temporal
    with paciente_temporal(c, "T-INS-001", acceso="CY", acceso_sitio="femoral", adicional=True,
                           citrato=True, heparina_sodica=False) as r:
        assert r.status_code == 201, r.text
        p = r.json()
        assert (p["adicional"], p["citrato"], p["heparina_sodica"]) == (True, True, False)
        # FAV: citrato / heparina sódica no aplican
        u = c.put(f"/api/pacientes/{p['id']}", json={**p, "acceso": "FAV", "acceso_estado": "limpia",
                                                    "acceso_calibre": 16})
        assert u.status_code == 200 and u.json()["citrato"] is None and u.json()["adicional"] is True
    with paciente_temporal(c, "T-INS-002") as r:
        assert r.json()["adicional"] is None                 # vacío = no


def test_migracion_crea_tablas_y_columnas(tmp_path):
    from sqlalchemy import create_engine, inspect, text
    import migraciones
    eng = create_engine(f"sqlite:///{tmp_path}/vieja.db")
    with eng.begin() as con:
        con.execute(text("CREATE TABLE pacientes (id INTEGER PRIMARY KEY, nombre TEXT, acceso TEXT)"))
        con.execute(text("CREATE TABLE registros (id INTEGER PRIMARY KEY, sesion_id INTEGER, paciente_id INTEGER)"))
    hechas = migraciones.aplicar(eng)
    assert {"+pacientes.adicional", "+pacientes.citrato", "+pacientes.heparina_sodica",
            "+registros.adicional", "+tabla pedido_insumos", "+tabla pedido_insumos_items",
            "+tabla insumos_config"} <= set(hechas)
    assert migraciones.aplicar(eng) == []
    assert inspect(eng).has_table("pedido_insumos_items")
    eng.dispose()


def test_menu_pedido_de_insumos_antes_de_proximamente(anonimo):
    import re
    js = anonimo.get("/static/js/app.js").text
    bloque = js[js.index("const MENU_INICIO = ["):]
    ids = re.findall(r'\{ id: "([a-z]+)"', bloque[:bloque.index("\n]\n")])
    assert ids[-2:] == ["insumos", "proximamente"]
    html = anonimo.get("/static/index.html").text
    assert "/static/js/insumos.js" in html and "/static/css/insumos.css" in html
    assert "function renderInsumos(" in anonimo.get("/static/js/insumos.js").text
