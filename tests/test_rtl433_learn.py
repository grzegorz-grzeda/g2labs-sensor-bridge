import json

from sensor_bridge.core import Router
from sensor_bridge.sources.rtl433 import parse_event
from sensor_bridge.sources.rtl433_learn import Learner, parse_slots

NAMES = {"Nexus-TH/*/1": "Na zewnątrz", "Nexus-TH/99/2": "Piwnica", "A4:C1:38:00:00:01": "Salon"}


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def ev(id_, ch=1, t=8.4, model="Nexus-TH"):
    return {"model": model, "id": id_, "channel": ch, "temperature_C": t, "humidity": 70}


def test_parse_slots_only_wildcards():
    slots = parse_slots(NAMES)
    assert [(s.key, s.model, s.channel, s.device_id) for s in slots] == [
        ("Nexus-TH/*/1", "Nexus-TH", "1", "rtl433_nexus_th_ch1")]
    assert parse_slots({"Foo/*": "x"})[0].device_id == "rtl433_foo_any"


def test_learn_follow_ignore_neighbour_and_relearn(tmp_path):
    clk, sf = Clock(), tmp_path / "b.json"
    L = Learner(NAMES, relearn_after=300, state_file=str(sf), clock=clk)

    r = parse_event(ev(143), L)                     # first frame -> learned
    assert r.device_id == "rtl433_nexus_th_ch1"
    assert r.aliases[0] == "Nexus-TH/*/1"
    assert json.loads(sf.read_text()) == {"Nexus-TH/*/1": "143"}

    clk.t += 60
    assert parse_event(ev(143), L).device_id == "rtl433_nexus_th_ch1"

    clk.t += 60                                     # neighbour, same model+channel, ours still alive
    r = parse_event(ev(200), L)
    assert r.device_id == "rtl433_nexus_th_200_ch1"  # treated as an ordinary, unbound device

    clk.t += 400                                    # ours silent > relearn_after (battery change)
    r = parse_event(ev(77), L)
    assert r.device_id == "rtl433_nexus_th_ch1"
    assert json.loads(sf.read_text()) == {"Nexus-TH/*/1": "77"}


def test_other_channel_or_model_not_matched():
    L = Learner(NAMES, clock=Clock())
    assert parse_event(ev(5, ch=2), L).device_id == "rtl433_nexus_th_5_ch2"
    assert parse_event(ev(5, model="Prologue-TH"), L).device_id == "rtl433_prologue_th_5_ch1"


def test_binding_survives_restart_and_waits_before_relearn(tmp_path):
    clk, sf = Clock(), tmp_path / "b.json"
    sf.write_text(json.dumps({"Nexus-TH/*/1": "143"}))
    L = Learner(NAMES, relearn_after=300, state_file=str(sf), clock=clk)
    clk.t += 10
    assert parse_event(ev(200), L).device_id != "rtl433_nexus_th_ch1"  # neighbour right after restart
    assert parse_event(ev(143), L).device_id == "rtl433_nexus_th_ch1"


def test_unwritable_state_file_does_not_crash(tmp_path):
    L = Learner(NAMES, state_file="/proc/nonexistent/b.json", clock=Clock())
    assert parse_event(ev(1), L).device_id == "rtl433_nexus_th_ch1"


def test_learned_slot_counts_as_named_for_only_named_filter():
    rt = Router({"devices": {"names": NAMES}})
    rt.only_named["rtl433"] = True
    L = Learner(NAMES, clock=Clock())
    assert rt.accept(parse_event(ev(143), L), now=0)
    assert not rt.accept(parse_event(ev(200), L), now=0)   # neighbour, not named
