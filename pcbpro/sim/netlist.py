"""Build a simulation circuit from a board project.

Nodes come from the logical nets ("as designed") or from the physical copper clusters ("as built", so a missing
track or a short really changes the circuit). Every component is resolved to a model (models.py) and expanded into
devices; power comes from batteries, DC jacks and USB sockets on the board, plus the supply sources configured in
``project.sim["sources"]`` (auto-detected from the net names when not configured).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from ..model.board import Component, Project
from . import ampboard, ics
from .devices import (VT, BJT, FET, Capacitor, Diode, Inductor, Potentiometer, Resistor, Switch, VoltageSource,
                      Waveform)
from .engine import Circuit
from .models import (LED_TYPES, Resolution, is_ground_net, led_params, resolve)
from .units import fmt_eng, parse_value, parse_voltage

LINK_R = 1e-3


@dataclass
class Control:
    """A live knob, button or plug the user can operate while the simulation runs."""
    key: str
    uid: str
    ref: str
    kind: str  # momentary | toggle | pot | plug | temp | encoder | source
    label: str
    devices: list = field(default_factory=list)
    value: float = 0
    options: list = field(default_factory=list)
    lo: float = 0.0
    hi: float = 1.0

    def apply(self, value) -> bool:
        """Set the control; returns True if the circuit changed."""
        changed = False
        if self.kind in ("momentary", "toggle", "encoder"):
            v = int(value)
            for d in self.devices:
                if d.state != v:
                    d.state = v
                    changed = True
        elif self.kind == "pot":
            v = min(max(float(value), 0.0), 1.0)
            for d in self.devices:
                if d.pos != v:
                    d.pos = v
                    changed = True
        elif self.kind == "plug":
            v = int(value)
            for d in self.devices:
                if isinstance(d, VoltageSource):
                    if d.enabled != bool(v):
                        d.enabled = bool(v)
                        changed = True
                elif hasattr(d, "state"):
                    s = d.plug_states[v] if hasattr(d, "plug_states") else v
                    if d.state != s:
                        d.state = s
                        changed = True
        elif self.kind == "temp":
            for d in self.devices:
                if d.temp != float(value):
                    d.temp = float(value)
                    changed = True
        elif self.kind == "source":
            for d in self.devices:
                d.enabled = bool(value)
            changed = True
        self.value = value
        return changed


@dataclass
class PartInfo:
    uid: str
    ref: str
    value: str
    res: Resolution
    devices: list = field(default_factory=list)
    leds: list = field(default_factory=list)  # (Diode, colour hex, label)
    controls: list = field(default_factory=list)
    status: str = "simulated"  # simulated | connection | unsupported | excluded | error
    note: str = ""


@dataclass
class SourceInfo:
    net: str
    kind: str
    params: dict
    device: VoltageSource
    label: str
    auto: bool


class BoardCircuit(Circuit):
    def __init__(self, project: Project, mode: str):
        super().__init__()
        self.project = project
        self.mode = mode
        self.parts: dict[str, PartInfo] = {}
        self.controls: list[Control] = []
        self.sources: list[SourceInfo] = []
        self.pad_nodes: dict[tuple, int] = {}
        self.net_node: dict[str, int] = {}
        self.node_nets: dict[int, set] = {}
        self.ground_nets: set = set()
        self.mcus: list = []

    def control(self, key: str) -> Control | None:
        return next((c for c in self.controls if c.key == key), None)

    def node_label(self, n: int) -> str:
        nets = sorted(self.node_nets.get(n, ()))
        return "/".join(nets) if nets else self.node_names[n]


# --------------------------------------------------------------------------- nodes

def _node_mapper(project: Project, ck: BoardCircuit, mode: str):
    ground_cfg = (project.sim or {}).get("ground")

    def is_gnd(net):
        return net == ground_cfg if ground_cfg else is_ground_net(net)

    if mode == "built":
        from ..model.connectivity import get_connectivity
        conn = get_connectivity(project)

        def pad_node(c: Component, number: str) -> int:
            key = (c.uid, number)
            if key in ck.pad_nodes:
                return ck.pad_nodes[key]
            idx = next((i for i, p in enumerate(c.footprint.pads) if p.number == number), None)
            nets = set()
            root = None
            if idx is not None:
                nid = f"{c.uid}:{idx}"
                if nid in conn.uf.parent:
                    root = conn.uf.find(nid)
                    nets = set(conn.cluster_nets.get(root, set()))
            if root is None:
                net = c.pad_nets.get(number)
                n = ck.node(("pad", c.uid, number), f"{c.ref}.{number}" + (f" ({net}, unconnected)" if net else ""))
            elif any(is_gnd(x) for x in nets):
                n = ck.ground(("cl", root))
                ck.ground_nets.update(x for x in nets if is_gnd(x))
            else:
                n = ck.node(("cl", root), "/".join(sorted(nets)) if nets else f"{c.ref}.{number}")
            for x in nets:
                ck.net_node.setdefault(x, n)
                ck.node_nets.setdefault(n, set()).add(x)
            ck.pad_nodes[key] = n
            return n
    else:
        def pad_node(c: Component, number: str) -> int:
            key = (c.uid, number)
            if key in ck.pad_nodes:
                return ck.pad_nodes[key]
            net = c.pad_nets.get(number)
            if net and is_gnd(net):
                n = ck.ground(("net", net))
                ck.ground_nets.add(net)
            elif net:
                n = ck.node(("net", net), net)
            else:
                n = ck.node(("pad", c.uid, number), f"{c.ref}.{number}")
            if net:
                ck.net_node.setdefault(net, n)
                ck.node_nets.setdefault(n, set()).add(net)
            ck.pad_nodes[key] = n
            return n
    return pad_node


# --------------------------------------------------------------------------- builders

class _Ctx:
    def __init__(self, ck: BoardCircuit, comp: Component, info: PartInfo, pad_node):
        self.ck, self.c, self.info, self.pad_node = ck, comp, info, pad_node

    def pad(self, number: str) -> int:
        return self.pad_node(self.c, number)

    def T(self, term: str, required: bool = True) -> int:
        pads = self.info.res.pins.get(term)
        if not pads:
            if required:
                raise ValueError(f"pin '{term}' is not mapped to a pad")
            return self.ck.internal(f"{self.c.ref}.{term}")
        nodes = [self.pad(p) for p in pads]
        for n in nodes[1:]:
            if n != nodes[0]:
                self.add(Resistor(nodes[0], n, LINK_R, name=f"{self.c.ref} {term} internal"))
        return nodes[0]

    def has(self, term: str) -> bool:
        return bool(self.info.res.pins.get(term))

    def add(self, dev):
        dev.part = self.c.uid
        if not dev.name:
            dev.name = self.c.ref
        self.ck.add(dev)
        self.info.devices.append(dev)
        return dev

    def internal(self, label: str) -> int:
        return self.ck.internal(f"{self.c.ref}.{label}")

    def control(self, kind: str, name: str, label: str, devices: list, value, **kw) -> Control:
        ctl = Control(f"{self.c.uid}:{name}", self.c.uid, self.c.ref, kind, label, devices, value, **kw)
        self.ck.controls.append(ctl)
        self.info.controls.append(ctl)
        return ctl


def _diode(x: _Ctx, a: int, k: int, p: dict, color: str | None = None, label: str = "") -> Diode:
    rs = float(p.get("rs", 0.0))
    if rs > 0:
        ai = x.internal("j")
        x.add(Resistor(a, ai, rs, name=f"{x.c.ref} Rs"))
        d = Diode(ai, k, p.get("is_", 1e-14), p.get("n", 1.0), p.get("bv", 0.0), p.get("ibv", 1e-3), p.get("nbv", 1.0),
                  imax=p.get("imax", 1.0), color=color, rs_node=a, rs=rs)
    else:
        d = Diode(a, k, p.get("is_", 1e-14), p.get("n", 1.0), p.get("bv", 0.0), p.get("ibv", 1e-3), p.get("nbv", 1.0),
                  imax=p.get("imax", 1.0), color=color)
    x.add(d)
    if color is not None:
        x.info.leds.append((d, color, label))
    return d


def _led(x: _Ctx, a: int, k: int, colour_word: str, label: str = "", big=False) -> Diode:
    p = led_params(colour_word, big)
    n = 2.0
    is_ = 0.01 / math.exp((p["vf"] - 0.01 * p["rs"]) / (n * VT))
    return _diode(x, a, k, dict(is_=is_, n=n, rs=p["rs"], bv=5.0, ibv=1e-5, imax=p["imax"]), p["color"], label)


def b_resistor(x: _Ctx):
    r = x.info.res.params.get("r")
    if r is None or r <= 0:
        if r is None:
            x.info.note = "no resistance in the value; using 10 k"
            r = 10e3
        else:
            r = LINK_R
    x.add(Resistor(x.T("1"), x.T("2"), r))


def b_resistor_array(x: _Ctx):
    r = x.info.res.params.get("r") or 10e3
    for a, b in x.info.res.params["pairs"]:
        x.add(Resistor(x.pad(a), x.pad(b), r))


def b_capacitor(x: _Ctx):
    p = x.info.res.params
    c = p.get("c")
    if not c:
        x.info.note = "no capacitance in the value; using 100 nF"
        c = 100e-9
    x.add(Capacitor(x.T("+"), x.T("-"), c, polarized=p.get("polarized", False), vmax=p.get("vmax")))


def b_inductor(x: _Ctx):
    li = x.info.res.params.get("l") or 10e-6
    mid = x.internal("dcr")
    x.add(Resistor(x.T("1"), mid, 0.05))
    x.add(Inductor(mid, x.T("2"), li))


def b_link(x: _Ctx):
    x.add(Resistor(x.T("1"), x.T("2"), x.info.res.params.get("r", 0.05)))


def b_diode(x: _Ctx):
    _diode(x, x.T("A"), x.T("K"), x.info.res.params)


def b_diodes(x: _Ctx):
    for a, k in x.info.res.params["pairs"]:
        _diode(x, x.pad(a), x.pad(k), x.info.res.params)


def b_led(x: _Ctx):
    p = x.info.res.params
    word = p.get("colour") or x.c.value
    _led(x, x.T("A"), x.T("K"), word, x.c.ref, big=p.get("imax", 0.03) > 0.05)


def b_leds(x: _Ctx):
    for entry in x.info.res.params["leds"]:
        a, k, colour = entry[:3]
        label = entry[3] if len(entry) > 3 else colour
        _led(x, x.pad(a), x.pad(k), colour, label)


def b_bjt(x: _Ctx):
    p = x.info.res.params
    c, b, e = x.T("C"), x.T("B"), x.T("E")
    kw = dict(pol=p.get("pol", 1), is_=p.get("is_", 1e-14), br=p.get("br", 4.0), vaf=p.get("vaf", 80.0),
              imax=p.get("imax", 0.2), pmax=p.get("pmax", 0.5))
    if p.get("darlington"):
        bf = math.sqrt(p.get("bf", 1000.0)) * 1.5
        mid = x.internal("e1")
        x.add(BJT(c, b, mid, bf=bf, **kw))
        x.add(BJT(c, mid, e, bf=bf, **kw))
        x.add(Resistor(b, mid, 8e3))
        x.add(Resistor(mid, e, 120.0))
    else:
        x.add(BJT(c, b, e, bf=p.get("bf", 100.0), **kw))


def b_fet(x: _Ctx):
    p = x.info.res.params
    d, g, s = x.T("D"), x.T("G"), x.T("S")
    pol = p.get("pol", 1)
    x.add(FET(d, g, s, pol, p.get("vth", 2.0), p.get("k", 0.1), p.get("lam", 0.01), imax=p.get("imax", 1.0),
              pmax=p.get("pmax", 1.0)))
    x.add(Resistor(g, s, 1e9, name=f"{x.c.ref} gate leakage"))
    if p.get("body", True):
        a, k = (s, d) if pol > 0 else (d, s)
        _diode(x, a, k, dict(is_=1e-12, n=1.0, rs=0.01, imax=p.get("imax", 1.0)))


def b_jfet(x: _Ctx):
    p = x.info.res.params
    d, g, s = x.T("D"), x.T("G"), x.T("S")
    pol = p.get("pol", 1)
    vp = p.get("vp", -1.5)
    k = 2.0 * p.get("idss", 3e-3) / (vp * vp)
    x.add(FET(d, g, s, pol, vp, k, p.get("lam", 0.01), nsub=1.2, imax=0.05, pmax=0.35))
    for other in (s, d):
        a, kk = (g, other) if pol > 0 else (other, g)
        _diode(x, a, kk, dict(is_=1e-14, n=1.0))


def b_opamp(x: _Ctx):
    p = x.info.res.params
    vp, vn = x.T("V+"), x.T("V-")
    units = p.get("units", 1)
    for u in range(1, units + 1):
        if not x.has(f"OUT{u}"):
            continue
        X = x.internal(f"X{u}")
        oa = ics.OpAmp(x.T(f"IN{u}+"), x.T(f"IN{u}-"), x.T(f"OUT{u}"), vp, vn, X, a0=p["a0"], gbw=p["gbw"], sr=p["sr"],
                       hh=p["hh"], hl=p["hl"], rout=p.get("rout", 50.0), ilim=p["ilim"], vmax=p.get("vmax", 36.0),
                       name=f"{x.c.ref}{'ABCD'[u - 1] if units > 1 else ''}")
        x.add(oa)
        x.add(Resistor(X, 0, oa.rx, name=f"{x.c.ref} pole"))
        x.add(Capacitor(X, 0, oa.cx, name=f"{x.c.ref} pole"))
    x.add(Resistor(vp, vn, 9.0 / max(p.get("iq", 1e-3) * units, 1e-6), name=f"{x.c.ref} supply current"))


def b_comparator(x: _Ctx):
    p = x.info.res.params
    vp, vn = x.T("V+"), x.T("V-")
    units = p.get("units", 1)
    for u in range(1, units + 1):
        if not x.has(f"OUT{u}"):
            continue
        x.add(ics.Comparator(x.T(f"IN{u}+"), x.T(f"IN{u}-"), x.T(f"OUT{u}"), vp, vn,
                             name=f"{x.c.ref}{'ABCD'[u - 1] if units > 1 else ''}"))
    x.add(Resistor(vp, vn, 5.0 / p.get("iq", 1e-3), name=f"{x.c.ref} supply current"))


def b_timer555(x: _Ctx):
    p = x.info.res.params
    cmos = p.get("cmos", False)
    gnd, vcc = x.T("GND"), x.T("VCC")
    units = p.get("units", 1)
    for u in range(1, units + 1):
        sfx = str(u) if units > 1 else ""
        ctrl = x.T("CTRL" + sfx)
        mid = x.internal(f"tap{sfx}")
        rd = 100e3 if cmos else 5e3
        x.add(Resistor(vcc, ctrl, rd, name=f"{x.c.ref} divider"))
        x.add(Resistor(ctrl, mid, rd, name=f"{x.c.ref} divider"))
        x.add(Resistor(mid, gnd, rd, name=f"{x.c.ref} divider"))
        x.add(ics.Timer555(gnd, x.T("TRIG" + sfx), x.T("OUT" + sfx), x.T("RESET" + sfx), ctrl, x.T("THR" + sfx),
                           x.T("DIS" + sfx), vcc, mid, cmos=cmos, name=f"{x.c.ref}{'AB'[u - 1] if units > 1 else ''}"))
    x.add(Resistor(vcc, gnd, (50e3 if cmos else 1.7e3) / units, name=f"{x.c.ref} supply current"))


def b_regulator(x: _Ctx):
    p = x.info.res.params
    en = x.T("EN") if x.has("EN") else None
    x.add(ics.Regulator(x.T("IN"), x.T("REF"), x.T("OUT"), en, vset=p["vset"], vdo=p["vdo"], ilim=p["ilim"],
                        iq=p["iq"], adj=p.get("adj", False), pol=p.get("pol", 1), vmax=p.get("vmax", 20.0)))


def b_shuntref(x: _Ctx):
    x.add(ics.ShuntRef(x.T("REF"), x.T("A"), x.T("K"), vref=x.info.res.params.get("vref", 2.495)))


def b_zener_ref(x: _Ctx):
    _diode(x, x.T("A"), x.T("K"), dict(is_=1e-14, n=1.0, rs=0.3, bv=x.info.res.params["bv"], ibv=1e-4, imax=0.015))


def b_sensor(x: _Ctx):
    p = x.info.res.params
    s = x.add(ics.Sensor(x.T("VS"), x.T("OUT"), x.T("GND"), p.get("slope", 0.01), p.get("offset", 0.0),
                         p.get("temp", 25.0)))
    x.control("temp", "temp", "Temperature (°C)", [s], s.temp, lo=-40.0, hi=125.0)


def b_currentsensor(x: _Ctx):
    t = (x.c.mpn + x.c.value).upper()
    sens = 0.066 if "30A" in t else (0.1 if "20A" in t else 0.185)
    ip, im = x.T("IP+"), x.T("IP-")
    x.add(Resistor(ip, im, 1.2e-3, name=f"{x.c.ref} conductor"))
    x.add(ics.CurrentSensorOut(ip, im, x.T("OUT"), x.T("VCC"), x.T("GND"), sens=sens))


def b_audioamp(x: _Ctx):
    inn, inp, gnd = x.T("IN-"), x.T("IN+"), x.T("GND")
    x.add(Resistor(inn, gnd, 50e3, name=f"{x.c.ref} input"))
    x.add(Resistor(inp, gnd, 50e3, name=f"{x.c.ref} input"))
    amp = x.add(ics.AudioAmp(inn, inp, gnd, x.T("OUT"), x.T("VS")))
    g1, g8 = (x.T("GAIN1", False), x.T("GAIN8", False))
    amp.gain_pins = (g1, g8)


def _opto_led(x: _Ctx):
    ks = x.internal("ks")
    k = x.T("K")
    _diode(x, x.T("A"), ks, dict(is_=6e-14, n=1.8, rs=1.0, bv=6.0, imax=0.06))
    x.add(Resistor(ks, k, 1.0, name=f"{x.c.ref} LED sense"))
    return ks, k


def b_opto(x: _Ctx):
    ks, k = _opto_led(x)
    x.add(ics.OptoOutput(ks, k, x.T("C"), x.T("E"), ctr=x.info.res.params.get("ctr", 1.0)))


def b_opto_switch(x: _Ctx):
    p = x.info.res.params
    ks, k = _opto_led(x)
    x.add(ics.SensedSwitch([(x.T("S1"), x.T("S2"))], [[], [0]], p.get("i_on", 5e-3), p.get("i_off", 2e-3),
                           sense=(ks, k), r_on=30.0))


def b_relay(x: _Ctx):
    p = x.info.res.params
    mid = x.internal("coil")
    x.add(Resistor(x.T("COIL1"), mid, p["r"], name=f"{x.c.ref} coil"))
    ind = x.add(Inductor(mid, x.T("COIL2"), p["l"], name=f"{x.c.ref} coil"))
    contacts, nc, no = [], [], []
    for pole in (1, 2):
        if not x.has(f"COM{pole}"):
            continue
        com = x.T(f"COM{pole}")
        if x.has(f"NC{pole}"):
            nc.append(len(contacts))
            contacts.append((com, x.T(f"NC{pole}")))
        if x.has(f"NO{pole}"):
            no.append(len(contacts))
            contacts.append((com, x.T(f"NO{pole}")))
    inom = p["vcoil"] / p["r"]
    x.add(ics.SensedSwitch(contacts, [nc, no], 0.75 * inom, 0.1 * inom, inductor=ind))


def b_switch(x: _Ctx):
    p = x.info.res.params
    if "dip" in p:
        for i, (a, b) in enumerate(p["dip"], start=1):
            sw = x.add(Switch([(x.pad(a), x.pad(b))], [[], [0]], name=f"{x.c.ref}.{i}"))
            x.control("toggle", f"sw{i}", f"{x.c.ref} switch {i}", [sw], 0, options=["off", "on"])
        return
    if p.get("encoder"):
        pads = set(x.c.footprint.pad_numbers())
        if {"S1", "S2"} <= pads:
            sw = x.add(Switch([(x.pad("S1"), x.pad("S2"))], [[], [0]], name=f"{x.c.ref} push", momentary=True))
            x.control("momentary", "push", f"{x.c.ref} push", [sw], 0, options=["released", "pressed"])
        if {"A", "B", "C"} <= pads:
            c = x.pad("C")
            q = x.add(Switch([(x.pad("A"), c), (x.pad("B"), c)], [[], [0], [0, 1], [1]], name=f"{x.c.ref} A/B"))
            x.control("encoder", "rotate", f"{x.c.ref} rotate", [q], 0)
        return
    contacts = [(x.pad(a), x.pad(b)) for a, b in p["contacts"]]
    sw = x.add(Switch(contacts, p["positions"], momentary=p.get("momentary", False), state=p.get("state", 0)))
    kind = "momentary" if p.get("momentary") else "toggle"
    x.control(kind, "sw", x.c.ref, [sw], sw.state, options=p.get("labels", []))


def b_pot(x: _Ctx):
    p = x.info.res.params
    pots = [x.add(Potentiometer(x.T("1"), x.T("W"), x.T("3"), p.get("r", 10e3), p.get("taper", "B"), 0.5))]
    if x.has("W2"):
        pots.append(x.add(Potentiometer(x.T("4"), x.T("W2"), x.T("6"), p.get("r", 10e3), p.get("taper", "B"), 0.5)))
    x.control("pot", "pos", f"{x.c.ref} {x.c.value}", pots, 0.5)


def b_battery(x: _Ctx):
    p = x.info.res.params
    mid = x.internal("cell")
    src = x.add(VoltageSource(mid, x.T("-"), p["v"], ramp=1e-4, name=f"{x.c.ref} battery"))
    x.add(Resistor(mid, x.T("+"), p.get("r", 0.5), name=f"{x.c.ref} internal resistance"))
    x.control("plug", "plug", f"{x.c.ref} battery inserted", [src], 1, options=["removed", "inserted"])


def _net_voltage(x: _Ctx, pad: str) -> float | None:
    net = x.c.pad_nets.get(pad)
    return parse_voltage(net) if net else None


def b_dcjack(x: _Ctx):
    p = x.info.res.params
    centre, sleeve = x.T("CENTRE"), x.T("SLEEVE")
    neg_centre = p.get("centre_negative", False)
    if centre == 0 and sleeve != 0:
        neg_centre = True
    elif sleeve == 0 and centre != 0:
        neg_centre = False
    plus, minus = (sleeve, centre) if neg_centre else (centre, sleeve)
    plus_pad = "2" if neg_centre else "1"
    v = p.get("v") or _net_voltage(x, plus_pad) or p.get("default", 9.0)
    mid = x.internal("adapter")
    src = x.add(VoltageSource(mid, minus, v, ramp=1e-4, name=f"{x.c.ref} adapter"))
    x.add(Resistor(mid, plus, 0.1, name=f"{x.c.ref} adapter"))
    devs = [src]
    if x.has("SWITCH"):
        sw = x.add(Switch([(sleeve, x.T("SWITCH"))], [[0], []], name=f"{x.c.ref} switch"))
        sw.plug_states = [0, 1]
        devs.append(sw)
    x.control("plug", "plug", f"{x.c.ref} {v:g} V adapter", devs, 1, options=["unplugged", "plugged in"])
    x.info.note = f"{v:g} V {'centre-negative' if neg_centre else 'centre-positive'} adapter"


def b_jack(x: _Ctx):
    pins = x.info.res.pins
    contacts, unplugged, plugged = [], [], []
    for main, sw in (("T", "TN"), ("R", "RN"), ("S", "SN")):
        if main in pins and sw in pins:
            unplugged.append(len(contacts))
            contacts.append((x.T(main), x.T(sw)))
    if "R" in pins and "S" in pins:  # a mono plug bridges ring and sleeve (the classic battery switch)
        plugged.append(len(contacts))
        contacts.append((x.T("R"), x.T("S")))
    if not contacts:
        x.info.status = "connection"
        return
    # a jack whose normalling contact carries a signal (an effects loop's RETURN normalled to SEND) passes it through
    # with nothing plugged in; an input jack (or one that only grounds its tip when empty) starts with a plug in it
    nets = x.c.pad_nets
    normalled = any(nets.get(m) and nets.get(s) and not is_ground_net(nets[s])
                    for m, s in (("T", "TN"), ("R", "RN"), ("S", "SN")) if m in pins and s in pins)
    state = 0 if normalled and nets.get("T") != "IN" else 1
    sw = x.add(Switch(contacts, [unplugged, plugged], state=state, name=f"{x.c.ref} contacts"))
    x.control("plug", "plug", f"{x.c.ref} jack", [sw], state, options=["unplugged", "plugged in"])


def b_usb(x: _Ctx):
    mid = x.internal("vbus")
    src = x.add(VoltageSource(mid, x.T("GND"), 5.0, ramp=1e-4, name=f"{x.c.ref} USB host"))
    x.add(Resistor(mid, x.T("VBUS"), 0.2, name=f"{x.c.ref} cable"))
    x.control("plug", "plug", f"{x.c.ref} USB cable", [src], 1, options=["unplugged", "plugged in"])


def b_buzzer(x: _Ctx):
    x.add(Resistor(x.T("+"), x.T("-"), x.info.res.params.get("r", 100.0)))


def b_addressable(x: _Ctx):
    x.add(Resistor(x.T("VDD"), x.T("VSS"), 5e3, name=f"{x.c.ref} quiescent"))
    x.info.note = "addressable LED: power only (its data input is not decoded)"
    try:
        from .avr import bridge
        bridge.attach_addressable(x)
    except (ImportError, AttributeError):
        pass


def b_uln(x: _Ctx):
    """Darlington array: 2.7k base resistor, Darlington pair to the common emitter, flyback diode to COM."""
    gnd = x.T("GND")
    com = x.T("COM", required=False)
    kw = dict(pol=1, is_=1e-13, br=4.0, vaf=100.0, imax=0.5, pmax=1.0)
    for i in range(1, x.info.res.params.get("n", 7) + 1):
        if not x.has(f"IN{i}"):
            continue
        b, out = x.internal(f"b{i}"), x.T(f"OUT{i}")
        mid = x.internal(f"e{i}")
        x.add(Resistor(x.T(f"IN{i}"), b, 2.7e3, name=f"{x.c.ref} R{i}"))
        x.add(BJT(out, b, mid, bf=40.0, **kw))
        x.add(BJT(out, mid, gnd, bf=40.0, **kw))
        x.add(Resistor(b, mid, 7.2e3, name=f"{x.c.ref} Rbe{i}"))
        x.add(Resistor(mid, gnd, 3e3, name=f"{x.c.ref} Rbe{i}"))
        _diode(x, out, com, dict(is_=1e-12, n=1.5, rs=0.5, imax=0.5))


def b_logic(x: _Ctx):
    from . import logic
    logic.build(x)


def b_mcu(x: _Ctx):
    from .avr import bridge
    bridge.build(x)


def b_tube(x: _Ctx):
    """Triode sections (with their plate-grid capacitance) or a pentode / beam tetrode."""
    from .tubes import Pentode, Triode, model_for
    p = x.info.res.params
    kind, prm = model_for(p["tube"])
    ref = x.c.ref
    pins = x.info.res.pins

    def wired(term):
        return any(x.c.pad_nets.get(pad) for pad in pins.get(term, []))

    if kind == "triode":
        prm, cgp = prm
        if p.get("sections") == 2:
            sections = (("PA", "GA", "KA", "A"), ("PB", "GB", "KB", "B"))
        else:  # a single triode (6C4) uses the pentode pin names
            sections = (("A", "G1", "K", ""),)
        used = []
        for P, G, K, sfx in sections:
            if not wired(P):  # an unused section (plate not connected)
                continue
            plate, grid, cath = x.T(P), x.T(G), x.T(K)
            x.add(Triode((plate, grid, cath), prm, name=f"{ref}{sfx}", pa_max=p.get("pa_max", 1.0)))
            x.add(Capacitor(grid, plate, cgp, name=f"{ref}{sfx} Cgp"))
            used.append(sfx or ref)
        if p.get("sections") == 2 and len(used) == 1:
            x.info.note = f"section {'B' if used == ['A'] else 'A'} unused"
    else:
        x.add(Pentode((x.T("A"), x.T("G2"), x.T("G1"), x.T("K")), prm, name=ref, pa_max=p.get("pa_max", 12.0)))


def b_rectifier(x: _Ctx):
    """Rectifier tube: two vacuum diodes (only used when the supply is not replaced by its DC model)."""
    k = x.T("K", required=False) if x.has("K") else x.T("HK")
    for a in ("A1", "A2"):
        if x.has(a):
            _diode(x, x.T(a), k, dict(is_=1e-6, n=6.0, rs=150.0, imax=0.3))


def b_bridge(x: _Ctx):
    p = x.info.res.params
    plus, minus = x.T("+"), x.T("-")
    for ac in ("AC1", "AC2"):
        n = x.T(ac)
        _diode(x, n, plus, p)
        _diode(x, minus, n, p)


BUILDERS = {
    "resistor": b_resistor, "resistor_array": b_resistor_array, "capacitor": b_capacitor, "inductor": b_inductor,
    "link": b_link, "diode": b_diode, "diodes": b_diodes, "led": b_led, "leds": b_leds, "bjt": b_bjt, "fet": b_fet,
    "jfet": b_jfet, "opamp": b_opamp, "comparator": b_comparator, "timer555": b_timer555, "regulator": b_regulator,
    "shuntref": b_shuntref, "zener_ref": b_zener_ref, "sensor": b_sensor, "currentsensor": b_currentsensor,
    "audioamp": b_audioamp, "opto": b_opto, "opto_switch": b_opto_switch, "relay": b_relay, "switch": b_switch,
    "pot": b_pot, "battery": b_battery, "dcjack": b_dcjack, "jack": b_jack, "usb": b_usb, "buzzer": b_buzzer,
    "addressable": b_addressable, "logic": b_logic, "mcu": b_mcu, "uln": b_uln, "tube": b_tube,
    "rectifier": b_rectifier, "bridge": b_bridge,
}


# --------------------------------------------------------------------------- sources

SUPPLY_DEFAULTS = {"VCC": 5.0, "VDD": 5.0, "VBUS": 5.0, "USB": 5.0, "VIN": 9.0, "V+": 9.0, "+V": 9.0, "PWR": 5.0,
                   "VPP": 12.0, "VBAT": 3.7, "BAT": 3.7, "VEE": -5.0, "V-": -9.0, "-V": -9.0}
CONNECTOR_PREFIXES = ("J", "P", "CN", "CON", "X", "TP", "W", "CONN", "HDR", "PWR")


def supply_voltage(net: str) -> float | None:
    n = (net or "").upper().lstrip("/").strip()
    neg = n.startswith("-") or n.startswith("NEG") or n.endswith("NEG")
    v = parse_voltage(n)
    if v is not None and v > 0:
        return -v if neg else v
    key = re.sub(r"[_\s]", "", n)
    for k, dv in SUPPLY_DEFAULTS.items():
        if key == k or key.startswith(k) and k not in ("V+", "V-", "+V", "-V"):
            return dv
    return None


def auto_sources(project: Project, ck: BoardCircuit) -> list[dict]:
    """Guess the bench supplies: nets with a voltage-like name that leave the board through a connector.

    Amplifier boards get their rectified supplies instead (see ``ampboard``), plus a test tone at IN."""
    hw = getattr(ck, "amp", None)
    if hw is not None and hw.supplies:
        out = [dict(s) for s in hw.supplies if s["net"] in ck.net_node]
        if "IN" in ck.net_node:
            out.append({"net": "IN", "kind": "sine", "freq": 220.0, "amp": 0.1, "offset": 0.0, "r": 10e3,
                        "enabled": True, "auto": True, "label": "guitar (220 Hz test tone)"})
        return out
    driven = set()
    reg_out = set()
    connector_nets: dict[str, str] = {}
    for c in project.components:
        info = ck.parts.get(c.uid)
        if info is None:
            continue
        kind = info.res.kind
        if kind in ("battery", "dcjack", "usb"):
            driven.update(n for n in c.pad_nets.values() if n)
        if kind == "mcu" and info.res.params.get("module") == "nano":  # powered by its own USB socket
            driven.update(c.pad_nets[p] for p in info.res.pins.get("5V", []) if c.pad_nets.get(p))
        if kind in ("regulator",):
            for pad in info.res.pins.get("OUT", []):
                if c.pad_nets.get(pad):
                    reg_out.add(c.pad_nets[pad])
        pre = re.match(r"[A-Za-z]+", c.ref or "")
        pre = pre.group(0).upper() if pre else ""
        if kind == "none" and pre in CONNECTOR_PREFIXES:
            for net in c.pad_nets.values():
                if net:
                    connector_nets.setdefault(net, c.value or "")
    out = []
    nets = [n for n in project.nets() if not is_ground_net(n) and n in ck.net_node]
    for net in nets:
        if net in driven or net in reg_out:
            continue
        v = supply_voltage(net)
        if net in connector_nets:
            v = supply_voltage(net) if supply_voltage(net) is not None else None
            cv = parse_voltage(connector_nets[net])
            if v is None and cv is not None and len([n for n in connector_nets if n in nets]) <= 2:
                v = cv
            elif v is not None and cv is not None and parse_voltage(net) is None:
                v = cv
            if v is not None:
                out.append({"net": net, "kind": "dc", "v": v, "r": 0.05, "enabled": True, "auto": True,
                            "label": f"bench supply via {connector_nets[net] or 'connector'}"})
    if not out and not driven:
        cands = [(supply_voltage(n), n) for n in nets if supply_voltage(n) is not None and n not in reg_out]
        if cands:
            v, net = max(cands, key=lambda t: abs(t[0]))
            out.append({"net": net, "kind": "dc", "v": v, "r": 0.05, "enabled": True, "auto": True,
                        "label": "bench supply"})
    if project.pedal and "IN" in ck.net_node:
        out.append({"net": "IN", "kind": "sine", "freq": 220.0, "amp": 0.1, "offset": 0.0, "r": 10e3,
                    "enabled": True, "auto": True, "label": "guitar (220 Hz test tone)"})
    return out


def _wave(s: dict) -> Waveform:
    k = s.get("kind", "dc")
    if k == "dc":
        return Waveform("dc", v=float(s.get("v", 5.0)))
    if k == "sine":
        return Waveform("sine", freq=float(s.get("freq", 1e3)), amp=float(s.get("amp", 1.0)),
                        offset=float(s.get("offset", 0.0)))
    if k == "square":
        return Waveform("square", freq=float(s.get("freq", 1e3)), lo=float(s.get("lo", 0.0)),
                        hi=float(s.get("hi", s.get("v", 5.0))), duty=float(s.get("duty", 0.5)))
    if k == "pulse":
        return Waveform("pulse", **{k2: float(v) for k2, v in s.items() if k2 in ("v1", "v2", "delay", "rise", "fall",
                                                                                    "width", "period")})
    if k == "samples":
        return Waveform("samples", data=s.get("data", []), rate=float(s.get("rate", 48000.0)),
                        gain=float(s.get("gain", 1.0)), loop=s.get("loop", False))
    return Waveform("dc", v=0.0)


def add_sources(project: Project, ck: BoardCircuit, cfg: list[dict] | None = None) -> None:
    if cfg is None:
        cfg = (project.sim or {}).get("sources")
    auto = cfg is None
    if cfg is None:
        cfg = auto_sources(project, ck)
    for s in cfg:
        net = s.get("net")
        node = ck.net_node.get(net)
        if node is None:
            ck.warnings.append(f"Source net '{net}' is not on the board.")
            continue
        if node == 0:
            ck.warnings.append(f"Source net '{net}' is shorted to ground.")
            continue
        r = float(s.get("r", 0.05))
        target = node
        if r > 0:
            target = ck.internal(f"src {net}")
            ck.add(Resistor(target, node, r, name=f"supply {net}"))
        dc = s.get("kind", "dc") == "dc"
        src = ck.add(VoltageSource(target, 0, _wave(s), name=f"supply {net}", ramp=1e-4 if dc else 0.0))
        src.enabled = bool(s.get("enabled", True))
        label = s.get("label") or (f"{fmt_eng(s.get('v', 0), 'V')} supply" if dc else s.get("kind"))
        info = SourceInfo(net, s.get("kind", "dc"), dict(s), src, label, s.get("auto", auto))
        ck.sources.append(info)
        ctl = Control(f"src:{net}:{len(ck.sources)}", "", net, "source", f"{net}: {label}", [src],
                      1 if src.enabled else 0, options=["off", "on"])
        ck.controls.append(ctl)


# --------------------------------------------------------------------------- top level

def build_circuit(project: Project, mode: str = "design", sources: list[dict] | None = None) -> BoardCircuit:
    """``mode``: 'design' (nets as drawn) or 'built' (copper as routed)."""
    ck = BoardCircuit(project, mode)
    pad_node = _node_mapper(project, ck, mode)
    overrides = (project.sim or {}).get("parts", {})
    resolved = {c.uid: resolve(c, overrides.get(c.uid)) for c in project.components}
    hw = None
    try:  # amplifier boards: transformers, speaker and supplies that live off the board
        hw = ampboard.analyse(project, resolved)
    except Exception as e:  # never let the amp extras stop the simulation of the board itself
        ck.warnings.append(f"Amplifier hardware not modelled: {e}")
    ck.amp = hw
    for c in project.components:
        res = resolved[c.uid]
        info = PartInfo(c.uid, c.ref, c.value, res, note=res.note)
        ck.parts[c.uid] = info
        # every connected pad gets a node, so nets show up even if only passive parts touch them
        for number in c.footprint.pad_numbers():
            if number and c.pad_nets.get(number):
                pad_node(c, number)
        if res.kind in ("none",):
            info.status = "connection"
            continue
        if hw is not None and c.uid in hw.replaced:
            info.status = "connection"
            info.note = hw.replaced[c.uid]
            continue
        if res.kind in ("unsupported", "excluded"):
            info.status = res.kind
            continue
        if res.kind == "crystal":
            info.status = "connection"
            info.note = "crystal: clocks the microcontroller it is wired to"
            continue
        builder = BUILDERS.get(res.kind)
        if builder is None:
            info.status = "unsupported"
            info.note = f"no builder for {res.kind}"
            continue
        try:
            builder(_Ctx(ck, c, info, pad_node))
        except Exception as e:  # a bad pin map must never stop the whole simulation
            info.status = "error"
            info.note = str(e)
            ck.warnings.append(f"{c.ref}: {e}")
    _post_process(ck)
    if hw is not None:
        _add_amp_hardware(project, ck, hw)
    add_sources(project, ck, sources)
    if mode == "design":
        try:
            from ..model.connectivity import get_connectivity
            unr = get_connectivity(project).unrouted_count()
            if unr:
                ck.warnings.append(f"{unr} connection(s) are not routed yet; simulating the netlist as designed.")
        except Exception:
            pass
    else:
        try:
            from ..model.connectivity import get_connectivity
            for s in get_connectivity(project).shorts:
                ck.warnings.append(f"Short circuit between {', '.join(s.nets)} (simulated as built).")
        except Exception:
            pass
    if not ck.ground_nets:
        # no GND net: reference the circuit to the negative side of the first source (battery, jack, USB...)
        ref = next((d.nodes[1] for d in ck.devices if isinstance(d, VoltageSource) and d.nodes[1] != 0), None)
        if ref is not None:
            ck.add(Resistor(ref, 0, LINK_R, name="ground reference"))
            ck.warnings.append(f"No GND net: voltages are measured from {ck.node_label(ref)}.")
        else:
            ck.warnings.append("No ground net (GND) found: voltages are relative to an arbitrary reference.")
    if not ck.sources and not any(i.res.kind in ("battery", "dcjack", "usb") for i in ck.parts.values()):
        ck.warnings.append("No power source: add a supply in the Simulation panel (net and voltage).")
    return ck


def _add_amp_hardware(project: Project, ck: BoardCircuit, hw) -> None:
    def node_of(net: str) -> int:
        if net in ck.net_node:
            return ck.net_node[net]
        if is_ground_net(net):
            return 0
        n = ck.node(("net", net), net)
        ck.net_node[net] = n
        ck.node_nets.setdefault(n, set()).add(net)
        return n

    try:
        if hw.ot is not None and hw.ot.get("polarity") is None and ampboard.forced_polarity() is None:
            hw.ot["polarity"] = ampboard.nfb_polarity(project, hw)
        ampboard.add_hardware(ck, hw, node_of)
    except Exception as e:
        ck.warnings.append(f"Amplifier hardware not modelled: {e}")


def _post_process(ck: BoardCircuit) -> None:
    """Cross-part fix-ups: LM386 gain bypass detection, WS2812 chains linked to the MCU pin driving them."""
    if ck.__dict__.get("ws2812"):
        from .avr.bridge import link_addressable
        link_addressable(ck)
    caps = [d for d in ck.devices if isinstance(d, Capacitor)]
    for d in ck.devices:
        if isinstance(d, ics.AudioAmp) and getattr(d, "gain_pins", None):
            g1, g8 = d.gain_pins
            if g1 == g8 or any({c.nodes[0], c.nodes[1]} == {g1, g8} for c in caps):
                d.gain = 200.0


__all__ = ["build_circuit", "BoardCircuit", "PartInfo", "Control", "SourceInfo", "supply_voltage", "auto_sources",
           "LED_TYPES"]
