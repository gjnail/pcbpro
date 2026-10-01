"""Circuit engine checks against analytic results."""
import math

import numpy as np
import pytest

from pcbpro.sim import ics
from pcbpro.sim.devices import (BJT, FET, VT, Capacitor, Diode, Inductor, Potentiometer, Resistor, Switch,
                                VoltageSource, Waveform)
from pcbpro.sim.engine import Circuit, Simulator
from pcbpro.sim.units import fmt_eng, parse_pot, parse_value, parse_voltage


def test_units():
    assert parse_value("4k7") == pytest.approx(4700)
    assert parse_value("2R2") == pytest.approx(2.2)
    assert parse_value("100nF") == pytest.approx(100e-9)
    assert parse_value("0.1uF") == pytest.approx(1e-7)
    assert parse_value("1M5") == pytest.approx(1.5e6)
    assert parse_value("47R") == pytest.approx(47)
    assert parse_value("16MHz") == pytest.approx(16e6)
    assert parse_value("Red") is None
    assert parse_voltage("3V3") == pytest.approx(3.3)
    assert parse_voltage("+5V") == pytest.approx(5)
    assert parse_voltage("BZX84C5V1") == pytest.approx(5.1)
    assert parse_voltage("VCC") is None
    assert parse_pot("B500K") == ("B", 500e3)
    assert parse_pot("A100K") == ("A", 100e3)
    assert fmt_eng(4700, "Ω") == "4.7 kΩ"


def _opamp(c, ip, im, o, vp, vn, **kw):
    X = c.internal("X")
    oa = ics.OpAmp(ip, im, o, vp, vn, X, **kw)
    c.add(oa)
    c.add(Resistor(X, 0, oa.rx))
    c.add(Capacitor(X, 0, oa.cx))
    return oa


def test_rc_charge_time_constant():
    c = Circuit()
    a, m = c.node("A"), c.node("M")
    c.add(VoltageSource(a, 0, 5.0))
    c.add(Resistor(a, m, 1e3))
    c.add(Capacitor(m, 0, 1e-6))
    ts, vs = Simulator(c).transient(5e-3, [m])
    assert np.interp(1e-3, ts, vs[:, 0]) / 5 == pytest.approx(1 - math.exp(-1), abs=0.005)


def test_divider_and_diodes():
    c = Circuit()
    a, k, z = c.node("A"), c.node("K"), c.node("Z")
    c.add(VoltageSource(a, 0, 5.0))
    c.add(Resistor(a, k, 4.3e3))
    c.add(Diode(k, 0, is_=4.352e-9, n=1.906))
    c.add(Resistor(a, z, 1e3))
    c.add(Diode(0, z, is_=1e-14, bv=3.3))  # Zener, reverse biased
    x = Simulator(c).operating_point()
    assert 0.58 < x[k] < 0.68
    assert x[z] == pytest.approx(3.3, abs=0.15)


def test_led_current():
    c = Circuit()
    a, k = c.node("A"), c.node("K")
    is_ = 0.01 / math.exp(1.85 / (2 * VT))
    c.add(VoltageSource(a, 0, 5.0))
    c.add(Resistor(a, k, 330))
    c.add(Diode(k, 0, is_=is_, n=2))
    x = Simulator(c).operating_point()
    assert (5 - x[k]) / 330 == pytest.approx(9.5e-3, rel=0.05)


def test_transistor_switches():
    c = Circuit()
    v, b, col = c.node("V"), c.node("B"), c.node("C")
    c.add(VoltageSource(v, 0, 5.0))
    c.add(Resistor(v, b, 10e3))
    c.add(Resistor(v, col, 1e3))
    c.add(BJT(col, b, 0, 1, is_=6.734e-15, bf=416, br=0.737, vaf=74))
    x = Simulator(c).operating_point()
    assert x[col] < 0.2 and 0.6 < x[b] < 0.8
    c = Circuit()
    v, g, d = c.node("V"), c.node("G"), c.node("D")
    c.add(VoltageSource(v, 0, 12.0))
    c.add(VoltageSource(g, 0, 5.0))
    c.add(Resistor(v, d, 10))
    c.add(FET(d, g, 0, 1, vth=1.05, k=10))
    x = Simulator(c).operating_point()
    assert x[d] < 0.1
    c.devices[1].wave.p["v"] = 0.0  # gate low: off
    x = Simulator(c).operating_point()
    assert x[d] > 11.9


def test_opamp_gain_and_clipping():
    c = Circuit()
    vp, vn, i, o, f = c.node("VP"), c.node("VN"), c.node("I"), c.node("O"), c.node("F")
    c.add(VoltageSource(vp, 0, 12))
    c.add(VoltageSource(vn, 0, -12))
    src = c.add(VoltageSource(i, 0, 0.5))
    c.add(Resistor(o, f, 10e3))
    c.add(Resistor(f, 0, 1e3))
    _opamp(c, i, f, o, vp, vn, a0=2e5, gbw=3e6, sr=13e6, hh=1.5, hl=1.5)
    s = Simulator(c)
    assert s.operating_point()[o] == pytest.approx(5.5, abs=0.01)
    src.wave.p["v"] = 2.0
    assert s.operating_point()[o] == pytest.approx(10.5, abs=0.15)


def test_lm317_output():
    c = Circuit()
    vin, adj, out = c.node("IN"), c.node("ADJ"), c.node("OUT")
    c.add(VoltageSource(vin, 0, 12.0))
    c.add(ics.Regulator(vin, adj, out, vset=1.25, vdo=1.8, ilim=1.5, iq=2e-3, adj=True))
    c.add(Resistor(out, adj, 240))
    c.add(Resistor(adj, 0, 720))
    x = Simulator(c).operating_point()
    assert x[out] == pytest.approx(1.25 * (1 + 720 / 240), rel=0.03)


def test_rlc_ring_frequency():
    c = Circuit()
    a, m, k = c.node("A"), c.node("M"), c.node("K")
    c.add(VoltageSource(a, 0, 1.0))
    c.add(Resistor(a, m, 1.0))
    c.add(Inductor(m, k, 1e-3))
    c.add(Capacitor(k, 0, 1e-6))
    ts, vs = Simulator(c).transient(2e-3, [k], h_max=2e-6)
    v = vs[:, 0]
    peaks = [ts[j] for j in range(1, len(v) - 1) if v[j] > v[j - 1] and v[j] >= v[j + 1]]
    assert np.mean(np.diff(peaks[:4])) == pytest.approx(2 * math.pi * math.sqrt(1e-9), rel=0.02)


def test_555_astable_frequency():
    c = Circuit()
    vcc, thr, dis, out, ctrl = c.node("VCC"), c.node("THR"), c.node("DIS"), c.node("OUT"), c.node("CTRL")
    mid = c.internal("mid")
    c.add(VoltageSource(vcc, 0, 5.0))
    for a, b, r in ((vcc, dis, 1e3), (dis, thr, 47e3), (vcc, ctrl, 5e3), (ctrl, mid, 5e3), (mid, 0, 5e3)):
        c.add(Resistor(a, b, r))
    c.add(Capacitor(thr, 0, 10e-6))
    c.add(Capacitor(ctrl, 0, 10e-9))
    t5 = c.add(ics.Timer555(0, thr, out, vcc, ctrl, thr, dis, vcc, mid))
    s = Simulator(c)
    s.start_uic()
    rises = []
    last = [0]

    def rec(t, x):
        if t5.state != last[0]:
            if t5.state:
                rises.append(t)
            last[0] = t5.state
    s.on_accept = rec
    s.run_until(3.0)
    period = np.mean(np.diff(rises[1:]))
    assert 1 / period == pytest.approx(1.44 / ((1e3 + 2 * 47e3) * 10e-6), rel=0.05)


def test_switch_pot_and_ac():
    c = Circuit()
    a, m, w = c.node("A"), c.node("M"), c.node("W")
    src = c.add(VoltageSource(a, 0, 0.0))
    c.add(Resistor(a, m, 1e3))
    c.add(Capacitor(m, 0, 1e-6))
    pot = c.add(Potentiometer(m, w, 0, 10e3, "B", 0.25))
    sw = c.add(Switch([(w, 0)], [[], [0]]))
    s = Simulator(c)
    s.operating_point()
    h = np.abs(s.ac_sweep(np.array([10.0, 1e3 / (2 * math.pi * 1.0)]), src, [m]))[:, 0]
    assert h[0] == pytest.approx(10e3 / 11e3, rel=0.01)
    src.wave = Waveform("dc", v=1.0)
    x = s.operating_point()
    assert x[w] == pytest.approx(x[m] * 0.75, rel=1e-3)
    sw.state = 1
    pot.pos = 0.25
    x = s.operating_point()
    assert x[w] == pytest.approx(0.0, abs=1e-3)
