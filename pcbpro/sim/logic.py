"""Behavioural digital logic: 74HC / 74LVC / CD4000 gates, flip-flops, counters, shift registers, decoders, analog
multiplexers and the L293D half-bridges.

Each chip is one event device. Its inputs are read against thresholds relative to the chip's own supply pins (with
hysteresis; Schmitt-trigger parts have a wide window), the chip function runs on every input change (clocked parts
look at edges), and each output is a push-pull stage (supply rail behind R_out) or high impedance.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from .devices import R_OFF, EventDevice, stamp_emf, stamp_g

FAMILIES = {  # output resistance, schmitt window (fraction of VCC), minimum supply
    "HC": (50.0, 0.0, 1.8),
    "LVC": (25.0, 0.0, 1.4),
    "CD": (400.0, 0.0, 2.8),
    "L293": (1.0, 0.0, 4.0),
}


@dataclass
class Spec:
    name: str
    family: str
    pins: list[str]  # logic pins (readable and drivable)
    fn: Callable  # (levels: dict, prev: dict, regs: tuple) -> (outs: dict pin -> 0/1/None, regs)
    pinmaps: dict  # package -> {terminal: pad}
    schmitt: set = field(default_factory=set)
    regs: tuple = ()
    switches: Callable | None = None  # (levels, regs) -> list of (terminal, terminal) closed analog switches
    supply: dict = field(default_factory=dict)  # output pin -> high-side supply terminal (default VCC)
    drop: tuple = (0.0, 0.0)  # high / low output stage drop (V)
    analog: list = field(default_factory=list)  # analog terminals (mux channels)


def _rise(prev, cur, p):
    return cur.get(p, 0) and not prev.get(p, 0)


def _fall(prev, cur, p):
    return prev.get(p, 0) and not cur.get(p, 0)


# --------------------------------------------------------------------------- gates

QUAD14 = {"1A": "1", "1B": "2", "1Y": "3", "2A": "4", "2B": "5", "2Y": "6", "GND": "7", "3Y": "8", "3A": "9",
          "3B": "10", "4Y": "11", "4A": "12", "4B": "13", "VCC": "14"}
NOR14 = {"1Y": "1", "1A": "2", "1B": "3", "2Y": "4", "2A": "5", "2B": "6", "GND": "7", "3A": "8", "3B": "9",
         "3Y": "10", "4A": "11", "4B": "12", "4Y": "13", "VCC": "14"}
CD4011_14 = {"1A": "1", "1B": "2", "1Y": "3", "2Y": "4", "2A": "5", "2B": "6", "GND": "7", "3A": "8", "3B": "9",
             "3Y": "10", "4Y": "11", "4A": "12", "4B": "13", "VCC": "14"}
HEX14 = {"1A": "1", "1Y": "2", "2A": "3", "2Y": "4", "3A": "5", "3Y": "6", "GND": "7", "4Y": "8", "4A": "9",
         "5Y": "10", "5A": "11", "6Y": "12", "6A": "13", "VCC": "14"}


def _gates(op: Callable, n: int) -> Callable:
    def fn(lv, prev, regs):
        return {f"{i}Y": int(op(lv.get(f"{i}A", 0), lv.get(f"{i}B", 0))) for i in range(1, n + 1)}, regs
    return fn


def _inverters(lv, prev, regs):
    return {f"{i}Y": int(not lv.get(f"{i}A", 0)) for i in range(1, 7)}, regs


def _gate_pins(n=4):
    return [f"{i}{s}" for i in range(1, n + 1) for s in "ABY"]


NAND = lambda a, b: not (a and b)  # noqa: E731
AND = lambda a, b: a and b  # noqa: E731
OR = lambda a, b: a or b  # noqa: E731
NOR = lambda a, b: not (a or b)  # noqa: E731
XOR = lambda a, b: a != b  # noqa: E731
HEX_PINS = [f"{i}{s}" for i in range(1, 7) for s in "AY"]
SCHMITT_GATES = {f"{i}{s}" for i in range(1, 5) for s in "AB"}
SCHMITT_HEX = {f"{i}A" for i in range(1, 7)}


# --------------------------------------------------------------------------- flip-flops and counters

def _hc74(lv, prev, regs):
    q1, q2 = regs
    out = []
    for i, q in ((1, q1), (2, q2)):
        clr, pre = not lv.get(f"{i}CLR", 1), not lv.get(f"{i}PRE", 1)
        if clr or pre:
            q = int(pre and not clr) if not (clr and pre) else 1
            out.append((q, int(not q) if not (clr and pre) else 1))
        else:
            if _rise(prev, lv, f"{i}CLK"):
                q = int(lv.get(f"{i}D", 0))
            out.append((q, int(not q)))
    (a, an), (b, bn) = out
    return {"1Q": a, "1QN": an, "2Q": b, "2QN": bn}, (a, b)


HC74 = {"1CLR": "1", "1D": "2", "1CLK": "3", "1PRE": "4", "1Q": "5", "1QN": "6", "GND": "7", "2QN": "8", "2Q": "9",
        "2PRE": "10", "2CLK": "11", "2D": "12", "2CLR": "13", "VCC": "14"}


def _cd4013(lv, prev, regs):
    q1, q2 = regs
    res = []
    for i, q in ((1, q1), (2, q2)):
        s, r = lv.get(f"{i}SET", 0), lv.get(f"{i}RESET", 0)
        if s or r:
            q = int(s and not r) if not (s and r) else 1
            res.append((q, 1 if (s and r) else int(not q)))
        else:
            if _rise(prev, lv, f"{i}CLK"):
                q = int(lv.get(f"{i}D", 0))
            res.append((q, int(not q)))
    (a, an), (b, bn) = res
    return {"1Q": a, "1QN": an, "2Q": b, "2QN": bn}, (a, b)


CD4013 = {"1Q": "1", "1QN": "2", "1CLK": "3", "1RESET": "4", "1D": "5", "1SET": "6", "GND": "7", "2SET": "8",
          "2D": "9", "2RESET": "10", "2CLK": "11", "2QN": "12", "2Q": "13", "VCC": "14"}


def _cd4017(lv, prev, regs):
    (count,) = regs
    if lv.get("RESET", 0):
        count = 0
    elif not lv.get("INH", 0) and _rise(prev, lv, "CLK"):
        count = (count + 1) % 10
    outs = {f"Q{i}": int(count == i) for i in range(10)}
    outs["CO"] = int(count < 5)
    return outs, (count,)


CD4017 = {"Q5": "1", "Q1": "2", "Q0": "3", "Q2": "4", "Q6": "5", "Q7": "6", "Q3": "7", "GND": "8", "Q8": "9",
          "Q4": "10", "Q9": "11", "CO": "12", "INH": "13", "CLK": "14", "RESET": "15", "VCC": "16"}


def _cd4060(lv, prev, regs):
    (count,) = regs
    x = lv.get("PI", 0)
    if lv.get("RESET", 0):
        count = 0
    elif _fall(prev, lv, "PI"):
        count = (count + 1) % (1 << 14)
    outs = {f"Q{n}": (count >> (n - 1)) & 1 for n in (4, 5, 6, 7, 8, 9, 10, 12, 13, 14)}
    outs["PON"] = int(not x) if not lv.get("RESET", 0) else 1  # first inverter (pin 10)
    outs["PO"] = int(x) if not lv.get("RESET", 0) else 0  # second inverter (pin 9)
    return outs, (count,)


CD4060 = {"Q12": "1", "Q13": "2", "Q14": "3", "Q6": "4", "Q5": "5", "Q7": "6", "Q4": "7", "GND": "8", "PO": "9",
          "PON": "10", "PI": "11", "RESET": "12", "Q9": "13", "Q8": "14", "Q10": "15", "VCC": "16"}


# --------------------------------------------------------------------------- shift registers and decoders

def _hc595(lv, prev, regs):
    shift, latch = regs
    if not lv.get("SRCLR", 1):
        shift = 0
    elif _rise(prev, lv, "SRCLK"):
        shift = ((shift << 1) | int(lv.get("SER", 0))) & 0xFF
    if _rise(prev, lv, "RCLK"):
        latch = shift
    oe = not lv.get("OE", 0)
    outs = {f"Q{c}": ((latch >> i) & 1 if oe else None) for i, c in enumerate("ABCDEFGH")}
    outs["QH2"] = (shift >> 7) & 1
    return outs, (shift, latch)


HC595 = {"QB": "1", "QC": "2", "QD": "3", "QE": "4", "QF": "5", "QG": "6", "QH": "7", "GND": "8", "QH2": "9",
         "SRCLR": "10", "SRCLK": "11", "RCLK": "12", "OE": "13", "SER": "14", "QA": "15", "VCC": "16"}


def _hc165(lv, prev, regs):
    (reg,) = regs
    if not lv.get("SHLD", 1):
        reg = sum(int(lv.get(c, 0)) << i for i, c in enumerate("ABCDEFGH"))
    elif not lv.get("INH", 0) and _rise(prev, lv, "CLK"):
        reg = ((reg << 1) | int(lv.get("SER", 0))) & 0xFF
    qh = (reg >> 7) & 1
    return {"QH": qh, "QHN": int(not qh)}, (reg,)


HC165 = {"SHLD": "1", "CLK": "2", "E": "3", "F": "4", "G": "5", "H": "6", "QHN": "7", "GND": "8", "QH": "9",
         "SER": "10", "A": "11", "B": "12", "C": "13", "D": "14", "INH": "15", "VCC": "16"}


def _hc138(lv, prev, regs):
    en = (not lv.get("E1", 0)) and (not lv.get("E2", 0)) and lv.get("E3", 0)
    sel = lv.get("A0", 0) | (lv.get("A1", 0) << 1) | (lv.get("A2", 0) << 2)
    return {f"Y{i}": int(not (en and sel == i)) for i in range(8)}, regs


HC138 = {"A0": "1", "A1": "2", "A2": "3", "E1": "4", "E2": "5", "E3": "6", "Y7": "7", "GND": "8", "Y6": "9",
         "Y5": "10", "Y4": "11", "Y3": "12", "Y2": "13", "Y1": "14", "Y0": "15", "VCC": "16"}


def _hc245(lv, prev, regs):
    if lv.get("OE", 0):
        return {}, regs
    outs = {}
    for i in range(1, 9):
        if lv.get("DIR", 0):
            outs[f"B{i}"] = int(lv.get(f"A{i}", 0))
        else:
            outs[f"A{i}"] = int(lv.get(f"B{i}", 0))
    return outs, regs


HC245 = {"DIR": "1", **{f"A{i}": str(i + 1) for i in range(1, 9)}, "GND": "10",
         **{f"B{i}": str(19 - i) for i in range(1, 9)}, "OE": "19", "VCC": "20"}


def _mux4051(lv, prev, regs):
    return {}, regs


def _mux4051_switches(lv, regs):
    if lv.get("E", 0):
        return []
    sel = lv.get("S0", 0) | (lv.get("S1", 0) << 1) | (lv.get("S2", 0) << 2)
    return [("Z", f"Y{sel}")]


MUX4051 = {"Y4": "1", "Y6": "2", "Z": "3", "Y7": "4", "Y5": "5", "E": "6", "VEE": "7", "GND": "8", "S2": "9",
           "S1": "10", "S0": "11", "Y3": "12", "Y0": "13", "Y1": "14", "Y2": "15", "VCC": "16"}


def _l293(lv, prev, regs):
    outs = {}
    for en, pairs in (("EN12", ((1, "1A", "1Y"), (2, "2A", "2Y"))), ("EN34", ((3, "3A", "3Y"), (4, "4A", "4Y")))):
        for _, a, y in pairs:
            outs[y] = int(lv.get(a, 0)) if lv.get(en, 0) else None
    return outs, regs


L293D = {"EN12": "1", "1A": "2", "1Y": "3", "GND": ["4", "5", "12", "13"], "2Y": "6", "2A": "7", "VS": "8",
         "EN34": "9", "3A": "10", "3Y": "11", "4Y": "14", "4A": "15", "VCC": "16"}

LVC1G14 = {"1A": "2", "GND": "3", "1Y": "4", "VCC": "5"}
LVC1G08 = {"1A": "1", "1B": "2", "GND": "3", "1Y": "4", "VCC": "5"}


def _single(op):
    def fn(lv, prev, regs):
        return {"1Y": int(op(lv.get("1A", 0), lv.get("1B", 0)))}, regs
    return fn


# --------------------------------------------------------------------------- catalogue

def _q(name, fam, op, pm=QUAD14, schmitt=False):
    return Spec(name, fam, _gate_pins(), _gates(op, 4), {"14": pm}, SCHMITT_GATES if schmitt else set())


def _hex(name, fam, schmitt=False):
    return Spec(name, fam, HEX_PINS, _inverters, {"14": HEX14}, SCHMITT_HEX if schmitt else set())


SPECS: dict[str, Spec] = {}
for _s in (
        _q("74HC00", "HC", NAND), _q("74HC08", "HC", AND), _q("74HC32", "HC", OR), _q("74HC86", "HC", XOR),
        _q("74HC02", "HC", NOR, NOR14), _q("74HC132", "HC", NAND, schmitt=True),
        _hex("74HC04", "HC"), _hex("74HC14", "HC", True), _hex("74HCU04", "HC"),
        _q("CD4011", "CD", NAND, CD4011_14), _q("CD4093", "CD", NAND, CD4011_14, True),
        _q("CD4001", "CD", NOR, CD4011_14), _q("CD4081", "CD", AND, CD4011_14), _q("CD4071", "CD", OR, CD4011_14),
        _q("CD4070", "CD", XOR, CD4011_14), _hex("CD4069", "CD"), _hex("CD40106", "CD", True),
        Spec("74HC74", "HC", ["1CLR", "1D", "1CLK", "1PRE", "1Q", "1QN", "2QN", "2Q", "2PRE", "2CLK", "2D", "2CLR"],
             _hc74, {"14": HC74}, regs=(0, 0)),
        Spec("CD4013", "CD", ["1Q", "1QN", "1CLK", "1RESET", "1D", "1SET", "2SET", "2D", "2RESET", "2CLK", "2QN",
                              "2Q"], _cd4013, {"14": CD4013}, regs=(0, 0)),
        Spec("CD4017", "CD", [p for p in CD4017 if p not in ("GND", "VCC")], _cd4017, {"16": CD4017}, regs=(0,),
             schmitt={"CLK"}),
        Spec("CD4060", "CD", [p for p in CD4060 if p not in ("GND", "VCC")], _cd4060, {"16": CD4060}, regs=(0,),
             schmitt={"PI"}),
        Spec("74HC595", "HC", [p for p in HC595 if p not in ("GND", "VCC")], _hc595, {"16": HC595}, regs=(0, 0)),
        Spec("74HC165", "HC", [p for p in HC165 if p not in ("GND", "VCC")], _hc165, {"16": HC165}, regs=(0,)),
        Spec("74HC138", "HC", [p for p in HC138 if p not in ("GND", "VCC")], _hc138, {"16": HC138}),
        Spec("74HC245", "HC", [p for p in HC245 if p not in ("GND", "VCC")], _hc245, {"20": HC245}),
        Spec("74HC4051", "HC", ["E", "S0", "S1", "S2"], _mux4051, {"16": MUX4051}, switches=_mux4051_switches,
             analog=["Z"] + [f"Y{i}" for i in range(8)]),
        Spec("CD4051", "CD", ["E", "S0", "S1", "S2"], _mux4051, {"16": MUX4051}, switches=_mux4051_switches,
             analog=["Z"] + [f"Y{i}" for i in range(8)]),
        Spec("L293D", "L293", [p for p in L293D if p not in ("GND", "VCC", "VS")], _l293, {"16": L293D},
             supply={y: "VS" for y in ("1Y", "2Y", "3Y", "4Y")}, drop=(1.4, 1.2)),
        Spec("74LVC1G14", "LVC", ["1A", "1Y"], lambda lv, p, r: ({"1Y": int(not lv.get("1A", 0))}, r),
             {"SOT-23-5": LVC1G14}, {"1A"}),
        Spec("74LVC1G08", "LVC", ["1A", "1B", "1Y"], _single(AND), {"SOT-23-5": LVC1G08}),
):
    SPECS[_s.name] = _s
SPECS["74HC4067"] = None  # 16-channel mux: not modelled (24 pins)


def lookup(text: str) -> Spec | None:
    """'74HC595D' / 'SN74HC595N' / 'CD4017BE' / '74LVC1G14GW' -> Spec."""
    t = re.sub(r"[\s_-]", "", (text or "").upper())
    m = re.match(r"^(?:SN|MC|M|NL|HEF)?74(?:HCT|HCU|HC|AHCT|AHC|ACT|AC|LVC|LV|ALS|LS|F)?(1G\d+|\d{2,4})", t)
    if m:
        num = m.group(1)
        if num.startswith("1G"):
            return SPECS.get(f"74LVC{num}")
        fam = "HCU" if "74HCU" in t else ""
        if fam and SPECS.get(f"74HCU{num}"):
            return SPECS[f"74HCU{num}"]
        return SPECS.get(f"74HC{num}")
    m = re.match(r"^(?:CD|HEF|MC1|TC)?4(\d{3,4})(?:B|UB)?", t)
    if m and (t.startswith(("CD", "HEF", "MC1", "TC")) or len(t) <= 7):
        return SPECS.get(f"CD4{m.group(1)}")
    if t.startswith(("L293D", "L293")):
        return SPECS["L293D"]
    return None


# --------------------------------------------------------------------------- device

class LogicDevice(EventDevice):
    kind = "logic"

    def __init__(self, spec: Spec, term_nodes: dict, part=None, name=""):
        self.spec = spec
        self.tn = term_nodes
        order = ["VCC", "GND"] + [p for p in spec.pins if p in term_nodes] + [a for a in spec.analog if a in term_nodes]
        for extra in set(spec.supply.values()):
            if extra in term_nodes and extra not in order:
                order.append(extra)
        self.order = order
        self.idx = {t: i for i, t in enumerate(order)}
        super().__init__([term_nodes[t] for t in order], part, name)
        rout, _, vmin = FAMILIES[spec.family]
        self.rout, self.vmin = rout, vmin
        self.in_pins = [p for p in spec.pins if p in term_nodes]

    def initial_state(self):
        return (None, self.spec.regs, (), ())  # input levels unknown until the first evaluation

    def _levels(self, x, prev_levels):
        if prev_levels is None:
            prev_levels = tuple(0 for _ in self.spec.pins)
        g = float(x[self.tn["GND"]])
        vcc = float(x[self.tn["VCC"]]) - g
        lv = {}
        for p, pl in zip(self.spec.pins, prev_levels):
            n = self.tn.get(p)
            if n is None:
                continue
            v = float(x[n]) - g
            if p in self.spec.schmitt:
                hi, lo = 0.6 * vcc, 0.4 * vcc
            else:
                hi, lo = 0.52 * vcc, 0.48 * vcc
            lv[p] = int(v > (lo if pl else hi))
        return lv, vcc

    def next_state(self, x):
        prev_levels, regs, _, _ = self.state
        lv, vcc = self._levels(x, prev_levels)
        if vcc < self.vmin:
            return (None, self.spec.regs, (), ())
        if prev_levels is None:  # power-up: take the inputs as they are, no edges
            prev = dict(lv)
        else:
            prev = {p: l for p, l in zip(self.spec.pins, prev_levels)}
        outs, regs = self.spec.fn(lv, prev, regs)
        sw = tuple(self.spec.switches(lv, regs)) if self.spec.switches else ()
        levels = tuple(lv.get(p, 0) for p in self.spec.pins)
        return (levels, regs, tuple(sorted((k, v) for k, v in outs.items() if k in self.tn)), sw)

    def thresholds(self, x):
        prev_levels = self.state[0] or tuple(0 for _ in self.spec.pins)
        g = float(x[self.tn["GND"]])
        vcc = float(x[self.tn["VCC"]]) - g
        out = [vcc - self.vmin]
        for p, pl in zip(self.spec.pins, prev_levels):
            n = self.tn.get(p)
            if n is None:
                continue
            if p in self.spec.schmitt:
                th = (0.4 if pl else 0.6) * vcc
            else:
                th = (0.48 if pl else 0.52) * vcc
            out.append(float(x[n]) - g - th)
        return out

    def stamp_step(self, A, b, t, h, mode):
        _, _, outs, sw = self.state
        gnd = self.tn["GND"]
        g = 1.0 / self.rout
        dh, dl = self.spec.drop
        for pin, val in outs:
            n = self.tn[pin]
            if val is None:
                continue
            if val:
                stamp_emf(A, b, self.tn.get(self.spec.supply.get(pin, "VCC"), self.tn["VCC"]), n, g, dh)
            else:
                stamp_emf(A, b, n, gnd, g, dl)
        for a, c in sw:
            if a in self.tn and c in self.tn:
                stamp_g(A, self.tn[a], self.tn[c], 1.0 / 80.0)

    def currents(self, x):
        _, _, outs, sw = self.state
        cur = [0.0] * len(self.nodes)
        gnd = self.tn["GND"]
        dh, dl = self.spec.drop
        for pin, val in outs:
            if val is None:
                continue
            n = self.tn[pin]
            j = self.idx[pin]
            if val:
                sup_t = self.spec.supply.get(pin, "VCC")
                sup = self.tn.get(sup_t, self.tn["VCC"])
                i = (x[sup] - x[n] - dh) / self.rout
                cur[self.idx.get(sup_t, 0)] += i
                cur[j] -= i
            else:
                i = (x[n] - x[gnd] - dl) / self.rout
                cur[j] += i
                cur[1] -= i
        return cur

    def observe(self, x):
        _, regs, outs, _ = self.state
        return {"outs": dict(outs), "regs": regs, "p": self.power(x)}


def build(x) -> None:
    """Netlist builder for kind 'logic' (x is the netlist build context)."""
    spec = SPECS[x.info.res.params["chip"]]
    tn = {}
    for term in ["VCC", "GND"] + spec.pins + spec.analog + list(set(spec.supply.values())):
        if x.has(term):
            tn[term] = x.T(term)
    if "VCC" not in tn or "GND" not in tn:
        raise ValueError("supply pins not mapped")
    if "VEE" in x.info.res.pins:
        x.T("VEE")
    dev = LogicDevice(spec, tn, name=x.c.ref)
    x.add(dev)
