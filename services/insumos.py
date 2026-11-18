"""
Pedido de insumos (R5/R6): composición con la BD. Las reglas puras están en
services/insumos_reglas.py.

El pedido que se hace el día ``F`` (fecha del pedido) tiene cuatro secciones:

* **pedido**      insumos de las sesiones del PRÓXIMO día de diálisis
                  ``D = hoja_dia.proximo_dia_dialisis(F)`` (sin domingos; sábado → lunes),
                  según la hoja compuesta de cada turno (base + cambios de un día).
                  Solo pacientes activos; los marcados «adicional» no van aquí.
* **adicional**   pacientes adicionales que LLEGARON el día ``F`` (asistencia A o peso
                  de entrada): paciente con ``adicional`` o fila de la hoja marcada como
                  adicional solo ese día. Se cargan al pedido de HOY, no al de mañana.
* **devolucion**  de lo que ya se pidió para ``F`` (pedido confirmado cuya
                  ``fecha_sesiones`` es ``F``; si no hay, se recalcula la hoja de ``F``),
                  los pacientes que NO asistieron (asistencia ≠ A) y sin peso de entrada.
* **revisar**     datos que no cuadran y no se deciden solos: A sin peso, peso sin A,
                  pedido sin fila en la hoja, asistió sin estar en el pedido, calibre o
                  filtro faltante… No suman en los totales.

Al confirmar se guarda una foto (``pedido_insumos`` + items): las ediciones
posteriores de pacientes o reglas no cambian un pedido ya enviado.
"""
from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from sqlalchemy.orm import Session, joinedload

import hoja_dia as hd
import models
from services import insumos_reglas as ir
from services.bloqueo_mes import exigir_abierto
from services.pacientes import esta_activo, etiqueta_acceso

SECCIONES = ("pedido", "adicional", "devolucion", "revisar")
SECCION_NOMBRE = {"pedido": "Pedido", "adicional": "Adicionales",
                  "devolucion": "Devolución", "revisar": "Revisar"}
CLAVE_REGLAS = "reglas"
SEP_ALERTAS = " · "


class ErrorPedido(Exception):
    """Operación imposible (ya confirmado, fecha inválida…). Mensaje para el usuario."""


# ── Quién cuenta ──────────────────────────────────────────────────────────────

def cuenta_para_pedido(p: models.Paciente | None) -> bool:
    """Único punto que decide si un paciente entra al pedido.

    R10/R13: solo activos y NO archivados. ``services.pacientes.esta_activo`` y
    ``consulta_activos`` (que usa hoja_dia.componer) ya excluyen a los archivados,
    así un paciente archivado sale del pedido futuro sin confirmar; los pedidos
    confirmados son una foto y no cambian.
    """
    return p is not None and esta_activo(p)


def es_adicional(p: models.Paciente | None) -> bool:
    return bool(p is not None and p.adicional)


# ── Reglas activas ────────────────────────────────────────────────────────────

def reglas_guardadas(db: Session) -> models.InsumosConfig | None:
    return db.query(models.InsumosConfig).filter_by(clave=CLAVE_REGLAS).first()


def reglas_activas(db: Session) -> ir.Reglas:
    fila = reglas_guardadas(db)
    if fila:
        try:
            return ir.validar(json.loads(fila.contenido))
        except Exception:   # JSON dañado a mano en la BD: no tumbar la pantalla
            pass
    return ir.cargar_por_defecto()


def guardar_reglas(db: Session, datos: dict, usuario: str) -> ir.Reglas:
    reglas = ir.validar(datos)
    fila = reglas_guardadas(db) or models.InsumosConfig(clave=CLAVE_REGLAS)
    fila.contenido = json.dumps(reglas.model_dump(exclude_none=True), ensure_ascii=False, indent=2)
    fila.actualizado_en, fila.actualizado_por = datetime.now(), usuario
    db.add(fila)
    return reglas


def restaurar_reglas(db: Session) -> None:
    fila = reglas_guardadas(db)
    if fila:
        db.delete(fila)


# ── Estructura del pedido ─────────────────────────────────────────────────────

@dataclass
class Fila:
    seccion: str
    fecha_sesion: str
    paciente_id: Optional[int]
    nombre: str
    cedula: str = ""
    turno: Optional[str] = None
    estacion: Optional[int] = None
    cama: Optional[int] = None
    acceso: str = "—"
    lineas: list[ir.Linea] = field(default_factory=list)
    alertas: list[str] = field(default_factory=list)
    motivo: Optional[str] = None            # devolución / revisar: por qué está aquí
    asistencia: Optional[str] = None
    peso_entrada: Optional[float] = None
    tipo: Optional[str] = None              # base | mover | transitorio | reemplazo | adicional…

    @property
    def cama_global(self) -> Optional[int]:
        if self.estacion is None or self.cama is None:
            return None
        return hd.cama_global(self.estacion, self.cama)

    def como_dict(self) -> dict:
        return {"seccion": self.seccion, "fecha_sesion": self.fecha_sesion,
                "paciente_id": self.paciente_id, "nombre": self.nombre, "cedula": self.cedula,
                "turno": self.turno, "estacion": self.estacion, "cama": self.cama,
                "cama_global": self.cama_global, "acceso": self.acceso,
                "items": [li.como_dict() for li in self.lineas], "alertas": list(self.alertas),
                "motivo": self.motivo, "asistencia": self.asistencia,
                "peso_entrada": self.peso_entrada, "tipo": self.tipo}


def datos_paciente(p: models.Paciente, turno: Optional[str] = None,
                   registro: models.Registro | None = None) -> ir.DatosPaciente:
    """Datos para las reglas. El citrato / heparina sódica marcados en la fila de
    la hoja de ese día también cuentan (además de los del paciente)."""
    return ir.DatosPaciente(
        acceso=p.acceso, calibre=p.acceso_calibre, filtro=p.tipo_filtro,
        citrato=bool(p.citrato or (registro is not None and registro.citrato)),
        heparina_sodica=bool(p.heparina_sodica or (registro is not None and registro.heparina_sodica)),
        sitio=p.acceso_sitio, estado_fav=p.acceso_estado, turno=turno or p.turno)


def _fila(seccion: str, fecha: str, p: models.Paciente, turno, estacion, cama, reglas: ir.Reglas,
          registro: models.Registro | None = None, **extra) -> Fila:
    res = ir.calcular(datos_paciente(p, turno, registro), hd.parse_fecha(fecha), reglas)
    return Fila(seccion=seccion, fecha_sesion=fecha, paciente_id=p.id, nombre=p.nombre,
                cedula=p.cedula or "", turno=turno, estacion=estacion, cama=cama,
                acceso=etiqueta_acceso(p), lineas=res.lineas, alertas=res.alertas, **extra)


# ── Sección «pedido»: próximo día de diálisis ─────────────────────────────────

def filas_del_dia(db: Session, fecha_sesiones: str, reglas: ir.Reglas
                  ) -> tuple[list[Fila], list[Fila]]:
    """(pedido, adicionales_previstos) de las hojas compuestas de `fecha_sesiones`."""
    pedido, previstos = [], []
    for turno in hd.TURNOS:
        hoja = hd.componer(db, fecha_sesiones, turno)
        for pu in hoja.puestos:
            p = pu.paciente
            if not cuenta_para_pedido(p):
                continue
            fila = _fila("pedido", fecha_sesiones, p, turno, pu.estacion, pu.cama, reglas, tipo=pu.tipo)
            (previstos if es_adicional(p) else pedido).append(fila)
    return pedido, previstos


# ── Asistencia del día (para devoluciones y adicionales) ──────────────────────

@dataclass
class Asistencia:
    registro: models.Registro
    sesion: models.Sesion
    paciente: models.Paciente
    asistencia: Optional[str]
    peso_entrada: Optional[float]
    suplente: bool = False

    @property
    def llego(self) -> bool:
        return hd.llego(self.asistencia, self.peso_entrada)

    @property
    def adicional_de_hoy(self) -> bool:
        """Fila marcada «adicional» en la hoja: aplica a quien asiste en ella
        (el suplente si hay reemplazo, no el paciente reemplazado)."""
        r = self.registro
        return bool(r.adicional) and (self.suplente or not r.transitorio_paciente_id)

    @property
    def es_adicional(self) -> bool:
        return es_adicional(self.paciente) or self.adicional_de_hoy


def asistencias_del_dia(db: Session, fecha: str) -> tuple[dict[str, models.Sesion], dict[int, Asistencia]]:
    """Sesiones del día por turno y asistencia por paciente.

    En una fila con suplente (reemplazo) la asistencia y el peso son del suplente;
    el paciente reemplazado queda como «H» sin peso.
    """
    sesiones = {s.turno: s for s in db.query(models.Sesion).filter_by(fecha=fecha).all()}
    out: dict[int, Asistencia] = {}
    if not sesiones:
        return sesiones, out
    regs = (db.query(models.Registro)
            .options(joinedload(models.Registro.paciente), joinedload(models.Registro.transitorio_paciente))
            .filter(models.Registro.sesion_id.in_([s.id for s in sesiones.values()])).all())
    por_id = {s.id: s for s in sesiones.values()}
    for r in regs:
        s = por_id[r.sesion_id]
        if r.transitorio_paciente_id and r.transitorio_paciente:
            out[r.transitorio_paciente_id] = Asistencia(r, s, r.transitorio_paciente,
                                                        r.transitorio_asistencia, r.peso_entrada, True)
            out.setdefault(r.paciente_id, Asistencia(r, s, r.paciente, r.asistencia or "H", None))
        elif r.paciente:
            out[r.paciente_id] = Asistencia(r, s, r.paciente, r.asistencia, r.peso_entrada)
    return sesiones, out


def _ubic(a: Asistencia) -> tuple[Optional[int], Optional[int]]:
    return hd.ubicacion_registro(a.registro)


# ── Pedido ya hecho para un día ───────────────────────────────────────────────

def pedido_confirmado(db: Session, fecha_pedido: str) -> models.PedidoInsumos | None:
    return (db.query(models.PedidoInsumos).options(joinedload(models.PedidoInsumos.items))
            .filter_by(fecha_pedido=fecha_pedido).first())


def pedido_que_cubre(db: Session, fecha_sesiones: str) -> models.PedidoInsumos | None:
    return (db.query(models.PedidoInsumos).options(joinedload(models.PedidoInsumos.items))
            .filter_by(fecha_sesiones=fecha_sesiones).order_by(models.PedidoInsumos.id.desc()).first())


def filas_de_snapshot(pedido: models.PedidoInsumos, seccion: Optional[str] = None) -> list[Fila]:
    """Reconstruye las filas guardadas (una por paciente y sección)."""
    filas: dict[tuple, Fila] = {}
    for it in pedido.items:
        if seccion and it.seccion != seccion:
            continue
        clave = (it.seccion, it.paciente_id, it.paciente_nombre)
        f = filas.get(clave)
        if f is None:
            f = Fila(seccion=it.seccion, fecha_sesion=it.fecha_sesion or pedido.fecha_sesiones,
                     paciente_id=it.paciente_id, nombre=it.paciente_nombre or "", cedula=it.cedula or "",
                     turno=it.turno, estacion=it.estacion, cama=it.cama, acceso=it.acceso or "—",
                     alertas=[a for a in (it.alertas or "").split(SEP_ALERTAS) if a])
            filas[clave] = f
        if it.insumo_codigo:
            f.lineas.append(ir.Linea(it.insumo_codigo, it.insumo_nombre or it.insumo_codigo,
                                     it.cantidad or 0, it.unidad or "", it.detalle))
    return list(filas.values())


# ── Devoluciones, adicionales y «revisar» del día del pedido ──────────────────

def filas_de_hoy(db: Session, fecha: str, reglas: ir.Reglas) -> dict:
    """Secciones que dependen de la hoja de `fecha` (el día en que se hace el pedido)."""
    cubre = pedido_que_cubre(db, fecha)
    if cubre:
        pedidos = filas_de_snapshot(cubre, "pedido")
        origen = {"tipo": "confirmado", "fecha_pedido": cubre.fecha_pedido}
    else:
        pedidos, _ = filas_del_dia(db, fecha, reglas)
        origen = {"tipo": "recalculado", "fecha_pedido": None}

    sesiones, asist = asistencias_del_dia(db, fecha)
    devolucion, revisar, adicionales, pendientes = [], [], [], []
    pedidos_ids = {f.paciente_id for f in pedidos}

    for f in pedidos:
        a = asist.get(f.paciente_id)
        sesion = sesiones.get(f.turno)
        if a is None:
            if sesion is None:
                pendientes.append({"nombre": f.nombre, "turno": f.turno, "motivo": "Hoja del turno sin abrir"})
            else:
                revisar.append(_copia(f, "revisar", "Estaba en el pedido pero no figura en la hoja de hoy"))
            continue
        f.asistencia, f.peso_entrada = a.asistencia, a.peso_entrada
        if a.asistencia == "A" and a.peso_entrada is not None:
            continue                                          # asistió: todo bien
        if a.asistencia == "A":
            revisar.append(_copia(f, "revisar", "Marcado A (asistió) pero sin peso de entrada"))
        elif a.peso_entrada is not None:
            revisar.append(_copia(f, "revisar", "Tiene peso de entrada pero la asistencia no es A"))
        elif hd.falto(a.asistencia, a.peso_entrada, bool(a.sesion.cerrada)):
            motivo = {"NA": "No asistió", "H": "Hospitalizado", "F": "Falleció"}.get(a.asistencia or "", "Sin asistencia (hoja cerrada)")
            devolucion.append(_copia(f, "devolucion", motivo))
        else:
            pendientes.append({"nombre": f.nombre, "turno": f.turno, "motivo": "Asistencia sin marcar"})

    for pid, a in asist.items():
        p = a.paciente
        if pid in pedidos_ids or not cuenta_para_pedido(p):
            continue
        adic = a.es_adicional
        e, c = _ubic(a)
        if not a.llego:
            if adic:
                pendientes.append({"nombre": p.nombre, "turno": a.sesion.turno, "motivo": "Adicional aún sin llegar"})
            continue
        if adic:
            adicionales.append(_fila("adicional", fecha, p, a.sesion.turno, e, c, reglas, registro=a.registro,
                                     asistencia=a.asistencia, peso_entrada=a.peso_entrada,
                                     motivo="Paciente adicional" if es_adicional(p) else "Adicional de hoy",
                                     tipo="adicional"))
        elif a.llego:
            revisar.append(_fila("revisar", fecha, p, a.sesion.turno, e, c, reglas, registro=a.registro,
                                 asistencia=a.asistencia, peso_entrada=a.peso_entrada,
                                 motivo="Asistió sin estar en el pedido: ¿marcarlo como adicional?"))

    # Un adicional de hoy que ya estaba en el pedido no se cuenta dos veces.
    for pid in pedidos_ids:
        a = asist.get(pid)
        if a and a.llego and a.es_adicional:
            f = next(x for x in pedidos if x.paciente_id == pid)
            revisar.append(_copia(f, "revisar", "Marcado adicional pero ya estaba en el pedido (no se suma dos veces)"))

    return {"devolucion": devolucion, "adicional": adicionales, "revisar": revisar,
            "pendientes": pendientes, "origen": origen,
            "hojas": {t: {"abierta": t in sesiones, "cerrada": bool(sesiones[t].cerrada) if t in sesiones else False}
                      for t in hd.TURNOS}}


def _copia(f: Fila, seccion: str, motivo: str) -> Fila:
    return Fila(seccion=seccion, fecha_sesion=f.fecha_sesion, paciente_id=f.paciente_id, nombre=f.nombre,
                cedula=f.cedula, turno=f.turno, estacion=f.estacion, cama=f.cama, acceso=f.acceso,
                lineas=[ir.Linea(li.codigo, li.nombre, li.cantidad, li.unidad, li.detalle) for li in f.lineas],
                alertas=list(f.alertas), motivo=motivo, asistencia=f.asistencia,
                peso_entrada=f.peso_entrada, tipo=f.tipo)


# ── Pedido completo ───────────────────────────────────────────────────────────

def generar(db: Session, fecha_pedido: str, fecha_sesiones: Optional[str] = None) -> dict:
    """Pedido en vivo (sin guardar) del día `fecha_pedido`."""
    try:
        f = hd.parse_fecha(fecha_pedido)
        d = hd.parse_fecha(fecha_sesiones) if fecha_sesiones else hd.proximo_dia_dialisis(f)
    except hd.Conflicto as e:
        raise ErrorPedido(str(e)) from None
    if d <= f:
        raise ErrorPedido("El día de las sesiones debe ser posterior a la fecha del pedido.")
    reglas = reglas_activas(db)
    pedido, previstos = filas_del_dia(db, d.isoformat(), reglas)
    hoy = filas_de_hoy(db, f.isoformat(), reglas)
    revisar = [_copia(x, "revisar", SEP_ALERTAS.join(x.alertas)) for x in pedido if x.alertas] + hoy["revisar"]
    return {
        "fecha_pedido": f.isoformat(), "fecha_sesiones": d.isoformat(),
        "dia_sesiones": hd.DIA_NOMBRE[d.weekday()], "dia_pedido": hd.DIA_NOMBRE[f.weekday()],
        "filas": pedido + hoy["adicional"] + hoy["devolucion"] + revisar,
        "adicionales_previstos": [{"nombre": x.nombre, "turno": x.turno, "cama_global": x.cama_global}
                                  for x in previstos],
        "pendientes": hoy["pendientes"], "origen_devoluciones": hoy["origen"], "hojas_hoy": hoy["hojas"],
        "reglas_version": reglas.version, "_reglas": reglas,
    }


def filtrar(filas: list[Fila], turno: Optional[str] = None, estacion: Optional[int] = None) -> list[Fila]:
    return [f for f in filas if (not turno or f.turno == turno) and (not estacion or f.estacion == estacion)]


def totales(filas: list[Fila]) -> dict:
    """Totales por insumo de cada sección y neto = pedido + adicionales − devoluciones."""
    por = {s: ir.sumar(f.lineas for f in filas if f.seccion == s) for s in ("pedido", "adicional", "devolucion")}
    neto: dict[str, ir.Linea] = {}
    for s, signo in (("pedido", 1), ("adicional", 1), ("devolucion", -1)):
        for li in por[s]:
            n = neto.setdefault(li.codigo, ir.Linea(li.codigo, li.nombre, 0, li.unidad, li.detalle))
            n.cantidad += signo * li.cantidad
    return {**{s: [li.como_dict() for li in v] for s, v in por.items()},
            "neto": [li.como_dict() for li in neto.values()]}


def serializar(res: dict, turno: Optional[str] = None, estacion: Optional[int] = None) -> dict:
    filas = filtrar(res["filas"], turno, estacion)
    out = {k: v for k, v in res.items() if not k.startswith("_") and k not in ("filas", "novedades")}
    out["filtro"] = {"turno": turno, "estacion": estacion}
    out["secciones"] = {s: [f.como_dict() for f in filas if f.seccion == s] for s in SECCIONES}
    out["totales"] = totales(filas)
    if "novedades" in res:
        nov = filtrar(res["novedades"], turno, estacion)
        out["novedades"] = [f.como_dict() for f in nov]
    return out


# ── Confirmar (foto inmutable) ────────────────────────────────────────────────

def confirmar(db: Session, fecha_pedido: str, usuario: str, fecha_sesiones: Optional[str] = None
              ) -> models.PedidoInsumos:
    if pedido_confirmado(db, fecha_pedido):
        raise ErrorPedido("El pedido de ese día ya está confirmado.")
    res = generar(db, fecha_pedido, fecha_sesiones)
    exigir_abierto(db, res["fecha_pedido"], res["fecha_sesiones"])   # R12: mes cerrado -> 409
    reglas: ir.Reglas = res["_reglas"]
    pedido = models.PedidoInsumos(
        fecha_pedido=res["fecha_pedido"], fecha_sesiones=res["fecha_sesiones"], estado="confirmado",
        confirmado_en=datetime.now(), confirmado_por=usuario,
        reglas_json=json.dumps(reglas.model_dump(exclude_none=True), ensure_ascii=False),
        resumen_json=json.dumps({
            "revisar": [f.como_dict() for f in res["filas"] if f.seccion == "revisar"],
            "pendientes": res["pendientes"], "adicionales_previstos": res["adicionales_previstos"],
            "origen_devoluciones": res["origen_devoluciones"]}, ensure_ascii=False))
    for f in res["filas"]:
        if f.seccion == "revisar":
            continue
        base = dict(seccion=f.seccion, fecha_sesion=f.fecha_sesion, paciente_id=f.paciente_id,
                    paciente_nombre=f.nombre, cedula=f.cedula, turno=f.turno, estacion=f.estacion,
                    cama=f.cama, acceso=f.acceso, alertas=SEP_ALERTAS.join(f.alertas) or None)
        if not f.lineas:
            pedido.items.append(models.PedidoInsumosItem(**base))
        for li in f.lineas:
            pedido.items.append(models.PedidoInsumosItem(
                **base, insumo_codigo=li.codigo, insumo_nombre=li.nombre, cantidad=li.cantidad,
                unidad=li.unidad, detalle=li.detalle))
    db.add(pedido)
    db.flush()
    return pedido


def anular(db: Session, fecha_pedido: str) -> None:
    p = pedido_confirmado(db, fecha_pedido)
    if not p:
        raise ErrorPedido("No hay pedido confirmado ese día.")
    exigir_abierto(db, p.fecha_pedido, p.fecha_sesiones)   # R12
    db.delete(p)


def ver(db: Session, fecha_pedido: str, fecha_sesiones: Optional[str] = None) -> dict:
    """Pedido del día: la foto si está confirmado (más novedades posteriores), si no, en vivo."""
    p = pedido_confirmado(db, fecha_pedido)
    if not p:
        res = generar(db, fecha_pedido, fecha_sesiones)
        res["confirmado"] = None
        return res
    resumen = json.loads(p.resumen_json or "{}")
    filas = filas_de_snapshot(p)
    # Revisar: avisos de la foto (calibre/filtro faltante) + chequeos EN VIVO de la hoja de hoy.
    revisar = [_copia(x, "revisar", SEP_ALERTAS.join(x.alertas)) for x in filas
               if x.seccion == "pedido" and x.alertas]
    d = hd.parse_fecha(p.fecha_sesiones)
    f = hd.parse_fecha(p.fecha_pedido)
    res = {
        "fecha_pedido": p.fecha_pedido, "fecha_sesiones": p.fecha_sesiones,
        "dia_sesiones": hd.DIA_NOMBRE[d.weekday()], "dia_pedido": hd.DIA_NOMBRE[f.weekday()],
        "filas": filas,
        "adicionales_previstos": resumen.get("adicionales_previstos", []),
        "pendientes": resumen.get("pendientes", []),
        "origen_devoluciones": resumen.get("origen_devoluciones"),
        "confirmado": {"id": p.id, "en": p.confirmado_en.isoformat(timespec="minutes") if p.confirmado_en else None,
                       "por": p.confirmado_por, "estado": p.estado},
    }
    # Novedades: adicionales/devoluciones que aparecieron DESPUÉS de confirmar.
    try:
        vivo = filas_de_hoy(db, p.fecha_pedido, reglas_activas(db))
        guardadas = {(x.seccion, x.paciente_id) for x in filas}
        res["novedades"] = [x for x in vivo["adicional"] + vivo["devolucion"]
                            if (x.seccion, x.paciente_id) not in guardadas]
        revisar += vivo["revisar"]
        res["hojas_hoy"] = vivo["hojas"]
    except hd.Conflicto:
        res["novedades"] = []
    res["filas"] = filas + revisar
    return res


# ── CSV ───────────────────────────────────────────────────────────────────────

def a_csv(datos: dict) -> str:
    """CSV (separador «;», UTF-8 con BOM para Excel) de un pedido serializado."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow(["Pedido de insumos", f"Fecha del pedido {datos['fecha_pedido']}",
                f"Sesiones del {datos['dia_sesiones']} {datos['fecha_sesiones']}",
                "CONFIRMADO" if datos.get("confirmado") else "BORRADOR (sin confirmar)"])
    w.writerow(["Sección", "Fecha sesión", "Turno", "Estación", "Cama", "Paciente", "Cédula", "Acceso",
                "Insumo", "Cantidad", "Unidad", "Detalle", "Motivo", "Avisos"])
    for s in SECCIONES:
        for f in datos["secciones"][s]:
            comunes = [SECCION_NOMBRE[s], f["fecha_sesion"], f["turno"] or "", f["estacion"] or "",
                       f["cama_global"] or "", f["nombre"], f["cedula"], f["acceso"]]
            avisos = SEP_ALERTAS.join(f["alertas"])
            if not f["items"]:
                w.writerow(comunes + ["", "", "", "", f["motivo"] or "", avisos])
            for it in f["items"]:
                w.writerow(comunes + [it["nombre"], it["cantidad"], it["unidad"], it["detalle"] or "",
                                      f["motivo"] or "", avisos])
    w.writerow([])
    w.writerow(["TOTALES", "Sección", "Insumo", "Cantidad", "Unidad", "Detalle"])
    for s, nombre in (("pedido", "Pedido"), ("adicional", "Adicionales"),
                      ("devolucion", "Devolución"), ("neto", "Neto (pedido + adicionales − devoluciones)")):
        for it in datos["totales"][s]:
            w.writerow(["", nombre, it["nombre"], it["cantidad"], it["unidad"], it["detalle"] or ""])
    return "﻿" + buf.getvalue()
