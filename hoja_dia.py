"""
Hoja de un día = ubicación base del paciente + cambios de un día (R2 / R7).

- La **ubicación base** (habitual) vive en `Paciente.turno/estacion/cama` y los
  días de diálisis en `Paciente.dias` (LMV o MJS/TJS).
- Los **cambios de un día** viven en `AsignacionDia` (una fila por paciente y
  fecha) y solo afectan esa fecha. El jueves la hoja vuelve a la base.
- Un **cambio permanente** actualiza la base del paciente y borra el cambio del
  día (ya no hace falta).
- Cada `Registro` guarda la ubicación que tuvo en su sesión (`estacion/cama`),
  así un cambio permanente no altera retroactivamente las hojas pasadas.

Todas las funciones de este módulo trabajan dentro de la transacción de la
`Session` recibida: no hacen commit. Si algo no cuadra lanzan `Conflicto` y el
llamador hace rollback.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session, joinedload

import models
from services.pacientes import consulta_activos, esta_activo, esta_archivado

TURNOS = ("M", "T", "N")
TURNO_NOMBRE = {"M": "Mañana", "T": "Tarde", "N": "Noche"}
ESTACIONES = (1, 2, 3)
CAMAS_POR_ESTACION = 16
DIA_NOMBRE = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

# Grupos de días de diálisis. «MJS» es como lo escribe la unidad; «TJS» es el
# código histórico de la app (Tuesday/Thursday/Saturday). Ambos son el mismo grupo.
DIAS_GRUPO = {"LMV": {0, 2, 4}, "MJS": {1, 3, 5}, "TJS": {1, 3, 5}}
TODA_LA_SEMANA = {0, 1, 2, 3, 4, 5}


class Conflicto(Exception):
    """Cambio imposible (cama ocupada, hoja cerrada…). El mensaje es para el usuario."""


# ── Calendario ────────────────────────────────────────────────────────────────

def parse_fecha(fecha: str) -> date:
    try:
        return date.fromisoformat(fecha)
    except (TypeError, ValueError):
        raise Conflicto(f"Fecha inválida: {fecha!r} (use AAAA-MM-DD)") from None


def proximo_dia_dialisis(desde: date) -> date:
    """Siguiente día de diálisis: el día siguiente saltando domingos (sábado → lunes)."""
    d = desde + timedelta(days=1)
    while d.weekday() == 6:
        d += timedelta(days=1)
    return d


def dias_semana(dias: str | None) -> set[int] | None:
    """Días de la semana (0=lunes) del grupo del paciente; None si no está configurado."""
    if not dias:
        return None
    return DIAS_GRUPO.get(dias.strip().upper())


def le_toca(p: models.Paciente, f: date) -> bool:
    """¿Le toca diálisis ese día? Sin días configurados se asume que sí (compatibilidad)."""
    ws = dias_semana(p.dias)
    return ws is None or f.weekday() in ws


def grupo_del_dia(f: date) -> str | None:
    return {0: "LMV", 2: "LMV", 4: "LMV", 1: "MJS", 3: "MJS", 5: "MJS"}.get(f.weekday())


def _dias_se_cruzan(a: str | None, b: str | None) -> bool:
    return bool((dias_semana(a) or TODA_LA_SEMANA) & (dias_semana(b) or TODA_LA_SEMANA))


# ── Filtro de pacientes activos ───────────────────────────────────────────────
# R10: el criterio activo/inactivo (hospitalizado, otro motivo) vive en
# services.pacientes; aquí solo se reutiliza. Es el único punto que decide quién
# entra a la composición del día y a la programación automática.
# R13: un paciente ARCHIVADO cuenta como inactivo en todo este módulo (no entra a
# la hoja, sus cambios de un día no cuentan y no se puede programar).

def filtrar_activos(query):
    """Restringe una Query de Paciente a los activos (mismo criterio que consulta_activos)."""
    return query.filter(models.Paciente.activo.is_(True), models.Paciente.archivado_en.is_(None))


def _motivo_fuera(p: models.Paciente) -> str:
    return "Archivado" if esta_archivado(p) else "Inactivo"


def es_activo(p: models.Paciente) -> bool:
    return esta_activo(p)


# ── Composición de la hoja ────────────────────────────────────────────────────

@dataclass
class Puesto:
    paciente: models.Paciente
    estacion: int
    cama: int
    tipo: str                                   # base | mover | transitorio | reemplazo
    asignacion: models.AsignacionDia | None = None


@dataclass
class Hoja:
    fecha: str
    turno: str
    puestos: list[Puesto] = field(default_factory=list)
    # (paciente reemplazado, asignación del suplente, estacion, cama)
    desplazados: list[tuple] = field(default_factory=list)
    excluidos: list[tuple] = field(default_factory=list)   # (paciente, motivo)
    base_ids: set[int] = field(default_factory=set)
    programacion: dict = field(default_factory=dict)       # paciente_id → Programacion

    @property
    def programado(self) -> bool:
        return bool(self.programacion)

    def puesto_de(self, paciente_id: int) -> Puesto | None:
        return next((p for p in self.puestos if p.paciente.id == paciente_id), None)

    def ocupante(self, estacion: int, cama: int, excluir: int | None = None) -> Puesto | None:
        return next((p for p in self.puestos
                     if p.estacion == estacion and p.cama == cama and p.paciente.id != excluir), None)

    def conflictos(self) -> list[dict]:
        por_cama: dict[tuple, list[Puesto]] = {}
        for p in self.puestos:
            por_cama.setdefault((p.estacion, p.cama), []).append(p)
        return [{"estacion": e, "cama": c, "pacientes": ps}
                for (e, c), ps in sorted(por_cama.items()) if len(ps) > 1]


def _asignaciones_fecha(db: Session, fecha: str) -> list[models.AsignacionDia]:
    return (db.query(models.AsignacionDia)
            .options(joinedload(models.AsignacionDia.paciente),
                     joinedload(models.AsignacionDia.reemplaza))
            .filter_by(fecha=fecha).all())


def componer(db: Session, fecha: str, turno: str) -> Hoja:
    """Hoja de `fecha`/`turno`: pacientes base del día + cambios de un día de esa fecha."""
    f = parse_fecha(fecha)
    hoja = Hoja(fecha=fecha, turno=turno)

    progs = (db.query(models.Programacion)
             .options(joinedload(models.Programacion.paciente))
             .filter_by(fecha=fecha, turno=turno).all())
    hoja.programacion = {pr.paciente_id: pr for pr in progs}

    naturales = [p for p in consulta_activos(db, turno=turno).all() if le_toca(p, f)]
    if progs:
        # Hay programación explícita para ese día: manda la lista guardada.
        base = [pr.paciente for pr in progs if pr.paciente and es_activo(pr.paciente)]
        hoja.excluidos += [(p, "No incluido en la programación") for p in naturales
                           if p.id not in hoja.programacion]
    else:
        base = naturales
    hoja.base_ids = {p.id for p in base}

    asigs = _asignaciones_fecha(db, fecha)
    # R10: los cambios de un día de un paciente que luego quedó inactivo no cuentan
    # (si era suplente, el paciente reemplazado vuelve a su cama).
    inactivos = [a for a in asigs if not esta_activo(a.paciente)]
    asigs = [a for a in asigs if esta_activo(a.paciente)]
    hoja.excluidos += [(a.paciente, _motivo_fuera(a.paciente)) for a in inactivos if a.turno == turno]
    por_paciente = {a.paciente_id: a for a in asigs}
    del_turno = [a for a in asigs if a.turno == turno]
    # Un reemplazo cuyo reemplazado quedó inactivo o archivado: el suplente ocupa la
    # cama como un transitorio (no se crea fila «H» para quien ya no está en la unidad).
    reemplazos = {a.reemplaza_paciente_id: a for a in del_turno
                  if a.tipo == "reemplazo" and a.reemplaza is not None and esta_activo(a.reemplaza)}

    for p in base:
        a = por_paciente.get(p.id)
        if a and a.turno != turno:
            hoja.excluidos.append((p, f"Ese día va en el turno {TURNO_NOMBRE.get(a.turno, a.turno)}"))
        elif p.id in reemplazos:
            sup = reemplazos[p.id]
            hoja.desplazados.append((p, sup, sup.estacion, sup.cama))
        elif not a:
            hoja.puestos.append(Puesto(p, p.estacion, p.cama, "base"))

    for a in del_turno:
        if a.paciente_id in reemplazos:            # su cama la ocupa un suplente
            sup = reemplazos[a.paciente_id]
            if a.paciente_id not in hoja.base_ids:
                hoja.desplazados.append((a.paciente, sup, sup.estacion, sup.cama))
            continue
        tipo = a.tipo
        if tipo == "reemplazo" and a.reemplaza_paciente_id not in reemplazos:
            tipo = "transitorio"                   # su reemplazado ya no está activo
        hoja.puestos.append(Puesto(a.paciente, a.estacion, a.cama, tipo, a))

    for a in reemplazos.values():                  # reemplazado que no estaba en la base
        q = a.reemplaza
        if q and q.id not in hoja.base_ids and q.id not in por_paciente:
            hoja.desplazados.append((q, a, a.estacion, a.cama))

    hoja.puestos.sort(key=lambda p: (p.estacion, p.cama, p.paciente.nombre))
    return hoja


# ── Creación y sincronización de la sesión (hoja principal) ───────────────────

def _flags(hoja: Hoja, paciente_id: int) -> tuple[bool, bool]:
    pr = hoja.programacion.get(paciente_id)
    return (bool(pr.epo_programado), bool(pr.hierro_programado)) if pr else (False, False)


def crear_registros(db: Session, sesion: models.Sesion) -> None:
    """Crea los registros de una sesión nueva a partir de la hoja compuesta."""
    hoja = componer(db, sesion.fecha, sesion.turno)
    for pu in hoja.puestos:
        if pu.tipo == "reemplazo":
            continue                              # el suplente va en el registro del reemplazado
        epo, fe = _flags(hoja, pu.paciente.id)
        db.add(models.Registro(sesion_id=sesion.id, paciente_id=pu.paciente.id,
                               epo=epo, hierro=fe, estacion=pu.estacion, cama=pu.cama))
    for q, sup, e, c in hoja.desplazados:
        epo, fe = _flags(hoja, sup.paciente_id)
        db.add(models.Registro(sesion_id=sesion.id, paciente_id=q.id, asistencia="H",
                               transitorio_paciente_id=sup.paciente_id,
                               transitorio_nombre=sup.paciente.nombre,
                               epo=epo, hierro=fe, estacion=e, cama=c))


def _tiene_datos(r: models.Registro) -> bool:
    return any([r.asistencia, r.peso_entrada is not None, r.peso_salida is not None,
                r.ktv is not None, (r.observaciones or "").strip(), r.transitorio_paciente_id,
                (r.transitorio_nombre or "").strip()])


def _quitar_registro(db: Session, r: models.Registro) -> None:
    if _tiene_datos(r):
        nombre = r.paciente.nombre if r.paciente else f"#{r.paciente_id}"
        raise Conflicto(f"{nombre} ya tiene datos anotados en la hoja abierta de ese turno; "
                        "no se puede quitar de ella.")
    db.delete(r)


def sesion_de(db: Session, fecha: str, turno: str) -> models.Sesion | None:
    return db.query(models.Sesion).filter_by(fecha=fecha, turno=turno).first()


def exigir_editable(db: Session, fecha: str, turnos) -> None:
    for t in set(turnos):
        s = sesion_de(db, fecha, t)
        if s and s.cerrada:
            raise Conflicto(f"La hoja del {fecha} turno {TURNO_NOMBRE.get(t, t)} ya está cerrada; "
                            "no se puede cambiar.")


def sincronizar_sesion(db: Session, fecha: str, turno: str, paciente_ids: set[int]) -> None:
    """Si la sesión de ese día ya está abierta, le aplica el cambio (solo a los pacientes tocados)."""
    s = sesion_de(db, fecha, turno)
    if not s:
        return
    db.flush()
    hoja = componer(db, fecha, turno)
    regs = {r.paciente_id: r for r in s.registros}
    desplazado = {q.id: (sup, e, c) for q, sup, e, c in hoja.desplazados}
    suplentes = {sup.paciente_id for _, sup, _, _ in hoja.desplazados}

    for pid in paciente_ids:
        r = regs.get(pid)
        if pid in desplazado:
            sup, e, c = desplazado[pid]
            if r is None:
                r = models.Registro(sesion_id=s.id, paciente_id=pid)
                db.add(r)
            r.asistencia = "H"
            r.transitorio_paciente_id = sup.paciente_id
            r.transitorio_nombre = sup.paciente.nombre
            r.estacion, r.cama = e, c
        elif pid in suplentes:
            if r is not None:
                _quitar_registro(db, r)
        elif (pu := hoja.puesto_de(pid)) is not None:
            if r is None:
                epo, fe = _flags(hoja, pid)
                r = models.Registro(sesion_id=s.id, paciente_id=pid, epo=epo, hierro=fe)
                db.add(r)
            elif r.asistencia == "H" and r.transitorio_paciente_id in paciente_ids:
                # Se deshizo el reemplazo programado: vuelve a su cama sin marcar.
                r.asistencia = None
                r.transitorio_paciente_id = None
                r.transitorio_nombre = None
                r.transitorio_asistencia = None
            r.estacion, r.cama = pu.estacion, pu.cama
        elif r is not None:
            _quitar_registro(db, r)


def ubicacion_registro(r: models.Registro) -> tuple[int | None, int | None]:
    """Ubicación del registro en su sesión; los registros antiguos usan la base del paciente."""
    if r.estacion is not None and r.cama is not None:
        return r.estacion, r.cama
    p = r.paciente
    return (p.estacion, p.cama) if p else (None, None)


def con_ubicacion(out: dict, r: models.Registro) -> dict:
    """Añade al registro serializado la ubicación de ESE día.

    `paciente.estacion/cama` pasan a ser la ubicación en la sesión (es lo que la
    hoja dibuja) y la habitual queda en `paciente.estacion_base/cama_base`.
    """
    e, c = ubicacion_registro(r)
    out["estacion"], out["cama"] = e, c
    if out.get("paciente") and r.paciente:
        out["paciente"] = {**out["paciente"], "estacion": e, "cama": c,
                           "estacion_base": r.paciente.estacion, "cama_base": r.paciente.cama}
    return out


# ── Cambios de un día ─────────────────────────────────────────────────────────

def _validar_ubicacion(turno: str, estacion: int, cama: int) -> None:
    if turno not in TURNOS:
        raise Conflicto("Turno inválido (use M, T o N)")
    if estacion not in ESTACIONES:
        raise Conflicto("Estación inválida (1, 2 o 3)")
    if not 1 <= cama <= CAMAS_POR_ESTACION:
        raise Conflicto(f"Cama inválida (1 a {CAMAS_POR_ESTACION} por estación)")


def cama_global(estacion: int, cama: int) -> int:
    return cama + (estacion - 1) * CAMAS_POR_ESTACION


def _claves_conflicto(hoja: Hoja) -> set:
    return {(c["estacion"], c["cama"], frozenset(p.paciente.id for p in c["pacientes"]))
            for c in hoja.conflictos()}


class _Cambio:
    """Contexto de una operación: guarda los conflictos previos para detectar los nuevos."""

    def __init__(self, db: Session, fecha: str, turnos):
        self.db, self.fecha, self.turnos = db, fecha, set(turnos)
        exigir_editable(db, fecha, self.turnos)
        self.antes = {t: _claves_conflicto(componer(db, fecha, t)) for t in self.turnos}
        self.tocados: set[int] = set()

    def cerrar(self) -> None:
        self.db.flush()
        for t in self.turnos:
            hoja = componer(self.db, self.fecha, t)
            for c in hoja.conflictos():
                clave = (c["estacion"], c["cama"], frozenset(p.paciente.id for p in c["pacientes"]))
                if clave not in self.antes[t]:
                    nombres = " y ".join(p.paciente.nombre for p in c["pacientes"])
                    raise Conflicto(f"Conflicto: {nombres} quedarían en la misma cama "
                                    f"{cama_global(c['estacion'], c['cama'])} "
                                    f"({TURNO_NOMBRE[t]}, {self.fecha}).")
        for t in self.turnos:
            sincronizar_sesion(self.db, self.fecha, t, self.tocados)


def _asig(db: Session, fecha: str, paciente_id: int) -> models.AsignacionDia | None:
    return db.query(models.AsignacionDia).filter_by(fecha=fecha, paciente_id=paciente_id).first()


def _turnos_afectados(db: Session, fecha: str, p: models.Paciente, turno: str) -> set[str]:
    turnos = {turno, p.turno}
    a = _asig(db, fecha, p.id)
    if a:
        turnos.add(a.turno)
    return {t for t in turnos if t in TURNOS}


def _poner(db: Session, p: models.Paciente, fecha: str, turno: str, estacion: int, cama: int,
           usuario: str, grupo: str | None = None) -> None:
    """Deja a `p` ese día en turno/estación/cama. Si coincide con su base, borra el cambio."""
    base_ids = componer(db, fecha, turno).base_ids
    en_base = p.id in base_ids
    a = _asig(db, fecha, p.id)
    if en_base and (estacion, cama) == (p.estacion, p.cama):
        if a:
            db.delete(a)
            db.flush()
        return
    if a is None:
        a = models.AsignacionDia(fecha=fecha, paciente_id=p.id)
        db.add(a)
    a.turno, a.estacion, a.cama = turno, estacion, cama
    a.tipo = "mover" if en_base else "transitorio"
    a.reemplaza_paciente_id = None
    a.grupo = grupo
    a.creado_por, a.creado_en = usuario, datetime.now()
    db.flush()


def _paciente(db: Session, paciente_id: int) -> models.Paciente:
    p = db.get(models.Paciente, paciente_id)
    if not p:
        raise Conflicto(f"Paciente {paciente_id} no encontrado")
    return p


def _exigir_activo(p: models.Paciente) -> None:
    """R10: un paciente inactivo no se programa (ni cambio de un día ni suplente)."""
    if esta_archivado(p):
        raise Conflicto(f"{p.nombre} está archivado; restáurelo desde «Archivados» para programarlo.")
    if not esta_activo(p):
        raise Conflicto(f"{p.nombre} está inactivo; reactívelo en Pacientes para programarlo.")


def _soltar_grupo(db: Session, fecha: str, paciente_id: int) -> None:
    """Editar un lado de un intercambio lo independiza del otro."""
    a = _asig(db, fecha, paciente_id)
    if a and a.grupo:
        for otro in db.query(models.AsignacionDia).filter_by(fecha=fecha, grupo=a.grupo).all():
            otro.grupo = None


def mover(db: Session, fecha: str, turno: str, paciente_id: int, estacion: int, cama: int,
          usuario: str, intercambiar: bool = False) -> list[int]:
    """Mueve a un paciente a otra cama ese día. Devuelve los ids de los cambios creados."""
    _validar_ubicacion(turno, estacion, cama)
    p = _paciente(db, paciente_id)
    _exigir_activo(p)
    hoja = componer(db, fecha, turno)
    if any(q.id == p.id for q, *_ in hoja.desplazados):
        raise Conflicto(f"{p.nombre} fue reemplazado ese día; deshaga el reemplazo primero.")

    actual = hoja.puesto_de(p.id)
    if actual and (actual.estacion, actual.cama) == (estacion, cama):
        return [actual.asignacion.id] if actual.asignacion else []

    ocupa = hoja.ocupante(estacion, cama, excluir=p.id)
    turnos = _turnos_afectados(db, fecha, p, turno)
    if ocupa:
        turnos |= _turnos_afectados(db, fecha, ocupa.paciente, turno)
    cambio = _Cambio(db, fecha, turnos)
    cambio.tocados.add(p.id)
    if actual and actual.asignacion and actual.asignacion.reemplaza_paciente_id:
        cambio.tocados.add(actual.asignacion.reemplaza_paciente_id)

    if ocupa:
        if not intercambiar:
            raise Conflicto(f"La cama {cama_global(estacion, cama)} ya está ocupada ese día por "
                            f"{ocupa.paciente.nombre}. Use «intercambiar» o elija otra cama.")
        if actual is None:
            raise Conflicto("Para intercambiar, los dos pacientes deben estar en la hoja de ese turno.")
        if "reemplazo" in (actual.tipo, ocupa.tipo):
            raise Conflicto("No se puede intercambiar con un reemplazo; deshágalo primero.")
        _soltar_grupo(db, fecha, p.id)
        _soltar_grupo(db, fecha, ocupa.paciente.id)
        grupo = uuid.uuid4().hex[:12]
        _poner(db, p, fecha, turno, estacion, cama, usuario, grupo)
        _poner(db, ocupa.paciente, fecha, turno, actual.estacion, actual.cama, usuario, grupo)
        cambio.tocados.add(ocupa.paciente.id)
        # Si uno de los dos volvió a su base, el otro ya no forma pareja.
        vivos = db.query(models.AsignacionDia).filter_by(fecha=fecha, grupo=grupo).all()
        if len(vivos) == 1:
            vivos[0].grupo = None
    else:
        _soltar_grupo(db, fecha, p.id)
        _poner(db, p, fecha, turno, estacion, cama, usuario)

    cambio.cerrar()
    return [a.id for a in db.query(models.AsignacionDia).filter(
        models.AsignacionDia.fecha == fecha,
        models.AsignacionDia.paciente_id.in_(cambio.tocados)).all()]


def reemplazar(db: Session, fecha: str, turno: str, paciente_id: int, reemplaza_id: int,
               usuario: str) -> list[int]:
    """`paciente_id` ocupa ese día la cama de `reemplaza_id`, que no viene."""
    if turno not in TURNOS:
        raise Conflicto("Turno inválido (use M, T o N)")
    if paciente_id == reemplaza_id:
        raise Conflicto("Un paciente no puede reemplazarse a sí mismo.")
    p = _paciente(db, paciente_id)
    q = _paciente(db, reemplaza_id)
    _exigir_activo(p)
    hoja = componer(db, fecha, turno)
    pq = hoja.puesto_de(q.id)
    if pq is None:
        raise Conflicto(f"{q.nombre} no está en la hoja de ese día y turno.")
    if pq.tipo in ("reemplazo", "transitorio"):
        raise Conflicto(f"{q.nombre} ya es un cambio de ese día; deshágalo en lugar de reemplazarlo.")
    if any(x.id == p.id for x, *_ in hoja.desplazados):
        raise Conflicto(f"{p.nombre} fue reemplazado ese día; no puede ser suplente.")

    cambio = _Cambio(db, fecha, _turnos_afectados(db, fecha, p, turno))
    cambio.tocados |= {p.id, q.id}
    prev = _asig(db, fecha, p.id)
    if prev and prev.reemplaza_paciente_id:
        cambio.tocados.add(prev.reemplaza_paciente_id)
    _soltar_grupo(db, fecha, p.id)
    a = prev or models.AsignacionDia(fecha=fecha, paciente_id=p.id)
    if prev is None:
        db.add(a)
    a.turno, a.estacion, a.cama, a.tipo = turno, pq.estacion, pq.cama, "reemplazo"
    a.reemplaza_paciente_id, a.grupo = q.id, None
    a.creado_por, a.creado_en = usuario, datetime.now()
    cambio.cerrar()
    return [a.id]


def _grupo_de(db: Session, a: models.AsignacionDia) -> list[models.AsignacionDia]:
    if not a.grupo:
        return [a]
    return db.query(models.AsignacionDia).filter_by(fecha=a.fecha, grupo=a.grupo).all()


def obtener(db: Session, asignacion_id: int) -> models.AsignacionDia:
    a = db.get(models.AsignacionDia, asignacion_id)
    if not a:
        raise Conflicto("El cambio ya no existe (quizá se deshizo antes).")
    return a


def deshacer(db: Session, asignacion_id: int) -> tuple[str, str]:
    """Borra un cambio de un día (y su pareja si fue intercambio). Devuelve (fecha, turno)."""
    a = obtener(db, asignacion_id)
    fecha, turno = a.fecha, a.turno
    miembros = _grupo_de(db, a)
    turnos = {turno}
    for m in miembros:
        turnos |= _turnos_afectados(db, fecha, m.paciente, m.turno)
    cambio = _Cambio(db, fecha, turnos)
    for m in miembros:
        cambio.tocados.add(m.paciente_id)
        if m.reemplaza_paciente_id:
            cambio.tocados.add(m.reemplaza_paciente_id)
        # Un transitorio deshecho no debe quedarse «colgado» en la lista programada.
        f = parse_fecha(fecha)
        p = m.paciente
        if not (p.turno == m.turno and le_toca(p, f)):
            db.query(models.Programacion).filter_by(
                fecha=fecha, turno=m.turno, paciente_id=p.id).delete()
        db.delete(m)
    try:
        cambio.cerrar()
    except Conflicto as e:
        raise Conflicto(f"No se puede deshacer: {e}") from None
    return fecha, turno


def _snapshot_historial(db: Session, paciente_ids) -> None:
    """Fija la ubicación de los registros antiguos (sin foto) antes de cambiar la base."""
    for pid in paciente_ids:
        p = db.get(models.Paciente, pid)
        (db.query(models.Registro)
         .filter(models.Registro.paciente_id == pid, models.Registro.estacion.is_(None))
         .update({models.Registro.estacion: p.estacion, models.Registro.cama: p.cama},
                 synchronize_session=False))


def hacer_permanente(db: Session, asignacion_id: int) -> tuple[str, str]:
    """Convierte un cambio de un día en la nueva ubicación habitual del paciente."""
    a = obtener(db, asignacion_id)
    if a.tipo == "reemplazo":
        raise Conflicto("Un reemplazo es solo por un día; para dejar al paciente en esa cama "
                        "muévalo con «Cambio permanente».")
    fecha, turno = a.fecha, a.turno
    miembros = _grupo_de(db, a)
    exigir_editable(db, fecha, {m.turno for m in miembros})
    ids = {m.paciente_id for m in miembros}

    for m in miembros:
        p = m.paciente
        choques = [o for o in filtrar_activos(db.query(models.Paciente).filter(
                       models.Paciente.turno == m.turno, models.Paciente.estacion == m.estacion,
                       models.Paciente.cama == m.cama, models.Paciente.id.notin_(ids))).all()
                   if _dias_se_cruzan(o.dias, p.dias)]
        if choques:
            raise Conflicto(f"No se puede hacer permanente: la cama {cama_global(m.estacion, m.cama)} "
                            f"({TURNO_NOMBRE[m.turno]}) es la habitual de {choques[0].nombre}.")

    _snapshot_historial(db, ids)
    for m in miembros:
        p = m.paciente
        turno_viejo = p.turno
        p.turno, p.estacion, p.cama = m.turno, m.estacion, m.cama
        if turno_viejo != m.turno:
            # Programación futura ya generada: sigue al paciente a su nuevo turno.
            for pr in db.query(models.Programacion).filter(
                    models.Programacion.paciente_id == p.id,
                    models.Programacion.turno == turno_viejo,
                    models.Programacion.fecha >= fecha).all():
                if not db.query(models.Programacion).filter_by(
                        fecha=pr.fecha, turno=m.turno, paciente_id=p.id).first():
                    pr.turno = m.turno
        hay_prog = db.query(models.Programacion).filter_by(fecha=fecha, turno=m.turno).first()
        if hay_prog and not db.query(models.Programacion).filter_by(
                fecha=fecha, turno=m.turno, paciente_id=p.id).first():
            db.add(models.Programacion(fecha=fecha, turno=m.turno, paciente_id=p.id))
        db.delete(m)
    db.flush()
    return fecha, turno
