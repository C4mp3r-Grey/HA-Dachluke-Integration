"""Reine Rechenfunktionen ohne Home-Assistant-Abhängigkeit (gut testbar)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
import math

Sample = tuple[datetime, float]


def humidity_rise(samples: Sequence[Sample], now: datetime, window_min: float = 5) -> float | None:
    """Anstieg der Feuchte in den letzten `window_min` Minuten.

    Homematic-Klimasensoren melden nur alle paar Minuten. Deshalb wird als
    Ausgangswert der letzte Wert *vor* dem Fenster mitgenommen und das Minimum
    im Fenster betrachtet. So unterschätzt die Berechnung den Anstieg nicht,
    wenn im Fenster nur ein oder zwei Werte liegen.
    """
    if not samples:
        return None
    start = now - timedelta(minutes=window_min)
    current = samples[-1][1]
    before = [v for t, v in samples if t <= start]
    inside = [v for t, v in samples if t > start]
    candidates = inside[:]
    if before:
        candidates.append(before[-1])
    if len(candidates) < 2 and not before:
        return 0.0
    return round(current - min(candidates), 1)


def baseline_humidity(samples: Sequence[Sample], now: datetime, lookback_min: float = 20) -> float | None:
    """Feuchte vor dem Duschen: Minimum der letzten `lookback_min` Minuten."""
    start = now - timedelta(minutes=lookback_min)
    values = [v for t, v in samples if t >= start]
    before = [v for t, v in samples if t < start]
    if before:
        values.append(before[-1])
    return min(values) if values else None


def dew_point(temp_c: float, rh: float) -> float | None:
    """Taupunkt nach Magnus-Formel (Näherung)."""
    if rh <= 0:
        return None
    a, b = 17.62, 243.12
    gamma = math.log(rh / 100) + a * temp_c / (b + temp_c)
    return round(b * gamma / (a - gamma), 1)


def target_position(
    *,
    weather_state: str | None,
    restricted: Sequence[str],
    blocked: Sequence[str],
    frost_active: bool,
    pos_normal: int,
    pos_restricted: int,
    pos_frost: int,
) -> int:
    """Zielposition: gesperrt > Frost > eingeschränkt > normal."""
    if weather_state in blocked:
        return 0
    if frost_active:
        return pos_frost
    if weather_state in restricted:
        return pos_restricted
    return pos_normal


def close_reason(
    *,
    humidity: float | None,
    baseline: float | None,
    close_offset: float,
    close_abs: float,
    indoor_dew: float | None,
    outdoor_dew: float | None,
    dew_offset: float,
    dew_enabled: bool,
) -> str | None:
    """Grund zum Schließen oder None.

    Geschlossen wird, sobald EINE Bedingung erfüllt ist:
    - Feuchte wieder nahe am Wert vor dem Duschen (Basis + Offset)
    - Feuchte unter dem absoluten Schwellwert (0 = aus)
    - Taupunkt innen unter Taupunkt außen + Offset (optional)
    """
    if humidity is None:
        return None
    if baseline is not None and humidity <= baseline + close_offset:
        return "basis"
    if close_abs > 0 and humidity < close_abs:
        return "schwelle"
    if (
        dew_enabled
        and indoor_dew is not None
        and outdoor_dew is not None
        and indoor_dew < outdoor_dew + dew_offset
    ):
        return "taupunkt"
    return None
