from sensor_bridge.sinks.arbitration import Owner, OwnerTable, should_publish

T, H = 300, 6  # takeover_after, rssi_hysteresis


def sp(my_rssi, owner, now=1000):
    return should_publish("pc", my_rssi, owner, now, T, H)


def test_no_owner_or_own_device():
    assert sp(-80, None)
    assert sp(-95, Owner("pc", -60, 999))


def test_other_owner_with_comparable_signal_wins():
    assert not sp(-70, Owner("rpi", -72, 990))   # better but within hysteresis
    assert not sp(-80, Owner("rpi", -72, 990))   # worse


def test_takeover_on_clearly_better_signal():
    assert sp(-66, Owner("rpi", -72, 990))


def test_takeover_when_owner_silent():
    assert not sp(-90, Owner("rpi", -60, 1000 - T + 1))
    assert sp(-90, Owner("rpi", -60, 1000 - T))


def test_missing_rssi_only_stale_takeover():
    assert not sp(None, Owner("rpi", -90, 990))
    assert not sp(-50, Owner("rpi", None, 990))


def test_owner_table_ignores_legacy_payload():
    t = OwnerTable()
    t.update_from_state("d", {"temperature": 20})
    assert t.get("d") is None
    t.update_from_state("d", {"temperature": 20, "receiver": "rpi", "ts": 5, "rssi": -70})
    assert t.get("d") == Owner("rpi", -70, 5.0)
