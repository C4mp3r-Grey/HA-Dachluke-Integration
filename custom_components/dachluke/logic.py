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


def value_at(samples: Sequence[Sample], when: datetime) -> float | None:
    """Letzter bekannter Wert zum Zeitpunkt `when` (Sensoren melden nur Änderungen)."""
    value = None
    for t, v in samples:
        if t <= when:
            value = v
        else:
            break
    return value


def humidity_drop(samples: Sequence[Sample], now: datetime, minutes: float) -> float | None:
    """Um wie viel die Feuchte in den letzten `minutes` gefallen ist (positiv = gefallen)."""
    if not samples:
        return None
    past = value_at(samples, now - timedelta(minutes=minutes))
    if past is None:
        return None
    return round(past - samples[-1][1], 2)


def rise_start(samples: Sequence[Sample], baseline: float | None, margin: float = 1.0) -> datetime | None:
    """Zeitpunkt, ab dem die Feuchte über den Ausgangswert gestiegen ist (Beginn des Duschens, geschätzt)."""
    if not samples:
        return None
    if baseline is None:
        return samples[0][0]
    start = samples[0][0]
    for i in range(len(samples) - 1, -1, -1):
        if samples[i][1] <= baseline + margin:
            start = samples[i + 1][0] if i + 1 < len(samples) else samples[i][0]
            break
    return start


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


def absolute_humidity(temp_c: float, rh: float) -> float:
    """Absolute Feuchte in g/m³ (Magnus-Näherung)."""
    saturation = 6.112 * math.exp(17.62 * temp_c / (243.12 + temp_c))  # hPa
    return round(216.7 * (rh / 100 * saturation) / (273.15 + temp_c), 2)


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
    abs_humidity: float | None = None,
    baseline_ah: float | None = None,
    ah_offset: float = 1.0,
    close_abs: float,
    indoor_dew: float | None,
    outdoor_dew: float | None,
    dew_offset: float,
    dew_enabled: bool,
) -> str | None:
    """Grund zum Schließen oder None.

    Geschlossen wird, sobald EINE Bedingung erfüllt ist:
    - absolute Feuchte wieder nahe am Wert vor dem Duschen (wenn Temperatur bekannt).
      Die relative Feuchte wird dann NICHT mit der Basis verglichen, weil Heizen sie
      senkt, ohne dass Wasser hinausgeht.
    - sonst relative Feuchte wieder nahe am Wert vor dem Duschen (Basis + Offset)
    - Feuchte unter dem absoluten Schwellwert (0 = aus)
    - Taupunkt innen unter Taupunkt außen + Offset (optional)
    """
    if humidity is None:
        return None
    if abs_humidity is not None and baseline_ah is not None:
        if abs_humidity <= baseline_ah + ah_offset:
            return "absolut"
    elif baseline is not None and humidity <= baseline + close_offset:
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
