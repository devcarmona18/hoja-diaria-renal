"""
Algoritmo de la auto-programación mensual de EPO y hierro (R14). Módulo PURO:
no toca la base de datos, solo fechas y números, para poder probarlo y
explicarlo con ejemplos (ver docs/epo-hierro.md).

Unidades
--------
- EPO: se cuenta en **jeringas de 4.000 UI** (1 jeringa = 4.000 UI, 2 = 8.000 UI).
- Hierro (Fe): se cuenta en **dosis**; como máximo 1 dosis por sesión.

Días de laboratorio
-------------------
Por defecto: el **segundo miércoles del mes** (siempre cae entre el 8 y el 14, es
decir, en la «segunda semana» contada como días 8-14) y el **jueves de esa misma
semana** (LMV se toma muestras el miércoles, MJS el jueves). Se puede cambiar por
mes. Esos días no se programa nada salvo que la dosis no quepa en el resto.

Reparto de EPO (por paciente)
-----------------------------
Sea ``E`` el número de jeringas y ``N`` las sesiones del paciente que NO son día de
laboratorio:
1. ``E <= N``: ``E`` sesiones con 1 jeringa, en posiciones uniformes y centradas
   (``posiciones_uniformes``): 4 jeringas en 13 sesiones → sesiones 2, 5, 9 y 12.
2. ``N < E <= 2N``: todas llevan 1 jeringa y ``E - N`` llevan 2 (8.000 UI),
   también repartidas de forma uniforme (14 jeringas en 13 sesiones → 1 doble).
3. ``E > 2N`` (inevitable): primero 2 jeringas en cada sesión normal, el resto en
   los días de laboratorio (máx. 2 c/u) y, si aún sobra, reparto parejo en todas.

Reparto de hierro (toda la unidad a la vez) — «opción B»
--------------------------------------------------------
Para cada paciente con ``F`` dosis:
1. **Un poco más de la mitad antes del laboratorio**: al menos ``⌈F/2⌉`` dosis en
   las sesiones previas al primer día de laboratorio (F=1 → la única va antes si se
   puede; F=2 → 1; F=4 → 2). Las demás van donde el reparto parejo y la carga lo
   indiquen (antes o después).
2. Las sesiones normales del mes se dividen en ``F`` **bloques consecutivos** (mismo
   tamaño ±1), una dosis por bloque: quedan espaciadas en todo el mes. Si ese reparto
   no deja ``⌈F/2⌉`` bloques antes del laboratorio, se usan ``⌈F/2⌉`` bloques antes y
   el resto después.
3. Dentro del bloque se escoge el **día con menos hierros en la unidad**; empates:
   no pegada a otra dosis del paciente, más cerca del centro, la más temprana.
4. Orden de los pacientes: primero los más «apretados». Al final una **mejora local**
   mueve dosis (dentro del bloque ampliado medio bloque a cada lado) desde los días
   más cargados a días con al menos 2 hierros menos, sin pegar dosis y sin bajar del
   mínimo antes del laboratorio.
5. Días de laboratorio: solo si ``F`` supera las sesiones normales (inevitable).
   Si ni así caben (F > sesiones), sobran «sin cupo».

Todo es determinista: mismos datos → misma programación.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Iterable

JERINGA_UI = 4000
EPO_MAX_NORMAL = 2          # jeringas por sesión antes de considerar los días de laboratorio


# ── Calendario ────────────────────────────────────────────────────────────────

def dias_del_mes(anio: int, mes: int) -> list[date]:
    return [date(anio, mes, d) for d in range(1, calendar.monthrange(anio, mes)[1] + 1)]


def dias_lab_por_defecto(anio: int, mes: int) -> list[date]:
    """Segundo miércoles del mes (día 8 a 14) y el jueves siguiente."""
    d = date(anio, mes, 8)
    while d.weekday() != 2:
        d += timedelta(days=1)
    return [d, d + timedelta(days=1)]


def sesiones_del_mes(anio: int, mes: int, dias_semana: Iterable[int] | None,
                     excluir: Iterable[date] = ()) -> list[date]:
    """Fechas del mes en que el paciente dializa (nunca domingo), sin las excluidas."""
    ws = set(dias_semana or ()) - {6}
    fuera = set(excluir)
    return [d for d in dias_del_mes(anio, mes) if d.weekday() in ws and d not in fuera]


# ── Espaciado uniforme ────────────────────────────────────────────────────────

def posiciones_uniformes(m: int, k: int) -> list[int]:
    """``k`` índices distintos en ``[0, m)`` repartidos de forma pareja y centrada.

    El índice i-ésimo es ``⌊(2i+1)·m / 2k⌋`` (el centro del i-ésimo tramo de m/k
    sesiones). Ej.: m=13, k=4 → [1, 4, 8, 11] (saltos de 3-4 sesiones).
    """
    if k <= 0 or m <= 0:
        return []
    if k >= m:
        return list(range(m))
    return [((2 * i + 1) * m) // (2 * k) for i in range(k)]


def bloques(m: int, k: int) -> list[tuple[int, int]]:
    """Divide ``[0, m)`` en ``k`` bloques consecutivos [lo, hi) de tamaño ⌊m/k⌋ o ⌈m/k⌉ (k <= m)."""
    return [((j * m) // k, ((j + 1) * m) // k) for j in range(k)]


# ── EPO ───────────────────────────────────────────────────────────────────────

def _uniforme(sesiones: list[date], k: int, base: dict[date, int]) -> None:
    for i in posiciones_uniformes(len(sesiones), k):
        base[sesiones[i]] = base.get(sesiones[i], 0) + 1


def repartir_epo(sesiones: list[date], jeringas: int, dias_lab: Iterable[date] = ()) -> dict[date, int]:
    """Jeringas por sesión (solo las sesiones con al menos 1). Ver reglas en el docstring del módulo."""
    out: dict[date, int] = {}
    if jeringas <= 0 or not sesiones:
        return out
    lab = set(dias_lab)
    normales = [s for s in sesiones if s not in lab]
    en_lab = [s for s in sesiones if s in lab]
    n = len(normales)
    if n and jeringas <= n:
        _uniforme(normales, jeringas, out)
    elif n and jeringas <= EPO_MAX_NORMAL * n:
        for s in normales:
            out[s] = 1
        _uniforme(normales, jeringas - n, out)
    else:
        # Inevitable: las sesiones normales no alcanzan (o no hay).
        for s in normales:
            out[s] = EPO_MAX_NORMAL
        resto = jeringas - EPO_MAX_NORMAL * n
        nl = len(en_lab)
        if nl and resto <= EPO_MAX_NORMAL * nl:
            if resto <= nl:
                _uniforme(en_lab, resto, out)
            else:
                for s in en_lab:
                    out[s] = out.get(s, 0) + 1
                _uniforme(en_lab, resto - nl, out)
        else:
            # Más de 2 jeringas por sesión en todas: reparto parejo sobre todas.
            out = {}
            q, r = divmod(jeringas, len(sesiones))
            for s in sesiones:
                out[s] = q
            _uniforme(sesiones, r, out)
    return {s: v for s, v in out.items() if v > 0}


# ── Hierro ────────────────────────────────────────────────────────────────────

@dataclass
class PacienteFe:
    """Datos de un paciente para el reparto de hierro.

    ``sesiones``: TODAS sus sesiones del mes (ordenadas). ``libres``: las que el
    algoritmo puede usar (sin ajustes manuales, sin días ya cerrados y sin hierro
    reprogramado). ``dosis``: dosis a repartir en las libres. ``dosis_mes`` y
    ``fijas_antes``: total del mes y dosis ya fijas antes del laboratorio (para la
    regla de la mayoría). ``fijas``: fechas con hierro fijo (para no pegar dosis).
    """
    pid: int
    sesiones: list[date]
    dosis: int
    libres: list[date] | None = None
    dosis_mes: int | None = None
    fijas_antes: int = 0
    fijas: set[date] = field(default_factory=set)

    def __post_init__(self):
        self.sesiones = sorted(self.sesiones)
        self.libres = sorted(self.sesiones if self.libres is None else self.libres)
        if self.dosis_mes is None:
            self.dosis_mes = self.dosis


@dataclass
class ResultadoFe:
    asignado: dict[int, set[date]] = field(default_factory=dict)
    en_lab: dict[int, int] = field(default_factory=dict)       # dosis puestas en día de laboratorio (inevitable)
    sin_cupo: dict[int, int] = field(default_factory=dict)     # dosis que no caben en el mes
    carga: dict[date, int] = field(default_factory=dict)       # hierros por día (incluye la carga base)


@dataclass
class _Dosis:
    pid: int
    tramo: list[date]
    lo: int
    hi: int
    i: int          # índice elegido dentro de tramo

    @property
    def fecha(self) -> date:
        return self.tramo[self.i]

    @property
    def centro(self) -> float:
        return (self.lo + self.hi - 1) / 2


def minimo_antes(dosis_mes: int) -> int:
    """Dosis del mes que deben ir ANTES del primer día de laboratorio: «un poco más de
    la mitad» = ⌈F/2⌉ (F=1 → 1, F=2 → 1, F=3 → 2, F=4 → 2, F=5 → 3)."""
    return -(-max(0, dosis_mes) // 2)


def cuantas_antes(dosis_mes: int, fijas_antes: int, dosis: int, n_antes: int, n_despues: int) -> tuple[int, int]:
    """(mínimo antes, resto) del laboratorio para las ``dosis`` libres del paciente.

    Mínimo antes = ⌈F/2⌉ del total del mes menos las ya fijas antes, limitado por las
    sesiones disponibles. Si después del laboratorio no caben las demás, se adelantan.
    """
    if dosis <= 0:
        return 0, 0
    antes = min(max(0, minimo_antes(dosis_mes) - fijas_antes), dosis, n_antes)
    despues = dosis - antes
    if despues > n_despues:
        despues = n_despues
        antes = min(n_antes, dosis - despues)
    return antes, despues


def repartir_fe(pacientes: list[PacienteFe], dias_lab: Iterable[date] = (),
                carga_base: dict[date, int] | None = None, max_iter: int = 5000) -> ResultadoFe:
    """Reparto de hierro «opción B»: lo más parejo posible en el mes y en la carga
    diaria de la unidad, con al menos ⌈F/2⌉ dosis antes del laboratorio."""
    lab = set(dias_lab)
    primer_lab = min(lab) if lab else None
    carga: dict[date, int] = dict(carga_base or {})
    res = ResultadoFe()
    dosis_de: dict[int, list[_Dosis]] = {}
    orden_ses: dict[int, dict[date, int]] = {}
    elegidas: dict[int, set[date]] = {}
    min_antes: dict[int, int] = {}

    def apretado(p: PacienteFe):
        normales = [s for s in p.libres if s not in lab]
        return (-(p.dosis / max(1, len(normales))), -p.dosis, p.pid)

    def pegada(pid: int, f: date, ignorar: date | None = None) -> int:
        idx = orden_ses[pid]
        i = idx.get(f)
        if i is None:
            return 0
        for g in elegidas[pid]:
            if g != ignorar and g in idx and abs(idx[g] - i) == 1:
                return 1
        return 0

    for p in sorted(pacientes, key=apretado):
        orden_ses[p.pid] = {s: i for i, s in enumerate(p.sesiones)}
        elegidas[p.pid] = set(p.fijas)
        dosis_de[p.pid] = []
        res.asignado[p.pid] = set()
        min_antes[p.pid] = 0
        if p.dosis <= 0:
            continue
        normales = [s for s in p.libres if s not in lab]
        k = min(p.dosis, len(normales))
        bl: list[tuple[int, int]] = []          # bloques (índices en «normales»)
        if k and primer_lab is not None:
            n_a = sum(1 for s in normales if s < primer_lab)
            k_a, k_d = cuantas_antes(p.dosis_mes, p.fijas_antes, k, n_a, len(normales) - n_a)
            min_antes[p.pid] = k_a
            globales = bloques(len(normales), k)
            if sum(1 for lo, hi in globales if hi <= n_a) >= k_a:
                bl = globales               # el reparto parejo del mes ya cumple el mínimo antes
            else:
                bl = ([(lo, hi) for lo, hi in bloques(n_a, k_a)] if k_a else []) + \
                     ([(n_a + lo, n_a + hi) for lo, hi in bloques(len(normales) - n_a, k_d)] if k_d else [])
        elif k:
            bl = bloques(len(normales), k)
        for lo, hi in bl:
            centro = (lo + hi - 1) / 2
            i = min(range(lo, hi), key=lambda i: (carga.get(normales[i], 0), pegada(p.pid, normales[i]),
                                                  abs(i - centro), i))
            d = _Dosis(p.pid, normales, lo, hi, i)
            dosis_de[p.pid].append(d)
            elegidas[p.pid].add(d.fecha)
            carga[d.fecha] = carga.get(d.fecha, 0) + 1
        resto = p.dosis - len(bl)
        if resto > 0:   # inevitable: días de laboratorio (los menos cargados)
            libres_lab = sorted((s for s in p.libres if s in lab), key=lambda s: (carga.get(s, 0), s))
            for s in libres_lab[:resto]:
                res.asignado[p.pid].add(s)
                elegidas[p.pid].add(s)
                carga[s] = carga.get(s, 0) + 1
            res.en_lab[p.pid] = min(resto, len(libres_lab))
            if resto > len(libres_lab):
                res.sin_cupo[p.pid] = resto - len(libres_lab)

    def antes_de(pid: int) -> int:
        return sum(1 for d in dosis_de[pid] if primer_lab is not None and d.fecha < primer_lab)

    # Mejora local (prioriza la carga diaria): una dosis puede moverse dentro de su bloque
    # ampliado medio bloque a cada lado, a un día con >= 2 hierros menos, sin quedar pegada
    # a otra dosis del paciente y sin bajar del mínimo antes del laboratorio.
    todas = [d for ds in dosis_de.values() for d in ds]
    for _ in range(max_iter):
        movida = False
        for d in sorted(todas, key=lambda d: (-carga.get(d.fecha, 0), d.fecha, d.pid)):
            actual = carga.get(d.fecha, 0)
            ext = max(1, (d.hi - d.lo) // 2)
            lo, hi = max(0, d.lo - ext), min(len(d.tramo), d.hi + ext)
            opciones = sorted(
                (j for j in range(lo, hi) if d.tramo[j] not in elegidas[d.pid]),
                key=lambda j: (carga.get(d.tramo[j], 0), pegada(d.pid, d.tramo[j], ignorar=d.fecha),
                               abs(j - d.centro), j))
            for j in opciones:
                destino = d.tramo[j]
                if carga.get(destino, 0) + 1 >= actual or pegada(d.pid, destino, ignorar=d.fecha):
                    continue
                if (primer_lab is not None and d.fecha < primer_lab <= destino
                        and antes_de(d.pid) - 1 < min_antes[d.pid]):
                    continue
                carga[d.fecha] -= 1
                elegidas[d.pid].discard(d.fecha)
                d.i = j
                elegidas[d.pid].add(destino)
                carga[destino] = carga.get(destino, 0) + 1
                movida = True
                break
            if movida:
                break
        if not movida:
            break

    for pid, ds in dosis_de.items():
        res.asignado[pid] |= {d.fecha for d in ds}
    res.carga = {f: c for f, c in carga.items() if c}
    return res
