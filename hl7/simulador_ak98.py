"""
Simulador de máquinas AK 98 — genera mensajes ORU^R01 de FIN DE SESIÓN con
datos 100 % FICTICIOS y los envía al puente local por MLLP.

    python -m hl7.simulador_ak98 --maquinas 4 --puerto 2575
    python -m hl7.simulador_ak98 --solo-imprimir --maquinas 1   # ver el mensaje

Valores plausibles: peso pre/post coherente con la UF, Kt/V 1.1–1.6, tensión
arterial, frecuencia cardiaca, duración ~4 h y alarmas ocasionales. Con
--prob-malformado se mezcla algún mensaje dañado para probar el manejo de errores.

Los identificadores OBX-3 salen de hl7/mapeo_ak98.json (PROVISIONALES).
Ningún dato corresponde a personas reales.
"""
from __future__ import annotations

import argparse
import asyncio
import random
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

if __package__ in (None, ""):  # ejecución directa: python hl7/simulador_ak98.py
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
    __package__ = "hl7"

from hl7.mllp import codigo_ack, enmarcar, leer_mensaje  # noqa: E402
from hl7.parser import Separadores, codificar_escapes, formatear_fecha_hora  # noqa: E402

HORA_INICIO = {"M": time(6, 0), "T": time(12, 30), "N": time(18, 30)}
ALARMAS = ["PRESION VENOSA ALTA", "PRESION ARTERIAL BAJA", "DETECTOR DE AIRE", "CONDUCTIVIDAD", "FUGA DE SANGRE"]
NOTAS = ["Sesión sin novedad", "Cambio de línea arterial & reinicio", "Paciente refiere calambres; se ajusta UF",
         "Hipotensión transitoria^se administra SSN 100 mL"]


@dataclass
class SesionFicticia:
    """Datos inventados de una sesión."""

    maquina: str
    id_paciente: str
    inicio: datetime
    peso_entrada: float
    peso_salida: float
    uf_litros: float
    ktv: float
    ta_sistolica: int
    ta_diastolica: int
    frecuencia: int
    duracion_min: int
    alarmas: list[str]
    nota: str


def sesion_ficticia(rng: random.Random, maquina: str, id_paciente: str, inicio: datetime) -> SesionFicticia:
    peso_seco = round(rng.uniform(48, 88), 1)
    ganancia = round(rng.uniform(0.8, 3.6), 1)
    peso_entrada = round(peso_seco + ganancia, 1)
    uf = round(ganancia + rng.uniform(0.2, 0.5), 2)               # UF ≈ ganancia + líquidos de la sesión
    peso_salida = round(peso_entrada - uf + rng.uniform(0.1, 0.4), 1)  # restitución/ingesta durante la sesión
    alarmas = rng.sample(ALARMAS, k=rng.choice([0, 0, 0, 1, 2]))
    return SesionFicticia(
        maquina=maquina, id_paciente=id_paciente, inicio=inicio,
        peso_entrada=peso_entrada, peso_salida=peso_salida, uf_litros=uf,
        ktv=round(rng.uniform(1.1, 1.6), 2),
        ta_sistolica=rng.randint(105, 160), ta_diastolica=rng.randint(60, 95),
        frecuencia=rng.randint(62, 98), duracion_min=rng.choice([225, 235, 240, 240, 240, 245]),
        alarmas=alarmas, nota=rng.choice(NOTAS),
    )


def construir_oru(s: SesionFicticia, control_id: str) -> str:
    """Arma un ORU^R01 (texto, sin marco MLLP) con los datos de la sesión."""
    sep = Separadores()
    esc = lambda t: codificar_escapes(t, sep)  # noqa: E731
    fin = s.inicio + timedelta(minutes=s.duracion_min)
    ts_fin = formatear_fecha_hora(fin)
    n = 0

    def obx(tipo: str, ident: str, texto: str, valor: str, unidad: str = "") -> str:
        nonlocal n
        n += 1
        return f"OBX|{n}|{tipo}|{ident}^{esc(texto)}^AK98L||{valor}|{unidad}|||||F|||{ts_fin}"

    num = s.id_paciente.split("-")[-1]
    seg = [
        f"MSH|^~\\&|AK98|{s.maquina}|HOJA-DIARIA|UNIDAD-RENAL|{ts_fin}||ORU^R01^ORU_R01|{control_id}|P|2.5",
        f"PID|1||{s.id_paciente}^^^AK98||FICTICIO^PACIENTE {num}",
        f"OBR|1|||HD^Sesión de hemodiálisis^AK98L|||{formatear_fecha_hora(s.inicio)}|{ts_fin}",
        obx("NM", "AK98-PESO-PRE", "Peso pre", f"{s.peso_entrada:.1f}", "kg"),
        obx("NM", "AK98-PESO-POST", "Peso post", f"{s.peso_salida:.1f}", "kg"),
        obx("NM", "AK98-UF-TOTAL", "UF total", f"{int(round(s.uf_litros * 1000))}", "mL"),
        obx("NM", "AK98-KTV", "Kt/V", f"{s.ktv:.2f}"),
        obx("SN", "AK98-PA", "Tensión arterial", f"^{s.ta_sistolica}^/^{s.ta_diastolica}", "mm[Hg]"),
        obx("NM", "AK98-FC", "Frecuencia cardiaca", str(s.frecuencia), "/min"),
        obx("NM", "AK98-DURACION", "Duración", str(s.duracion_min), "min"),
    ]
    if s.alarmas:
        seg.append(obx("ST", "AK98-ALARMA", "Alarmas", "~".join(esc(a) for a in s.alarmas)))
    seg.append(obx("TX", "AK98-NOTA", "Nota", esc(s.nota)))
    return "\r".join(seg) + "\r"


def malograr(mensaje: str, rng: random.Random) -> str:
    """Daña un mensaje a propósito (para probar AE/AR y el manejo de errores)."""
    tipo = rng.choice(["sin_pid", "segmento_roto", "sin_msh"])
    lineas = mensaje.strip("\r").split("\r")
    if tipo == "sin_pid":
        lineas = [l for l in lineas if not l.startswith("PID")]
    elif tipo == "segmento_roto":
        lineas.insert(3, "obx|roto")
    else:
        lineas = lineas[1:]
    return "\r".join(lineas) + "\r"


def generar_lote(
    *, maquinas: int, por_maquina: int, fecha: date, turno: str, ids: list[str] | None,
    prob_malformado: float, semilla: int | None,
) -> list[tuple[str, str]]:
    """Lista de (maquina, mensaje) ficticios."""
    rng = random.Random(semilla)
    salida: list[tuple[str, str]] = []
    k = 0
    for m in range(1, maquinas + 1):
        maquina = f"AK98-{m:02d}"
        for j in range(por_maquina):
            id_pac = ids[k % len(ids)] if ids else f"AK-SIM-{k + 1:04d}"
            k += 1
            inicio = datetime.combine(fecha, HORA_INICIO[turno]) + timedelta(minutes=rng.randint(0, 25) + j * 300)
            control = f"SIM{fecha:%Y%m%d}{turno}{m:02d}{j:02d}{rng.randint(1000, 9999)}"
            msg = construir_oru(sesion_ficticia(rng, maquina, id_pac, inicio), control)
            if rng.random() < prob_malformado:
                msg = malograr(msg, rng)
            salida.append((maquina, msg))
    return salida


async def enviar_maquina(host: str, puerto: int, mensajes: list[str], espera: float) -> list[str]:
    """Una conexión MLLP por máquina; devuelve el código de ACK de cada mensaje."""
    reader, writer = await asyncio.open_connection(host, puerto)
    codigos: list[str] = []
    try:
        for msg in mensajes:
            writer.write(enmarcar(msg))
            await writer.drain()
            try:
                ack = await asyncio.wait_for(leer_mensaje(reader), timeout=10)
            except asyncio.TimeoutError:
                ack = None
            codigos.append(codigo_ack(ack) if ack else "SIN-ACK")
            if espera:
                await asyncio.sleep(espera)
    finally:
        writer.close()
        await writer.wait_closed()
    return codigos


async def _principal(args: argparse.Namespace) -> int:
    fecha = date.fromisoformat(args.fecha) if args.fecha else date.today()
    ids = [x.strip() for x in args.ids.split(",") if x.strip()] if args.ids else None
    lote = generar_lote(maquinas=args.maquinas, por_maquina=args.mensajes_por_maquina, fecha=fecha,
                        turno=args.turno, ids=ids, prob_malformado=args.prob_malformado, semilla=args.semilla)
    if args.solo_imprimir:
        for maquina, msg in lote:
            print(f"# {maquina}")
            print(msg.replace("\r", "\n"))
        return 0
    por_maquina: dict[str, list[str]] = {}
    for maquina, msg in lote:
        por_maquina.setdefault(maquina, []).append(msg)
    resultados = await asyncio.gather(*(enviar_maquina(args.host, args.puerto, msgs, args.espera)
                                        for msgs in por_maquina.values()))
    total: dict[str, int] = {}
    for maquina, codigos in zip(por_maquina, resultados):
        print(f"{maquina}: {' '.join(codigos)}")
        for c in codigos:
            total[c] = total.get(c, 0) + 1
    print("Resumen ACK:", ", ".join(f"{k}={v}" for k, v in sorted(total.items())))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Simulador de máquinas AK 98 (datos FICTICIOS) → puente MLLP")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--puerto", type=int, default=2575)
    p.add_argument("--maquinas", type=int, default=3, help="número de máquinas simuladas")
    p.add_argument("--mensajes-por-maquina", type=int, default=1)
    p.add_argument("--turno", choices=["M", "T", "N"], default="M")
    p.add_argument("--fecha", help="YYYY-MM-DD (por defecto hoy)")
    p.add_argument("--ids", help="ids de paciente de la máquina, separados por coma (p. ej. AK-SIM-0001,…)")
    p.add_argument("--prob-malformado", type=float, default=0.0, help="probabilidad 0–1 de dañar un mensaje")
    p.add_argument("--semilla", type=int, help="semilla aleatoria (resultados reproducibles)")
    p.add_argument("--espera", type=float, default=0.0, help="segundos entre mensajes de una misma máquina")
    p.add_argument("--solo-imprimir", action="store_true", help="imprime los mensajes en lugar de enviarlos")
    return asyncio.run(_principal(p.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
