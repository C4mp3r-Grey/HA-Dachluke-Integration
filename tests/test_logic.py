from datetime import datetime, timedelta, timezone

from custom_components.dachluke import logic

T0 = datetime(2026, 11, 1, 7, 0, tzinfo=timezone.utc)


def m(minutes):
    return T0 + timedelta(minutes=minutes)


def test_rise_uses_value_before_window():
    samples = [(m(0), 60.0), (m(4), 74.0)]
    # Fenster 5 min vor m(6) beginnt bei m(1); 60 % von m(0) gilt als Ausgangswert
    assert logic.humidity_rise(samples, m(6)) == 14.0


def test_rise_single_sample_is_zero():
    assert logic.humidity_rise([(m(0), 60.0)], m(1)) == 0.0


def test_rise_falling_is_zero_or_negative():
    samples = [(m(0), 80.0), (m(3), 75.0), (m(6), 70.0)]
    assert logic.humidity_rise(samples, m(6)) <= 0


def test_baseline_is_minimum_before_shower():
    samples = [(m(0), 61.0), (m(5), 60.0), (m(8), 70.0), (m(10), 80.0)]
    assert logic.baseline_humidity(samples, m(10)) == 60.0


def test_close_reason_priority():
    kw = dict(close_offset=3, close_abs=0, indoor_dew=None, outdoor_dew=None, dew_offset=2, dew_enabled=False)
    assert logic.close_reason(humidity=62.5, baseline=60, **kw) == "basis"
    assert logic.close_reason(humidity=70, baseline=60, **kw) is None
    kw["close_abs"] = 65
    assert logic.close_reason(humidity=64, baseline=None, **kw) == "schwelle"


def test_target_position():
    common = dict(restricted=["rainy"], blocked=["hail"], pos_normal=80, pos_restricted=20, pos_frost=10)
    assert logic.target_position(weather_state="cloudy", frost_active=False, **common) == 80
    assert logic.target_position(weather_state="rainy", frost_active=False, **common) == 20
    assert logic.target_position(weather_state="rainy", frost_active=True, **common) == 10
    assert logic.target_position(weather_state="hail", frost_active=True, **common) == 0


def test_dew_point_roughly():
    assert 11 < logic.dew_point(21, 55) < 12.5


def test_humidity_drop_uses_last_known_value():
    samples = [(m(0), 80.0), (m(3), 72.0), (m(12), 71.5)]
    assert logic.humidity_drop(samples, m(12), 10) == 8.5
    assert logic.humidity_drop(samples, m(20), 10) == 0.5
    assert logic.humidity_drop(samples, m(5), 10) is None
