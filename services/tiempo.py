"""Fecha local de la unidad (Colombia, UTC-5 todo el año: no tiene horario de verano)."""
from datetime import date, datetime, timedelta, timezone

TZ_UNIDAD = timezone(timedelta(hours=-5))


def hoy_local() -> date:
    return datetime.now(TZ_UNIDAD).date()
