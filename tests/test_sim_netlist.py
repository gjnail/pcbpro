"""Board -> circuit: part models, pin maps, sources and the as-built mode."""
import numpy as np
import pytest

from pcbpro.examples import flasher_555, list_examples, load_example
from pcbpro.model.board import Component
from pcbpro.model.footprints import find_part
from pcbpro.sim.engine import Simulator
from pcbpro.sim.models import resolve
from pcbpro.sim.netlist import build_circuit, supply_voltage


def _part(lib_name, ref, value, mpn=""):
    lp = find_part(lib_name)
    return Component(ref, value, lp.make(), mpn=mpn)


def test_flasher_resolves_and_finds_supply():
    ck = build_circuit(flasher_555())
    kinds = {i.ref: i.res.kind for i in ck.parts.values()}
    assert kinds["U1"] == "timer555" and kinds["D1"] == "led" and kinds["SW1"] == "switch"
    assert kinds["C4"] == "capacitor" and ck.parts[next(u for u, i in ck.parts.items() if i.ref == "C4")].res.params[
        "polarized"]
    assert all(i.status != "unsupported" for i in ck.parts.values())
    assert [(s.net, s.params["v"]) for s in ck.sources] == [("VCC", 5.0)]
    assert {c.kind for c in ck.controls} >= {"momentary", "source"}


def _led_current(ck, x):
    led = next(i for i in ck.parts.values() if i.ref == "D1").leds[0][0]
    return led.current(float(x[led.nodes[0]] - x[led.nodes[1]]))


def test_flasher_blinks_and_reset_button_stops_it():
    ck = build_circuit(flasher_555())
    s = Simulator(ck)
    s.start_uic()
    samples = []
    s.on_accept = lambda t, x: samples.append((t, _led_current(ck, x)))
    s.run_until(2.5)
    arr = np.array(samples)
    on = arr[:, 1] > 1e-3
    rises = arr[1:, 0][np.diff(on.astype(int)) == 1]
    assert len(rises) >= 3
    assert 1 / np.mean(np.diff(rises[1:])) == pytest.approx(1.52, rel=0.06)
    # hold RESET: the 555 output goes low and stays low
    ck.control(next(c.key for c in ck.controls if c.kind == "momentary")).apply(1)
    s.touch()
    s.on_accept = None
    s.run_until(s.t + 1.0)
    assert _led_current(ck, s.x) < 1e-5


def test_as_built_mode_follows_the_copper():
    examples = list_examples()
    if not examples:
        pytest.skip("routed example not available")
    p = load_example(examples[0])
    from pcbpro.model.copper import fill_all_zones
    fill_all_zones(p)
    ck = build_circuit(p, mode="built")
    s = Simulator(ck)
    s.start_uic()
    peak = 0.0

    def rec(t, x):
        nonlocal peak
        peak = max(peak, _led_current(ck, x))
    s.on_accept = rec
    s.run_until(1.0)
    assert peak > 2e-3
    # cut the LED's anode track: the copper no longer reaches it
    led = p.component("D1")
    anode = led.pad_pos(next(pd for pd in led.footprint.pads if pd.number == "2"))
    p.tracks = [t for t in p.tracks if t.net != "LED_A"]
    p.touch()
    ck2 = build_circuit(p, mode="built")
    s2 = Simulator(ck2)
    s2.start_uic()
    peak = 0.0
    s2.on_accept = lambda t, x: rec_any(t, x)

    def rec_any(t, x):
        nonlocal peak
        peak = max(peak, _led_current(ck2, x))
    s2.run_until(1.0)
    assert peak < 1e-4, anode


def test_pinmaps():
    q = resolve(_part("TO-92 inline", "Q1", "2N3904"))
    assert q.kind == "bjt" and q.pins == {"E": ["1"], "B": ["2"], "C": ["3"]}
    q = resolve(_part("TO-92 wide", "Q2", "BC547B"))
    assert q.pins == {"C": ["1"], "B": ["2"], "E": ["3"]}
    q = resolve(_part("SOT-23", "Q3", "AO3400A"))
    assert q.kind == "fet" and q.pins == {"G": ["1"], "S": ["2"], "D": ["3"]}
    q = resolve(_part("TO-92 E-B-C (BJT, wide)", "Q4", "2N5088"))
    assert q.pins == {"C": ["C"], "B": ["B"], "E": ["E"]}
    u = resolve(Component("U1", "TL072", find_part("DIP-8 (300 mil)").make()))
    assert u.kind == "opamp" and u.pins["OUT1"] == ["1"] and u.pins["V+"] == ["8"]
    u = resolve(Component("U2", "AMS1117-3.3", find_part("SOT-223 regulator").make(), mpn="AMS1117-3.3"))
    assert u.kind == "regulator" and u.params["vset"] == pytest.approx(3.3) and u.pins["OUT"] == ["2", "4"]
    u = resolve(Component("U3", "L7805CV", find_part("TO-220-3 vertical").make()))
    assert u.kind == "regulator" and u.params["vset"] == 5.0 and u.pins["IN"] == ["1"]
    d = resolve(_part("Diode SOD-123", "D5", "BZT52C5V1"))
    assert d.kind == "diode" and d.params["bv"] == pytest.approx(5.1)
    assert resolve(_part("LED 0805", "D6", "Blue")).params["vf"] == pytest.approx(2.9)


def test_supply_voltage_names():
    assert supply_voltage("3V3") == pytest.approx(3.3)
    assert supply_voltage("+12V") == pytest.approx(12)
    assert supply_voltage("-12V") == pytest.approx(-12)
    assert supply_voltage("VCC") == pytest.approx(5)
    assert supply_voltage("THR") is None


def test_regulator_board():
    from pcbpro.model.board import Project
    p = Project("reg")
    reg = Component("U1", "AMS1117-3.3", find_part("SOT-223 regulator").make(),
                    pad_nets={"1": "GND", "2": "3V3", "4": "3V3", "3": "5V"})
    j = Component("J1", "PWR", find_part("Pin header 1x2 P2.54").make(), pad_nets={"1": "5V", "2": "GND"})
    r = Component("R1", "330", find_part("Resistor 0805").make(), pad_nets={"1": "3V3", "2": "GND"})
    p.components += [reg, j, r]
    ck = build_circuit(p)
    assert [s.net for s in ck.sources] == ["5V"]
    s = Simulator(ck)
    x = s.start_op()
    assert x[ck.net_node["3V3"]] == pytest.approx(3.3, abs=0.03)
