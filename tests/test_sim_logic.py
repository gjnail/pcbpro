"""Behavioural logic chips: shift register, decade counter, Schmitt oscillator, part resolution, ULN2003."""
import numpy as np

from pcbpro.model.board import Component, Project
from pcbpro.model.footprints import find_part
from pcbpro.sim.devices import Capacitor, Resistor, VoltageSource, Waveform
from pcbpro.sim.engine import Circuit, Simulator
from pcbpro.sim.logic import SPECS, LogicDevice, lookup
from pcbpro.sim.models import resolve
from pcbpro.sim.netlist import build_circuit


def _chip(c, name, extra=()):
    spec = SPECS[name]
    tn = {"VCC": c.node("VCC"), "GND": 0}
    for p in list(spec.pins) + list(spec.analog) + list(extra):
        tn[p] = c.node(p)
    c.add(VoltageSource(tn["VCC"], 0, 5.0))
    return c.add(LogicDevice(spec, tn, name=name)), tn


def test_lookup_names():
    assert lookup("74HC595D").name == "74HC595"
    assert lookup("SN74HC595N").name == "74HC595"
    assert lookup("CD4017BE").name == "CD4017"
    assert lookup("74HC14D").name == "74HC14"
    assert lookup("74LVC1G14GW").name == "74LVC1G14"
    assert lookup("NE555") is None


def test_595_shifts_and_latches():
    c = Circuit()
    dev, tn = _chip(c, "74HC595")
    c.add(VoltageSource(tn["SRCLK"], 0, Waveform("pulse", v1=0, v2=5, delay=1e-3, rise=1e-6, fall=1e-6,
                                                 width=0.5e-3, period=1e-3)))
    c.add(VoltageSource(tn["SER"], 0, Waveform("pulse", v1=5, v2=0, delay=2.5e-3, rise=1e-6, fall=1e-6, width=1)))
    c.add(VoltageSource(tn["RCLK"], 0, Waveform("pulse", v1=0, v2=5, delay=8.7e-3, rise=1e-6, fall=1e-6,
                                                width=0.2e-3)))
    c.add(VoltageSource(tn["SRCLR"], 0, 5.0))
    c.add(VoltageSource(tn["OE"], 0, 0.0))
    for q in "ABCDEFGH":
        c.add(Resistor(tn[f"Q{q}"], 0, 10e3))
    s = Simulator(c)
    s.start_op()
    s.run_until(8.5e-3)
    assert s.x[tn["QH"]] < 0.5  # not latched yet
    s.run_until(9.5e-3)
    bits = [s.x[tn[f"Q{q}"]] > 2.5 for q in "ABCDEFGH"]
    assert bits == [False] * 6 + [True, True]


def test_4017_walks_its_outputs():
    c = Circuit()
    dev, tn = _chip(c, "CD4017")
    c.add(VoltageSource(tn["CLK"], 0, Waveform("square", freq=1e3, lo=0, hi=5, duty=0.5)))
    c.add(VoltageSource(tn["RESET"], 0, 0.0))
    c.add(VoltageSource(tn["INH"], 0, 0.0))
    s = Simulator(c)
    s.start_op()
    seen = []
    s.on_accept = lambda t, x: seen.append(next((i for i in range(10) if x[tn[f"Q{i}"]] > 2.5), None))
    s.run_until(12.5e-3)
    order = [k for i, k in enumerate(seen) if k is not None and (i == 0 or seen[i - 1] != k)]
    assert order[:11] == [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 0]


def test_schmitt_inverter_oscillates():
    c = Circuit()
    dev, tn = _chip(c, "74HC14")
    c.add(Resistor(tn["1Y"], tn["1A"], 10e3))
    c.add(Capacitor(tn["1A"], 0, 100e-9))
    s = Simulator(c)
    s.start_uic()
    ys = []
    s.on_accept = lambda t, x: ys.append((t, x[tn["1Y"]] > 2.5))
    s.run_until(20e-3)
    arr = np.array(ys)
    rises = arr[1:, 0][np.diff(arr[:, 1].astype(int)) == 1]
    f = 1 / np.mean(np.diff(rises[2:]))
    rc = 10e3 * 100e-9
    assert 0.5 / rc < f < 2.0 / rc  # f = 1 / (RC ln(0.6 * 0.6 / (0.4 * 0.4))) ~ 1.23 / RC


def test_board_level_logic_and_uln():
    p = Project("logic")
    u1 = Component("U1", "74HC04", find_part("Parts catalog/Logic/74HC04D".split("/")[-1]).make()
                   if find_part("74HC04D") else find_part("SOIC-14").make(), mpn="74HC04D",
                   pad_nets={"14": "VCC", "7": "GND", "1": "VCC", "2": "NOTA"})
    u2 = Component("U2", "ULN2003AD", find_part("SOIC-16").make(), mpn="ULN2003AD",
                   pad_nets={"1": "IN", "8": "GND", "9": "VCC", "16": "LOAD"})
    r = Component("R1", "1k", find_part("Resistor 0805").make(), pad_nets={"1": "VCC", "2": "LOAD"})
    j = Component("J1", "5V", find_part("Pin header 1x2 P2.54").make(), pad_nets={"1": "VCC", "2": "GND"})
    rin = Component("R2", "10k", find_part("Resistor 0805").make(), pad_nets={"1": "VCC", "2": "IN"})
    p.components += [u1, u2, r, j, rin]
    assert resolve(u1).kind == "logic" and resolve(u2).kind == "uln"
    ck = build_circuit(p)
    s = Simulator(ck)
    x = s.start_op()
    assert x[ck.net_node["NOTA"]] < 0.1  # inverter of a high input
    assert x[ck.net_node["LOAD"]] < 1.2  # Darlington pulls the load low
