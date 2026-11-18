"""
Auto-programación mensual de EPO / hierro (R14): capa de base de datos.

El reparto (qué sesión lleva qué) lo decide ``services/epo_fe_algoritmo.py``
(puro, probado aparte). Aquí se guarda, se reprograma por inasistencia y se
llena la hoja diaria. Reglas completas en docs/epo-hierro.md.

Tablas
------
- ``epo_fe_mes``: totales del mes por paciente (jeringas EPO de 4.000 UI, dosis Fe).
- ``epo_fe_celdas``: PLAN por sesión (``manual`` = ajuste del administrador).
- ``epo_fe_movimientos``: reprogramaciones por inasistencia (origen → destino).
- ``epo_fe_config_mes``: días de laboratorio del mes si no son los por defecto.
- ``epo_fe_auditoria``: bitácora.

Valor EFECTIVO de una sesión = plan + lo que le llega reprogramado; una sesión
a la que faltó el paciente queda en 0 (su dosis se fue a otra).

Estado de un día del paciente (solo cuentan las hojas CERRADAS):
- ``asistio``: fila con asistencia A o con peso de entrada (misma regla que insumos).
- ``falto``: fila en hoja cerrada sin A y sin peso de entrada; o su hoja habitual
  (su turno) de ese día cerrada y él no aparece en ninguna hoja de ese día.
- ``inactivo``: el día cae en un periodo de inactividad/archivo (no se reprograma).
- sin estado: día aún abierto o futuro (puede recibir dosis reprogramadas).
"""
from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import date, datetime
from typing import Iterable, Optional

from sqlalchemy.orm import Session

import models
from services import epo_fe_algoritmo as alg
from services.asistencia import ReglaError, validar_mes
from services.medicos import iniciales_medico, normalizar
from services.pacientes import ahora_utc, consulta_activos
from services.tiempo import hoy_local

JERINGA_UI = alg.JERINGA_UI
DIAS_SEMANA = {"LMV": (0, 2, 4), "MJS": (1, 3, 5), "TJS": (1, 3, 5)}
DIA_CORTO = ["L", "M", "X", "J", "V", "S", "D"]
ASISTIO, FALTO, INACTIVO = "asistio", "falto", "inactivo"
MAX_EPO_CELDA = 6


# ── Utilidades ────────────────────────────────────────────────────────────────

def _anio_mes(mes: str) -> tuple[int, int]:
    validar_mes(mes)
    return int(mes[:4]), int(mes[5:])


def mes_de(fecha: str) -> str:
    return fecha[:7]


def _d(s: str) -> date:
    return date.fromisoformat(s)


def _auditar(db: Session, mes: str, accion: str, detalle: str, usuario: str,
             paciente_id: Optional[int] = None) -> None:
    db.add(models.EpoFeAuditoria(mes=mes, paciente_id=paciente_id, accion=accion,
                                 detalle=detalle[:400], usuario=usuario, creado_en=ahora_utc()))


def dias_semana(p: models.Paciente) -> Optional[tuple[int, ...]]:
    return DIAS_SEMANA.get((p.dias or "").strip().upper())


def jeringas_por_defecto(p: models.Paciente) -> int:
    """EPO del mes por defecto: UI mensuales de la ficha ÷ 4.000 (redondeado)."""
    return int(round((p.epo_mensual or 0) / JERINGA_UI)) if p.epo_mensual else 0


def dias_lab(db: Session, mes: str) -> tuple[list[date], bool]:
    """(días de laboratorio del mes, ¿son los de la regla por defecto?)."""
    anio, m = _anio_mes(mes)
    cfg = db.get(models.EpoFeConfigMes, mes)
    if cfg is not None:     # fijados a mano para ese mes (lista vacía = sin días de laboratorio)
        return sorted(_d(x) for x in (cfg.dias_lab or "").split(",") if x.strip()), False
    return alg.dias_lab_por_defecto(anio, m), True


def _periodos(db: Session, pids: Iterable[int]) -> dict[int, list[tuple[str, Optional[str]]]]:
    per: dict[int, list] = defaultdict(list)
    pids = list(pids)
    if not pids:
        return per
    for r in db.query(models.PacienteInactividad).filter(models.PacienteInactividad.paciente_id.in_(pids)).all():
        per[r.paciente_id].append((r.desde, r.hasta))
    return per


def _inactivo_en(periodos: list, fecha: str) -> bool:
    return any(desde <= fecha and (hasta is None or fecha < hasta) for desde, hasta in periodos)


def sesiones_paciente(p: models.Paciente, mes: str, periodos: list) -> list[date]:
    anio, m = _anio_mes(mes)
    ws = dias_semana(p)
    if not ws:
        return []
    fuera = [d for d in alg.dias_del_mes(anio, m) if _inactivo_en(periodos, d.isoformat())]
    return alg.sesiones_del_mes(anio, m, ws, fuera)


# ── Estado de cada día (asistió / faltó) ─────────────────────────────────────

def estados(db: Session, mes: str, pacientes: dict[int, models.Paciente]) -> dict[tuple[int, str], str]:
    out: dict[tuple[int, str], str] = {}
    if not pacientes:
        return out
    ses = db.query(models.Sesion).filter(models.Sesion.fecha.startswith(mes)).all()
    if not ses:
        return out
    por_id = {s.id: s for s in ses}
    cerrada = {(s.fecha, s.turno): bool(s.cerrada) for s in ses}
    con_fila: set[tuple[int, str]] = set()
    for r in db.query(models.Registro).filter(models.Registro.sesion_id.in_(list(por_id))).all():
        s = por_id[r.sesion_id]
        personas = []
        if r.transitorio_paciente_id:
            personas.append((r.paciente_id, False))
            vino = r.transitorio_asistencia == "A" or r.peso_entrada is not None
            personas.append((r.transitorio_paciente_id, vino))
        else:
            personas.append((r.paciente_id, r.asistencia == "A" or r.peso_entrada is not None))
        for pid, vino in personas:
            con_fila.add((pid, s.fecha))
            if not s.cerrada:
                continue
            clave = (pid, s.fecha)
            if vino:
                out[clave] = ASISTIO
            else:
                out.setdefault(clave, FALTO)
    per = _periodos(db, pacientes)
    anio, m = _anio_mes(mes)
    for pid, p in pacientes.items():
        for d in alg.dias_del_mes(anio, m):
            f = d.isoformat()
            if _inactivo_en(per.get(pid, []), f):
                out[(pid, f)] = INACTIVO
            elif (pid, f) not in con_fila and cerrada.get((f, p.turno)):
                ws = dias_semana(p)
                if ws and d.weekday() in ws:
                    out[(pid, f)] = FALTO     # su hoja de ese día se cerró y no aparece
    return out


# ── Carga del estado del mes ─────────────────────────────────────────────────

class Mes:
    def __init__(self, db: Session, mes: str):
        self.db, self.mes = db, mes
        self.anio, self.m = _anio_mes(mes)
        self.lab, self.lab_defecto = dias_lab(db, mes)
        self.totales = {t.paciente_id: t for t in db.query(models.EpoFeMesPaciente).filter_by(mes=mes).all()}
        self.celdas: dict[int, dict[str, models.EpoFeCelda]] = defaultdict(dict)
        for c in db.query(models.EpoFeCelda).filter_by(mes=mes).all():
            self.celdas[c.paciente_id][c.fecha] = c
        self.movs = (db.query(models.EpoFeMovimiento).filter_by(mes=mes, activo=True)
                     .order_by(models.EpoFeMovimiento.fecha_origen, models.EpoFeMovimiento.id).all())
        pids = set(self.totales) | set(self.celdas)
        self.pacientes = ({p.id: p for p in db.query(models.Paciente).filter(models.Paciente.id.in_(list(pids))).all()}
                          if pids else {})
        self.estado = estados(db, mes, self.pacientes)

    @property
    def generado(self) -> bool:
        return bool(self.totales)

    def efectivo(self) -> dict[tuple[int, str], list[int]]:
        """(pid, fecha) → [jeringas EPO, dosis Fe] efectivas (plan + llegan − salen)."""
        ef: dict[tuple[int, str], list[int]] = {}
        for pid, cs in self.celdas.items():
            for f, c in cs.items():
                ef[(pid, f)] = [c.epo or 0, c.fe or 0]
        for mv in self.movs:
            i = 0 if mv.tipo == "epo" else 1
            ef.setdefault((mv.paciente_id, mv.fecha_origen), [0, 0])[i] = 0
            if mv.fecha_destino:
                ef.setdefault((mv.paciente_id, mv.fecha_destino), [0, 0])[i] += mv.cantidad
        return ef


# ── Planificación (generar / regenerar / replanificar pacientes) ─────────────

def _fija(mesobj: Mes, pid: int, f: str, c: models.EpoFeCelda) -> bool:
    return bool(c.manual) or mesobj.estado.get((pid, f)) in (ASISTIO, FALTO, INACTIVO)


def _planificar(db: Session, mesobj: Mes, pids: set[int], regenerar: bool = False) -> None:
    """Reparte las dosis de ``pids`` en sus sesiones NO fijas (manuales o ya cerradas)."""
    lab = set(mesobj.lab)
    primer_lab = min(lab) if lab else None
    periodos = _periodos(db, pids)
    llegan_fe: dict[int, set[str]] = defaultdict(set)
    destinos: set[tuple[int, str]] = set()
    carga: dict[date, int] = defaultdict(int)
    for mv in mesobj.movs:
        if mv.fecha_destino:
            destinos.add((mv.paciente_id, mv.fecha_destino))
            if mv.tipo == "fe":
                llegan_fe[mv.paciente_id].add(mv.fecha_destino)
                carga[_d(mv.fecha_destino)] += 1
    for pid, cs in mesobj.celdas.items():          # hierro de los demás pacientes
        if pid in pids:
            continue
        for f, c in cs.items():
            if c.fe:
                carga[_d(f)] += 1

    planes_epo: dict[int, dict[date, int]] = {}
    sesiones: dict[int, list[date]] = {}
    fijas_de: dict[int, set[str]] = {}
    pfe: list[alg.PacienteFe] = []
    for pid in sorted(pids):
        p = mesobj.pacientes[pid]
        tot = mesobj.totales[pid]
        cs = mesobj.celdas.get(pid, {})
        if regenerar:
            for c in cs.values():
                c.manual = False
        fijas = {f: c for f, c in cs.items() if _fija(mesobj, pid, f, c)}
        fijas_de[pid] = set(fijas)
        ses = sesiones_paciente(p, mesobj.mes, periodos.get(pid, []))
        sesiones[pid] = ses
        libres = [s for s in ses if s.isoformat() not in fijas]
        epo_rest = max(0, (tot.epo_jeringas or 0) - sum(c.epo or 0 for c in fijas.values()))
        planes_epo[pid] = alg.repartir_epo(libres, epo_rest, lab)
        fe_fijas = [f for f, c in fijas.items() if c.fe]
        for f in fe_fijas:
            carga[_d(f)] += 1
        fe_rest = max(0, (tot.fe_dosis or 0) - len(fe_fijas))
        todas = sorted(set(ses) | {_d(f) for f in fijas})
        pfe.append(alg.PacienteFe(
            pid=pid, sesiones=todas, dosis=fe_rest,
            libres=[s for s in libres if s.isoformat() not in llegan_fe[pid]],
            dosis_mes=tot.fe_dosis or 0,
            fijas_antes=sum(1 for f in fe_fijas if primer_lab and _d(f) < primer_lab),
            fijas={_d(f) for f in fe_fijas} | {_d(f) for f in llegan_fe[pid]}))
    res = alg.repartir_fe(pfe, lab, dict(carga))

    for pid in sorted(pids):
        cs = mesobj.celdas[pid]
        fe = res.asignado.get(pid, set())
        en_plan = set()
        for s in sesiones[pid]:
            f = s.isoformat()
            if f in fijas_de[pid]:
                continue
            en_plan.add(f)
            c = cs.get(f)
            if c is None:
                c = models.EpoFeCelda(mes=mesobj.mes, paciente_id=pid, fecha=f)
                db.add(c)
                cs[f] = c
            c.epo, c.fe, c.manual = planes_epo[pid].get(s, 0), 1 if s in fe else 0, False
        for f in list(cs):
            if f not in en_plan and f not in fijas_de[pid]:
                c = cs[f]
                if (pid, f) in destinos:        # le llega una reprogramación: se conserva
                    c.epo, c.fe = 0, 0
                    continue
                db.delete(c)
                del cs[f]
    db.flush()


def generar(db: Session, mes: str, usuario: str, regenerar: bool = False) -> dict:
    """Crea la programación de los pacientes activos que aún no la tienen.

    ``regenerar``: rehace TODO el mes (borra los ajustes manuales; los días ya
    cerrados no cambian) con los totales guardados de cada paciente.
    """
    mesobj = Mes(db, mes)
    nuevos = []
    for p in consulta_activos(db).all():
        if p.id in mesobj.totales or not dias_semana(p):
            continue
        t = models.EpoFeMesPaciente(mes=mes, paciente_id=p.id, epo_jeringas=jeringas_por_defecto(p),
                                    fe_dosis=p.hierro_mensual or 0, actualizado_por=usuario,
                                    actualizado_en=ahora_utc())
        db.add(t)
        mesobj.totales[p.id] = t
        mesobj.pacientes[p.id] = p
        nuevos.append(p.id)
    db.flush()
    pids = set(mesobj.totales) if regenerar else set(nuevos)
    if pids:
        _planificar(db, mesobj, pids, regenerar=regenerar)
    _auditar(db, mes, "regenerar" if regenerar else "generar",
             f"{'Regenerado' if regenerar else 'Generado'}: {len(pids)} paciente(s)", usuario)
    rep = recalcular(db, mes, usuario, auditar_vacio=False)
    return {"pacientes": len(pids), "nuevos": len(nuevos), **rep}


def _exigir_plan(mesobj: Mes, pid: int) -> models.EpoFeMesPaciente:
    t = mesobj.totales.get(pid)
    if not t:
        raise ReglaError("El paciente no tiene programación en ese mes (use «Generar»).", 404)
    return t


def fijar_totales(db: Session, mes: str, pid: int, epo: Optional[int], fe: Optional[int], usuario: str) -> dict:
    mesobj = Mes(db, mes)
    t = _exigir_plan(mesobj, pid)
    antes = (t.epo_jeringas, t.fe_dosis)
    if epo is not None:
        t.epo_jeringas = epo
    if fe is not None:
        t.fe_dosis = fe
    t.actualizado_por, t.actualizado_en = usuario, ahora_utc()
    _planificar(db, mesobj, {pid})
    _auditar(db, mes, "totales", f"EPO {antes[0]}→{t.epo_jeringas} jer., Fe {antes[1]}→{t.fe_dosis}", usuario, pid)
    recalcular(db, mes, usuario, auditar_vacio=False)
    return {"ok": True}


def ajustar_celda(db: Session, mes: str, pid: int, fecha: str, epo: Optional[int], fe: Optional[int],
                  usuario: str, quitar_ajuste: bool = False) -> dict:
    """Ajuste manual de una sesión. El resto de sesiones automáticas se reparte de nuevo
    para mantener el total del mes. ``quitar_ajuste`` devuelve la sesión al reparto automático."""
    if mes_de(fecha) != mes:
        raise ReglaError("La fecha no pertenece al mes", 422)
    mesobj = Mes(db, mes)
    _exigir_plan(mesobj, pid)
    p = mesobj.pacientes[pid]
    st = mesobj.estado.get((pid, fecha))
    if st in (ASISTIO, FALTO):
        raise ReglaError("Ese día ya se cerró: no se puede cambiar su programación.", 409)
    c = mesobj.celdas[pid].get(fecha)
    if c is None:
        ws = dias_semana(p)
        if not ws or _d(fecha).weekday() not in ws:
            raise ReglaError("Ese día el paciente no dializa.", 422)
        c = models.EpoFeCelda(mes=mes, paciente_id=pid, fecha=fecha, epo=0, fe=0)
        db.add(c)
        mesobj.celdas[pid][fecha] = c
    antes = (c.epo, c.fe, c.manual)
    if quitar_ajuste:
        c.manual = False
    else:
        if epo is not None:
            c.epo = epo
        if fe is not None:
            c.fe = 1 if fe else 0
        c.manual = True
    db.flush()
    _planificar(db, mesobj, {pid})
    _auditar(db, mes, "celda", f"{fecha}: EPO {antes[0]}→{c.epo}, Fe {antes[1]}→{c.fe}"
             + (" (vuelve a automático)" if quitar_ajuste else " (ajuste manual)"), usuario, pid)
    recalcular(db, mes, usuario, auditar_vacio=False)
    return {"ok": True}


def configurar_lab(db: Session, mes: str, fechas: Optional[list[str]], usuario: str) -> dict:
    """Días de laboratorio del mes. ``None`` = volver a la regla por defecto; [] = sin días."""
    _anio_mes(mes)
    cfg = db.get(models.EpoFeConfigMes, mes)
    if fechas is None:
        if cfg:
            db.delete(cfg)
        detalle = "Días de laboratorio: regla por defecto"
    else:
        for f in fechas:
            try:
                d = _d(f)
            except ValueError:
                raise ReglaError(f"Fecha inválida: {f}", 422) from None
            if mes_de(f) != mes or d.weekday() == 6:
                raise ReglaError(f"{f} no es un día hábil de {mes}", 422)
        valor = ",".join(sorted(set(fechas)))
        if cfg is None:
            cfg = models.EpoFeConfigMes(mes=mes)
            db.add(cfg)
        cfg.dias_lab, cfg.actualizado_por, cfg.actualizado_en = valor, usuario, ahora_utc()
        detalle = f"Días de laboratorio: {valor or 'ninguno'}"
    db.flush()
    _auditar(db, mes, "config", detalle, usuario)
    mesobj = Mes(db, mes)
    if mesobj.totales:
        _planificar(db, mesobj, set(mesobj.totales))     # los ajustes manuales se respetan
        recalcular(db, mes, usuario, auditar_vacio=False)
    return {"ok": True}


def borrar_mes(db: Session, mes: str, usuario: str, hoy: Optional[date] = None) -> dict:
    anio, m = _anio_mes(mes)
    hoy = hoy or hoy_local()
    if (anio, m) >= (hoy.year, hoy.month):
        raise ReglaError("Solo se puede borrar la programación de un mes que ya terminó.", 409)
    n = db.query(models.EpoFeCelda).filter_by(mes=mes).delete()
    db.query(models.EpoFeMovimiento).filter_by(mes=mes).delete()
    db.query(models.EpoFeMesPaciente).filter_by(mes=mes).delete()
    db.query(models.EpoFeConfigMes).filter_by(mes=mes).delete()
    _auditar(db, mes, "borrar", f"Programación del mes borrada ({n} sesiones)", usuario)
    return {"ok": True, "celdas": n}


# ── Reprogramación por inasistencia ──────────────────────────────────────────

def recalcular(db: Session, mes: str, usuario: str, auditar_vacio: bool = True) -> dict:
    """Recorre el mes en orden y reprograma las dosis de los días en que el paciente faltó.

    - EPO: pasa COMPLETA a la siguiente sesión aún abierta del paciente (saltando días
      de laboratorio si hay otra): si esa tenía 1 jeringa queda en 2 (8.000 UI).
    - Hierro: pasa a una sesión futura aún abierta SIN hierro; se prefiere un día que
      no sea de laboratorio, luego el día con menos hierros en la unidad, luego el más cercano.
    Las reprogramaciones ya hechas se conservan (mismo destino); si la asistencia se
    corrige (sí vino) se revierten. Todo queda en la bitácora. Idempotente.
    """
    db.flush()
    mesobj = Mes(db, mes)
    resumen = {"reprogramadas": 0, "revertidas": 0, "ajustadas": 0, "sin_destino": 0}
    if not mesobj.generado:
        return resumen
    lab = {d.isoformat() for d in mesobj.lab}
    por_origen = {(mv.paciente_id, mv.fecha_origen, mv.tipo): mv for mv in mesobj.movs}
    vistos: set[int] = set()
    llega: dict[tuple[int, str, str], int] = defaultdict(int)
    plan = {(pid, f): c for pid, cs in mesobj.celdas.items() for f, c in cs.items()}
    carga_fe: dict[str, int] = defaultdict(int)
    for (pid, f), c in plan.items():
        if c.fe:
            carga_fe[f] += 1
    for mv in mesobj.movs:
        if mv.tipo == "fe" and mv.fecha_destino:
            carga_fe[mv.fecha_destino] += 1
    fechas_de = {pid: sorted(cs) for pid, cs in mesobj.celdas.items()}
    ahora = ahora_utc()

    def destino(pid: int, f: str, tipo: str) -> Optional[str]:
        futuras = [g for g in fechas_de.get(pid, []) if g > f and mesobj.estado.get((pid, g)) is None]
        if tipo == "epo":
            normales = [g for g in futuras if g not in lab]
            return (normales or futuras or [None])[0]
        # reprogramaciones de hierro aún no recorridas que ya apuntan a una fecha: ocupada
        ocupadas = {m.fecha_destino for m in mesobj.movs
                    if m.paciente_id == pid and m.tipo == "fe" and m.id not in vistos}
        libres = [g for g in futuras if g not in ocupadas
                  and (plan[(pid, g)].fe if (pid, g) in plan else 0) + llega[(pid, g, "fe")] == 0]
        if not libres:
            return None
        return min(libres, key=lambda g: (g in lab, carga_fe[g], g))

    claves = sorted(plan, key=lambda k: (k[1], k[0]))
    for pid, f in claves:
        c = plan[(pid, f)]
        st = mesobj.estado.get((pid, f))
        for tipo in ("epo", "fe"):
            qty = (c.epo if tipo == "epo" else c.fe) + llega[(pid, f, tipo)]
            mv = por_origen.get((pid, f, tipo))
            if st != FALTO or qty <= 0:
                continue
            nombre = mesobj.pacientes[pid].nombre if pid in mesobj.pacientes else f"#{pid}"
            if mv is None:
                dest = destino(pid, f, tipo)
                mv = models.EpoFeMovimiento(mes=mes, paciente_id=pid, tipo=tipo, fecha_origen=f,
                                            fecha_destino=dest, cantidad=qty, activo=True,
                                            creado_por=usuario, creado_en=ahora, actualizado_en=ahora)
                db.add(mv)
                db.flush()
                if dest and tipo == "fe":
                    carga_fe[dest] += 1
                que = f"{qty} jeringa(s) de EPO" if tipo == "epo" else "la dosis de hierro"
                if dest:
                    resumen["reprogramadas"] += 1
                    _auditar(db, mes, "reprogramar", f"{nombre}: no asistió el {f}; {que} pasa al {dest}", usuario, pid)
                else:
                    resumen["sin_destino"] += 1
                    _auditar(db, mes, "sin_destino", f"{nombre}: no asistió el {f}; {que} no tiene sesión libre en el mes",
                             usuario, pid)
            elif mv.cantidad != qty:
                _auditar(db, mes, "ajustar", f"{nombre}: reprogramación del {f} {mv.cantidad}→{qty}", usuario, pid)
                mv.cantidad, mv.actualizado_en = qty, ahora
                resumen["ajustadas"] += 1
            vistos.add(mv.id)
            if mv.fecha_destino:
                llega[(pid, mv.fecha_destino, tipo)] += qty
    for mv in mesobj.movs:
        if mv.id not in vistos:
            mv.activo, mv.actualizado_en = False, ahora
            if mv.tipo == "fe" and mv.fecha_destino:
                carga_fe[mv.fecha_destino] -= 1
            resumen["revertidas"] += 1
            _auditar(db, mes, "revertir", f"Se deshace la reprogramación del {mv.fecha_origen} "
                     f"({mv.tipo.upper()}) al {mv.fecha_destino or '—'}: ya no consta inasistencia", usuario,
                     mv.paciente_id)
    db.flush()
    if auditar_vacio:
        _auditar(db, mes, "recalcular", "Recalcular: " + ", ".join(f"{k} {v}" for k, v in resumen.items()), usuario)
    sincronizar_hojas(db, mes)
    return resumen


# ── Hoja diaria: llenado automático ─────────────────────────────────────────

def valores_dia(db: Session, fecha: str) -> dict[int, tuple[int, int]]:
    """pid → (jeringas, dosis Fe) efectivas ese día, para los pacientes con programación en el mes."""
    mes = mes_de(fecha)
    if not db.query(models.EpoFeMesPaciente.id).filter_by(mes=mes).first():
        return {}
    mesobj = Mes(db, mes)
    ef = mesobj.efectivo()
    return {pid: tuple(ef.get((pid, fecha), (0, 0))) for pid in mesobj.totales}


def _aplicar(r: models.Registro, vals: dict[int, tuple[int, int]]) -> bool:
    persona = r.transitorio_paciente_id or r.paciente_id
    if persona not in vals or r.epo_fe_manual:
        return False
    epo, fe = vals[persona]
    nuevo = (epo, epo > 0, fe > 0)
    if (r.epo_jeringas, bool(r.epo), bool(r.hierro)) == nuevo:
        return False
    r.epo_jeringas, r.epo, r.hierro = nuevo
    return True


def aplicar_a_sesion(db: Session, sesion: models.Sesion) -> int:
    """Llena EPO/Fe de las filas de una hoja ABIERTA desde la programación del mes."""
    if sesion.cerrada:
        return 0
    db.flush()
    vals = valores_dia(db, sesion.fecha)
    if not vals:
        return 0
    return sum(_aplicar(r, vals) for r in db.query(models.Registro).filter_by(sesion_id=sesion.id).all())


def sincronizar_hojas(db: Session, mes: str) -> int:
    n = 0
    for s in db.query(models.Sesion).filter(models.Sesion.fecha.startswith(mes),
                                            models.Sesion.cerrada.is_(False)).all():
        n += aplicar_a_sesion(db, s)
    return n


def tras_cierre(db: Session, fecha: str, usuario: str) -> None:
    """Gancho del cierre / reapertura de una hoja: reprograma el mes si tiene programación."""
    mes = mes_de(fecha)
    if db.query(models.EpoFeMesPaciente.id).filter_by(mes=mes).first():
        recalcular(db, mes, usuario, auditar_vacio=False)


# ── Grilla mensual y CSV ─────────────────────────────────────────────────────

def _iniciales(db: Session) -> dict[str, str]:
    return {normalizar(m.nombre): (m.iniciales or iniciales_medico(m.nombre)) for m in db.query(models.Medico).all()}


def grilla(db: Session, mes: str, hoy: Optional[date] = None) -> dict:
    mesobj = Mes(db, mes)
    hoy = hoy or hoy_local()
    lab = {d.isoformat() for d in mesobj.lab}
    dias = [{"fecha": d.isoformat(), "dia": d.day, "dow": DIA_CORTO[d.weekday()], "lab": d.isoformat() in lab}
            for d in alg.dias_del_mes(mesobj.anio, mesobj.m) if d.weekday() != 6]
    ef = mesobj.efectivo()
    sale = {(mv.paciente_id, mv.fecha_origen, mv.tipo): mv for mv in mesobj.movs}
    llegan: dict[tuple[int, str], list] = defaultdict(list)
    for mv in mesobj.movs:
        if mv.fecha_destino:
            llegan[(mv.paciente_id, mv.fecha_destino)].append(
                {"tipo": mv.tipo, "cantidad": mv.cantidad, "desde": mv.fecha_origen})
    inic = _iniciales(db)
    totales_dia: dict[str, dict] = {d["fecha"]: {"epo_jeringas": 0, "fe": 0} for d in dias}
    filas = []
    for pid, t in mesobj.totales.items():
        p = mesobj.pacientes.get(pid)
        if p is None:
            continue
        celdas = {}
        epo_plan = fe_plan = 0
        avisos = []
        for f, c in sorted(mesobj.celdas.get(pid, {}).items()):
            e, fe = ef.get((pid, f), [0, 0])
            epo_plan += c.epo or 0
            fe_plan += c.fe or 0
            st = mesobj.estado.get((pid, f))
            celdas[f] = {
                "epo": e, "fe": fe, "epo_ui": e * JERINGA_UI, "epo_plan": c.epo or 0, "fe_plan": c.fe or 0,
                "manual": bool(c.manual), "estado": st, "lab": f in lab,
                "llega": llegan.get((pid, f), []),
                "sale": [{"tipo": tp, "cantidad": mv.cantidad, "hacia": mv.fecha_destino}
                         for tp in ("epo", "fe") if (mv := sale.get((pid, f, tp)))],
            }
            if f in totales_dia and st != FALTO:
                totales_dia[f]["epo_jeringas"] += e
                totales_dia[f]["fe"] += fe
            if e > alg.EPO_MAX_NORMAL:
                avisos.append(f"{f[8:]}: {e} jeringas ({e * JERINGA_UI:,} UI)".replace(",", "."))
            if f in lab and (e or fe) and st is None:
                avisos.append(f"{f[8:]}: dosis en día de laboratorio (no cabía en otro día)")
        if epo_plan != (t.epo_jeringas or 0):
            avisos.append(f"EPO programada {epo_plan} de {t.epo_jeringas} jeringas")
        if fe_plan != (t.fe_dosis or 0):
            avisos.append(f"Fe programado {fe_plan} de {t.fe_dosis} dosis")
        for mv in mesobj.movs:
            if mv.paciente_id == pid and not mv.fecha_destino:
                avisos.append(f"Pendiente sin sesión: {mv.cantidad} {'jeringa(s) EPO' if mv.tipo == 'epo' else 'dosis Fe'}"
                              f" del {mv.fecha_origen[8:]}")
        filas.append({
            "paciente_id": pid, "nombre": p.nombre, "cedula": p.cedula, "turno": p.turno,
            "estacion": p.estacion, "cama": p.cama, "dias": p.dias, "medico": p.medico or "",
            "iniciales": inic.get(normalizar(p.medico), iniciales_medico(p.medico or "")) if p.medico else "",
            "activo": p.activo is True and p.archivado_en is None,
            "epo_mes": t.epo_jeringas or 0, "fe_mes": t.fe_dosis or 0,
            "epo_programada": epo_plan, "fe_programado": fe_plan,
            "celdas": celdas, "avisos": avisos,
        })
    orden_turno = {"M": 0, "T": 1, "N": 2}
    filas.sort(key=lambda r: (orden_turno.get(r["turno"], 9), r["estacion"] or 0, r["cama"] or 0, r["nombre"]))
    activos_sin = [p for p in consulta_activos(db).all() if p.id not in mesobj.totales]
    audit = (db.query(models.EpoFeAuditoria).filter_by(mes=mes)
             .order_by(models.EpoFeAuditoria.id.desc()).limit(50).all())
    return {
        "mes": mes, "generado": mesobj.generado, "dias": dias,
        "dias_lab": sorted(lab), "dias_lab_por_defecto": mesobj.lab_defecto,
        "filas": filas, "totales_dia": totales_dia,
        "sin_programacion": len([p for p in activos_sin if dias_semana(p)]),
        "sin_dias": len([p for p in activos_sin if not dias_semana(p)]),
        "puede_borrar": (mesobj.anio, mesobj.m) < (hoy.year, hoy.month),
        "jeringa_ui": JERINGA_UI,
        "auditoria": [{"accion": a.accion, "detalle": a.detalle, "usuario": a.usuario,
                       "paciente_id": a.paciente_id,
                       "creado_en": a.creado_en.isoformat(timespec="minutes")} for a in audit],
    }


def texto_celda(c: Optional[dict]) -> str:
    if not c:
        return ""
    if c["estado"] == FALTO:
        return "NA"
    partes = []
    if c["epo"]:
        partes.append(f"{c['epo_ui']:,}".replace(",", "."))
    if c["fe"]:
        partes.append("Fe")
    return "+".join(partes) or "·"


def a_csv(g: dict) -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\r\n")
    w.writerow(["Paciente", "Cédula", "Nefrólogo", "Días", "EPO del mes (jeringas)", "Fe del mes"]
               + [f"{d['dow']} {d['dia']}" + (" LAB" if d["lab"] else "") for d in g["dias"]])
    for f in g["filas"]:
        w.writerow([f["nombre"], f["cedula"], f["iniciales"], f["dias"] or "", f["epo_mes"], f["fe_mes"]]
                   + [texto_celda(f["celdas"].get(d["fecha"])) for d in g["dias"]])
    w.writerow(["TOTAL DÍA (jeringas EPO / Fe)", "", "", "", "", ""]
               + [f"{g['totales_dia'][d['fecha']]['epo_jeringas']} / {g['totales_dia'][d['fecha']]['fe']}"
                  for d in g["dias"]])
    return out.getvalue()
