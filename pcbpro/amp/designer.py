"""Amp Designer: describe the amp you want and get a complete, working circuit with the numbers to build it.

Choose the instrument, tube or solid-state, the sound (voicing), the power stage and a few features. The designer
assembles a proven circuit from building blocks (gain stages, cathode follower, tone stack, phase inverter, power
stage, bias supply, rectifier and B+ filter chain, heater wiring), picks every value, and works out:

* operating points: B+ at each filter node, plate / cathode voltages, idle currents and power-tube dissipation;
* the transformers to buy: power transformer HV / heater / bias windings, output transformer impedance and power,
  choke, mains fuse;
* output power, loudness, the gain of every stage, and where the amp starts to break up on the volume knob;
* warnings and tips, the tone-stack response, and finally a placed (and routed) board with every net annotated so
  the high-voltage checks apply.

The power stages are tabulated, proven operating points (not curve fits); preamp DC is estimated with the linear
triode model I = Vb / (ra + Ra + mu Rk), good to about 20 %.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

import numpy as np

from . import gainstage as gs
from .builder import AmpDesign, C, CP, D, P, PADS, POT, R, TUBE
from .tonestack import PRESETS, ToneStack, response, response_db, stack_parts
from .tubes import TUBES

SQ2 = math.sqrt(2.0)
E12 = (1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2)
STD_UF = (10, 16, 22, 33, 47, 68, 100, 150, 220, 330, 470)  # stock electrolytic values


def e12(v: float) -> float:
    """Nearest E12 value."""
    if v <= 0:
        return 0.0
    d = 10 ** math.floor(math.log10(v))
    m = min(E12 + (10.0,), key=lambda e: abs(math.log(v / d / e)))
    return round(m * d, 6)


def fmt_r(ohms: float) -> str:
    """Resistor value as printed on schematics: 470R, 2R7, 4k7, 100k, 1M5."""
    def body(v: float, unit: str) -> str:
        if abs(v - round(v)) < 1e-6:
            return f"{int(round(v))}{unit}"
        whole = int(v)
        frac = f"{v - whole:.2f}"[2:].rstrip("0")
        return f"{whole}{unit}{frac}"
    if ohms >= 1e6:
        return body(ohms / 1e6, "M")
    if ohms >= 1e3:
        return body(ohms / 1e3, "k")
    return body(ohms, "R")


# plate current at which the data-sheet plate resistance is quoted; rp grows roughly as I^(-1/3) below it
RA_REF_MA = {"12AX7": 1.2, "12AT7": 10.0, "12AU7": 10.5, "12AY7": 3.0, "5751": 1.0, "ECC88": 15.0, "6SN7": 9.0,
             "6SL7": 2.3, "6C4": 10.5}


def _rp(tube: str, ia: float) -> float:
    """Plate resistance (ohms) of a triode at plate current ``ia`` (A)."""
    ref = RA_REF_MA.get(tube, 1.0) * 1e-3
    return TUBES[tube].ra_k * 1e3 * (ref / max(ia, 1e-5)) ** (1.0 / 3.0)


def e6(v: float) -> float:
    """Nearest E6 value (the series film and electrolytic caps come in)."""
    if v <= 0:
        return 0.0
    d = 10 ** math.floor(math.log10(v))
    m = min((1.0, 1.5, 2.2, 3.3, 4.7, 6.8, 10.0), key=lambda e: abs(math.log(v / d / e)))
    return float(f"{m * d:.3g}")


def fmt_c(farads: float) -> str:
    if farads >= 1e-6:
        v = farads * 1e6
        return f"{v:g}uF"
    if farads >= 1e-9:
        return f"{farads * 1e9:g}nF"
    return f"{farads * 1e12:g}pF"


def rpart(ohms: float, volts: float) -> str:
    """Resistor footprint key (wattage) for a resistor with ``volts`` across it: at most half its rating."""
    p = volts * volts / ohms if ohms > 0 else 0.0
    if p <= 0.12 and volts <= 240:
        return "res_small"
    if p <= 0.24 and volts <= 340:
        return "res"
    if p <= 0.48 and volts <= 490:
        return "res1w"
    if p <= 0.98 and volts <= 490:
        return "res2w"
    if p <= 1.45:
        return "res3w"
    if p <= 3.4:
        return "res5w"
    return "res15w"


# --------------------------------------------------------------------------- power stages

@dataclass(frozen=True)
class PowerOption:
    key: str
    label: str
    tube: str
    count: int
    bias: str  # cathode | fixed
    bplus: float  # B+ at the output transformer centre tap
    raa: float  # output transformer primary impedance (plate to plate for push-pull)
    ik_ma: float  # idle cathode current per tube (plate + screen)
    pout: float  # clean output power (W)
    rk: float = 0.0  # shared cathode resistor (cathode bias)
    vbias: float = 0.0  # grid bias (fixed bias)
    screen_r: float = 1000.0
    screen_part: str = "res1w"
    stopper: float = 1500.0
    grid_leak: float = 220e3
    rect: str = "5AR4"
    vsat: float = 50.0

    @property
    def pp(self) -> bool:
        return self.count >= 2

    @property
    def bias_text(self) -> str:
        return "cathode (self) bias" if self.bias == "cathode" else "fixed bias, adjustable"


POWER = {o.key: o for o in [
    PowerOption("se_6v6", "5 W  -  single-ended 6V6 (Champ)", "6V6GT", 1, "cathode", 330, 5000, 40, 4.5, rk=470,
                screen_r=470, rect="5Y3GT"),
    PowerOption("se_el84", "5 W  -  single-ended EL84", "EL84", 1, "cathode", 300, 5200, 38, 4.5, rk=220, rect="EZ81",
                vsat=40),
    PowerOption("se_6l6", "9 W  -  single-ended 6L6GC", "6L6GC", 1, "cathode", 370, 4000, 62, 9, rk=330, screen_r=470,
                screen_part="res2w", rect="5AR4"),
    PowerOption("se_el34", "9 W  -  single-ended EL34", "EL34", 1, "cathode", 360, 3000, 60, 9, rk=330,
                screen_part="res5w", stopper=5600, rect="5AR4"),
    PowerOption("pp_6v6", "15 W  -  2 x 6V6, cathode bias (Tweed Deluxe)", "6V6GT", 2, "cathode", 360, 8000, 35, 15,
                rk=270, screen_r=470, rect="5Y3GT"),
    PowerOption("pp_el84", "18 W  -  2 x EL84, cathode bias", "EL84", 2, "cathode", 330, 8000, 36, 16, rk=150,
                rect="EZ81", vsat=40),
    PowerOption("pp_6v6_fixed", "22 W  -  2 x 6V6, fixed bias (Deluxe Reverb)", "6V6GT", 2, "fixed", 410, 6600, 26,
                20, vbias=-36, screen_r=470, grid_leak=100e3, rect="5AR4"),
    PowerOption("pp_el84x4", "30 W  -  4 x EL84, cathode bias (AC30)", "EL84", 4, "cathode", 330, 4000, 35, 30, rk=82,
                rect="5AR4", vsat=40),
    PowerOption("pp_6l6_cathode", "35 W  -  2 x 6L6GC, cathode bias", "6L6GC", 2, "cathode", 420, 4200, 50, 35,
                rk=220, screen_r=470, screen_part="res2w", rect="5AR4"),
    PowerOption("pp_el34_cathode", "35 W  -  2 x EL34, cathode bias", "EL34", 2, "cathode", 420, 3400, 50, 35, rk=220,
                screen_part="res5w", stopper=5600, rect="5AR4"),
    PowerOption("pp_6l6", "50 W  -  2 x 6L6GC, fixed bias (Bassman / Pro)", "6L6GC", 2, "fixed", 450, 4000, 38, 50,
                vbias=-45, screen_r=470, screen_part="res2w", grid_leak=100e3, rect="5AR4"),
    PowerOption("pp_el34", "50 W  -  2 x EL34, fixed bias (Marshall 50)", "EL34", 2, "fixed", 460, 3400, 36, 50,
                vbias=-38, screen_part="res5w", stopper=5600, rect="ss"),
    PowerOption("pp_kt88", "75 W  -  2 x KT88, fixed bias", "KT88", 2, "fixed", 480, 3500, 40, 75, vbias=-45,
                screen_part="res5w", stopper=5600, rect="ss", vsat=60),
    PowerOption("pp_6l6x4", "100 W  -  4 x 6L6GC, fixed bias (Twin)", "6L6GC", 4, "fixed", 460, 2000, 36, 100,
                vbias=-50, screen_r=470, screen_part="res2w", grid_leak=100e3, rect="ss"),
    PowerOption("pp_el34x4", "100 W  -  4 x EL34, fixed bias (Super Lead)", "EL34", 4, "fixed", 470, 1700, 35, 100,
                vbias=-38, screen_part="res5w", stopper=5600, rect="ss"),
]}

SS_POWER = {
    # key: (label, rail volts, secondary VAC)
    "lm3886_25": ("25 W  -  LM3886 on +/-24 V (50 W into 4 ohm)", 24.0, 18.0),
    "lm3886_40": ("35 W  -  LM3886 on +/-28 V (65 W into 4 ohm)", 28.0, 20.0),
    "lm3886_50": ("50 W  -  LM3886 on +/-35 V (8 ohm speakers only)", 35.0, 25.0),
}

# rectifier: voltage drop at full load, max current, max reservoir cap, heater (V, A), directly heated?
RECT = {
    "5Y3GT": dict(drop=50.0, imax=0.125, cmax=20e-6, heater=(5.0, 2.0), direct=True),
    "EZ81": dict(drop=25.0, imax=0.15, cmax=50e-6, heater=(6.3, 1.0), direct=False),
    "5AR4": dict(drop=20.0, imax=0.25, cmax=60e-6, heater=(5.0, 1.9), direct=False),
    "5U4GB": dict(drop=45.0, imax=0.275, cmax=40e-6, heater=(5.0, 3.0), direct=True),
    "ss": dict(drop=2.0, imax=10.0, cmax=1.0, heater=None, direct=True),
}


# --------------------------------------------------------------------------- voicings

@dataclass(frozen=True)
class Voicing:
    key: str
    label: str
    instrument: str  # guitar | bass | any
    tech: str  # tube | ss
    blurb: str
    power: str  # default power option
    pi: str = "ltp"  # ltp | cathodyne (push-pull only)
    nfb: str = "normal"  # off | light | normal (LTP only)
    v1: str = "12AX7"
    master: bool = False
    rect: str = ""  # preferred rectifier when the user leaves it on auto ("ss" for a stiff, tight supply)
    bright: bool = False  # a bright cap on the volume / gain control by default (the JCM800 has a 470p one)
    tight: str = ""  # default tightness (fat | normal | tight | djent); "" = the voicing has no tightness choice
    depth: bool = False  # a depth (resonance) control on the feedback loop by default
    loop: bool = False  # an effects loop by default


VOICINGS = {v.key: v for v in [
    Voicing("blackface", "Blackface clean", "guitar", "tube",
            "Glassy, scooped mids and lots of clean headroom (Fender AB763 style). The tone stack sits right after the "
            "first stage, then the volume and a recovery stage into a 12AT7 long-tail phase inverter with negative "
            "feedback.", "pp_6v6_fixed"),
    Voicing("tweed", "Tweed breakup", "guitar", "tube",
            "Raw, mid-forward and touch-sensitive; breaks up early (5E3 / 5F1 style). Two gain stages, a single "
            "treble-cut tone control and a cathodyne phase inverter, no negative feedback.", "pp_6v6", pi="cathodyne",
            nfb="off"),
    Voicing("plexi", "Plexi crunch", "guitar", "tube",
            "Bright, punchy British crunch (JTM45 / 1959 style). Partially bypassed gain stages, a cathode follower "
            "driving the Marshall tone stack, and a presence control on the feedback loop.", "pp_el34"),
    Voicing("chime", "Chime (EL84, no feedback)", "guitar", "tube",
            "Jangly, compressed top end with no negative feedback (Vox-style EL84 power stage).", "pp_el84x4",
            nfb="off"),
    Voicing("highgain", "British high gain (3 stages)", "guitar", "tube",
            "Three cascaded gain stages with a cold clipper, a cathode follower driving the Marshall tone stack and a "
            "master volume (JCM800 2203 style): the classic hard-rock and thrash sound, mid-forward and aggressive.",
            "pp_el34", master=True, rect="ss", tight="normal", depth=True, bright=True),
    Voicing("modern", "Modern high gain (4 stages)", "guitar", "tube",
            "Four cascaded stages - input, gain, a cold clipper and a hot stage - into a cathode follower and a "
            "post-distortion tone stack (in the spirit of the SLO-100 and its descendants): thick, saturated and "
            "articulate, with tight lows for rhythm and singing leads. Depth and presence on the power amp.",
            "pp_6l6", master=True, rect="ss", tight="normal", depth=True, loop=True),
    Voicing("extreme", "Extreme high gain (5 stages)", "guitar", "tube",
            "Five cascaded stages for the most saturation (5150 / Rectifier territory): a deeply scooped "
            "post-distortion EQ (a 10k middle control, like the big American amps), very tight low end for fast palm "
            "mutes and down-tuned and extended-range guitars. Pair it with a noise gate in the effects loop.",
            "pp_6l6x4", master=True, rect="ss", tight="tight", depth=True, loop=True),
    Voicing("bass_tube", "Bass (vintage tube)", "bass", "tube",
            "Deep, warm bass with headroom: a moderate-gain 12AX7 / 12AU7 preamp, a bass-voiced tone stack and a "
            "fixed-bias power stage with feedback for tight lows.", "pp_6l6"),
    Voicing("ss_clean", "Solid-state clean", "guitar", "ss",
            "Op-amp preamp with a Fender-style tone stack and an LM3886 power amp: light, reliable, clean.",
            "lm3886_40"),
    Voicing("ss_drive", "Solid-state drive", "guitar", "ss",
            "Op-amp gain stage into soft diode clipping and a Marshall-style tone stack, LM3886 power amp.",
            "lm3886_40", master=True),
    Voicing("ss_bass", "Solid-state bass", "bass", "ss",
            "Op-amp preamp with a deep bass tone stack, XLR DI output and speakON, LM3886 power amp.", "lm3886_40",
            master=True),
]}


@dataclass
class AmpSpec:
    """Everything the user chooses."""
    instrument: str = "guitar"  # guitar | bass
    tech: str = "tube"  # tube | ss
    voicing: str = "blackface"
    power: str = ""  # POWER / SS_POWER key ("" = the voicing's default)
    rectifier: str = "auto"  # auto | tube | ss
    speaker: int = 8
    v1: str = ""  # first preamp tube ("" = the voicing's choice)
    master: bool | None = None  # None = the voicing's default
    bright: bool | None = None  # bright cap on the volume / gain (None = the voicing's default)
    presence: bool = True
    nfb: str = "auto"  # auto | off | light | normal
    choke: bool = True
    standby: bool = False
    fx_loop: bool | None = None  # series effects loop (None = the voicing's default)
    di_out: bool | None = None  # bass: default on
    mains: int = 230
    name: str = ""
    tight: str = "auto"  # high gain: auto | fat | normal | tight | djent - how much bass reaches the distortion
    depth: bool | None = None  # depth (resonance) control on the feedback loop (None = the voicing's default)
    dc_heaters: bool = False  # tube: the preamp tubes' heaters on filtered DC (no heater hum in the input stages)

    def resolved(self) -> "AmpSpec":
        v = VOICINGS[self.voicing]
        s = replace(self)
        s.tech = v.tech
        if v.instrument != "any":
            s.instrument = v.instrument
        if not s.power or (s.tech == "tube") != (s.power in POWER):
            s.power = v.power
        if not s.v1:
            s.v1 = v.v1
        if s.master is None:
            s.master = v.master
        if s.nfb == "auto":
            s.nfb = v.nfb
        if s.di_out is None:
            s.di_out = s.instrument == "bass"
        if s.speaker not in (4, 8, 16):
            s.speaker = 8
        if s.fx_loop is None:
            s.fx_loop = v.loop
        if s.bright is None:
            s.bright = v.bright
        if s.depth is None:
            s.depth = v.depth
        if s.tight not in gs.TIGHT_LEVELS:
            s.tight = v.tight or "normal"
        if s.rectifier == "auto" and v.rect and s.tech == "tube":
            s.rectifier = v.rect
        return s


@dataclass
class Report:
    title: str = ""
    pout: float = 0.0
    character: str = ""
    breakup: tuple = (0.0, 0.0)  # volume-knob position (0-10) where it breaks up with single coils / humbuckers
    sensitivity_mv: float = 0.0
    gain_db: float = 0.0
    stages: list = field(default_factory=list)  # (stage, gain, note)
    supply: list = field(default_factory=list)  # (node, volts, mA, feeds, filter)
    power_rows: list = field(default_factory=list)  # (item, value)
    buy: list = field(default_factory=list)  # (item, spec)
    warnings: list = field(default_factory=list)
    tips: list = field(default_factory=list)
    tone: ToneStack | None = None
    tone_name: str = ""
    instrument: str = "guitar"
    tubes: list = field(default_factory=list)
    parts: int = 0
    spl: float = 0.0
    breakup_knob: str = ""  # the control the breakup positions refer to ("" = the volume, on a non-master amp)
    chart: list = field(default_factory=list)  # (ref, tube, [(pin, function, volts)]) - the voltage chart
    powerup: list = field(default_factory=list)  # first power-up steps
    analysis: gs.Analysis | None = None  # gain staging: where it distorts, low end into the distortion, hiss
    feedback: gs.Feedback | None = None  # the presence / depth network, for the power-amp response
    tight: str = ""  # tightness level of a high-gain preamp
    pedals: list = field(default_factory=list)  # (pedal key, why) - pedals that suit this amp


# --------------------------------------------------------------------------- circuit assembly

class _Slot:
    """A dual-triode tube being filled section by section."""

    def __init__(self, tube: str, section: str, index: int):
        self.tube = tube
        self.section = section
        self.node = f"@N{index}"  # B+ node placeholder, resolved when the supply is laid out
        self.nets: dict = {}
        self.free = ["A", "B"]

    def take(self) -> str:
        return self.free.pop(0)


class _Stage:
    def __init__(self, vp_fn):
        self.vp = vp_fn


class _D:
    def __init__(self, spec: AmpSpec):
        self.s = spec
        self.parts: list = []
        self.volts: dict = {}
        self.vac: dict = {}
        self.amps: dict = {}
        self.slots: list[_Slot] = []
        self.loads: dict = {}  # node -> [fn(V) -> amps]
        self.fins: list = []
        self.gains: list = []  # (label, gain, note)
        self.rep = Report()
        self.cf = False
        self.extra_tubes: list = []  # (name, section, nets, heater)
        self.path: list = []  # the signal path for the gain-staging analysis (gainstage.Stage / Net / Clip)
        self.ts_load = 1e6  # what loads the tone stack's output (the master or volume pot)
        self.ot: dict = {}

    def add(self, *parts):
        self.parts.extend(parts)
        return parts[-1] if parts else None

    def slot(self, tube: str, section: str, pair: bool = False) -> _Slot:
        if not pair:
            for sl in self.slots:
                if sl.tube == tube and sl.free and sl.section == section and len(sl.free) == 1:
                    return sl
        sl = _Slot(tube, section, len(self.slots))
        self.slots.append(sl)
        return sl

    def load(self, node: str, fn) -> None:
        self.loads.setdefault(node, []).append(fn)

    # ------------------------------------------------------------------ preamp blocks
    def stage(self, sl: _Slot, grid: str, label: str, ra: float, rk: float, ck: float = 0.0, load: float = 1e6,
              sec: str = "", note: str = "", zs=0.0) -> tuple[str, _Stage]:
        """A common-cathode gain stage. ``ck`` bypasses the cathode resistor (0 = unbypassed: less gain, more
        headroom); ``zs`` is the impedance feeding the grid, for the Miller roll-off in the analysis."""
        t = TUBES[sl.tube]
        x = sl.take()
        P_, K_ = f"{label}_P", f"{label}_K"
        sl.nets.update({"P" + x: P_, "G" + x: grid, "K" + x: K_})
        pr = self.add(R(fmt_r(ra), sl.node, P_, "res", sec))
        self.add(R(fmt_r(rk), K_, "GND", "res_small", sec))
        if ck >= 1e-6:
            self.add(CP(f"{fmt_c(ck)} 25V", K_, "GND", "elco_lv", sec))
        elif ck > 0:
            self.add(C(f"{fmt_c(ck)} 63V", K_, "GND", "film", sec))
        rec = gs.Stage(label, sl.tube, t.mu, ra, rk, ck, load, zs, note)
        self.path.append(rec)

        def ia(V):
            i = max(0.0, V[sl.node]) / (t.ra_k * 1e3 + ra + t.mu * rk)
            for _ in range(4):  # rp grows at low current: solve I = Vb / (rp(I) + Ra + mu Rk)
                i = max(0.0, V[sl.node]) / (_rp(sl.tube, i) + ra + t.mu * rk)
            return i

        self.load(sl.node, ia)
        zk = rk if ck <= 0 else abs(rk / (1 + 2j * math.pi * 1000 * rk * ck))
        raeff = ra * load / (ra + load)
        shelf = 1 / (2 * math.pi * rk * ck) if ck > 0 else 0.0
        bypass = ("unbypassed" if ck <= 0 else "fully bypassed" if shelf < 35 else
                  f"partly bypassed ({fmt_c(ck)}): less gain below about {shelf:.0f} Hz")
        entry = [f"{label} ({sl.tube})", 1.0, (note + ", " if note else "") +
                 f"{fmt_r(ra)} plate, {fmt_r(rk)} cathode, {bypass}"]
        self.gains.append(entry)

        def fin(V):
            i = ia(V)
            self.volts[P_] = round(V[sl.node] - i * ra)
            self.volts[K_] = round(i * rk, 1)
            pr.part = rpart(ra, i * ra)
            rp = _rp(sl.tube, i)
            entry[1] = t.mu * raeff / (raeff + rp + (t.mu + 1) * zk)
            rec.ia, rec.rp, rec.vb = i, rp, V[sl.node]
            rec.vp, rec.vk = V[sl.node] - i * ra, i * rk
        self.fins.append(fin)
        stage = _Stage(lambda V: V[sl.node] - ia(V) * ra)
        stage.rout = lambda V: ra * _rp(sl.tube, ia(V)) / (ra + _rp(sl.tube, ia(V)))  # output impedance
        return P_, stage

    def follower(self, sl: _Slot, prev: str, prev_stage: _Stage, label: str = "CF", sec: str = "") -> str:
        x = sl.take()
        G_, K_ = f"{label}_G", f"{label}_K"
        sl.nets.update({"P" + x: sl.node, "G" + x: G_, "K" + x: K_})
        self.add(R("470k", prev, G_, "res_small", sec))
        rk = self.add(R("100k", K_, "GND", "res2w", sec))
        self.cf = True

        def vk(V):
            return prev_stage.vp(V) + 1.5

        self.load(sl.node, lambda V: vk(V) / 100e3)

        def fin(V):
            self.volts[K_] = round(vk(V))
            self.volts[G_] = round(prev_stage.vp(V))
            rk.part = rpart(100e3, vk(V))
        self.fins.append(fin)
        self.gains.append((f"{label} ({sl.tube})", 0.97, "cathode follower, DC-coupled: drives the tone stack"))
        self.path.append(gs.Net("Cathode follower", lambda f: np.full(np.shape(f), 0.97 + 0j)))
        return K_

    def volume(self, top: str, wiper: str, label: str, value: str = "A1M", bright: str = "", sec: str = "") -> None:
        self.add(POT(value, "GND", wiper, top, label, sec))
        if bright:
            self.add(C(f"{bright} 500V", top, wiper, "ceramic_hv", sec))
        self.path.append(gs.Net(label, lambda f: np.ones(np.shape(f), dtype=complex), pot=value[0]))

    def couple(self, src: str, dst: str, farads: float, sec: str, rload: float = 1e6, rsrc: float = 38e3) -> None:
        """Coupling cap from a plate into ``rload``: blocks the DC and, when small, cuts the lows below
        1 / (2 pi (rsrc + rload) C) - the main way a high-gain preamp is tightened."""
        self.add(C(f"{fmt_c(farads)} 400V", src, dst, "film_hv", sec))
        rt = rsrc + rload

        def h(f):
            s_ = 2j * np.pi * np.asarray(f, dtype=float) * rt * farads
            return s_ / (1 + s_)
        self.path.append(gs.Net(f"{fmt_c(farads)} coupling", h))

    def treble(self, a: str, b: str, sec: str, rload: float | None = None, r: float = 470e3, c: float = 470e-12):
        """The 470k / 470p "bright" network: an attenuator into ``rload`` (a gain pot) whose cap lets the highs past,
        or a grid stopper (rload None) whose cap keeps the next stage's Miller capacitance from dulling the highs.
        Returns the impedance feeding the next grid as fn(f), for that stage's ``zs``."""
        self.add(R(fmt_r(r), a, b, "res_small", sec), C(f"{fmt_c(c)} 500V", a, b, "ceramic_hv", sec))

        def z(f):
            return r / (1 + 2j * np.pi * np.asarray(f, dtype=float) * r * c)
        if rload:
            g = abs(rload / (rload + z(np.array([1000.0]))[0]))
            self.gains.append((f"{fmt_r(r)} / {fmt_c(c)} network", g, f"treble-boosting attenuator into the "
                                                                       f"{fmt_r(rload)} control"))
            self.path.append(gs.Net(f"{fmt_r(r)} / {fmt_c(c)}", lambda f: rload / (rload + z(f))))
        return lambda f: z(f) + 36e3  # plus the previous plate's output impedance

    def tone_stack(self, ts: ToneStack, name: str, drive: str, dc_fn, rs_fn, sec: str) -> str:
        """FMV tone stack; ``rs_fn(V)`` is the driving stage's output impedance (a plate or a cathode follower)."""
        parts = stack_parts(ts, drive, "TS_OUT", "TS", sec)
        self.add(*parts)
        entry = ["Tone stack", 1.0, f"{name}, controls at noon (1 kHz)"]
        self.gains.append(entry)
        self.rep.tone, self.rep.tone_name = ts, name

        net = gs.Net("Tone stack", lambda f: np.ones(np.shape(f), dtype=complex))
        self.path.append(net)

        def fin(V):
            dc = dc_fn(V)
            self.volts["TS_A"] = round(dc)
            if dc > 300:
                for p in parts:
                    if p.prefix == "C" and p.value.endswith("400V"):
                        p.value = p.value.replace("400V", "630V")
            tsr = replace(ts, rs=rs_fn(V), rl=self.ts_load)
            entry[1] = 10 ** (response_db(tsr, 5, 5, 5, np.array([1000.0]))[0] / 20)
            self.rep.tone = tsr
            net.h = lambda f: response(tsr, 5, 5, 5, np.asarray(f, dtype=float))
        self.fins.append(fin)
        return "TS_OUT"

    def fx_loop(self, src: str, sec: str) -> str:
        """Tube-buffered series effects loop. A 470k / 47k divider brings the preamp's output down to pedal level and
        a cathode follower drives the SEND jack through a cable without losing treble; the RETURN jack's switch
        normals the send back in when nothing is plugged in, and a recovery stage makes up the level. Returns the
        recovery stage's plate."""
        sl = self.slot("12AX7", sec, pair=True)
        if src not in ("TS_OUT", "TONE_IN", "MV_OUT"):  # a plate: block its DC first
            self.add(C("22nF 400V", src, "FX_IN", "film_hv", sec))
            src = "FX_IN"
        if src == "TS_OUT":
            self.ts_load = 517e3
        x = sl.take()
        sl.nets.update({"P" + x: sl.node, "G" + x: "FX_G", "K" + x: "FX_K"})
        self.add(R("470k", src, "FX_G", "res_small", sec), R("47k", "FX_G", "GND", "res_small", sec),
                 R("1k5", "FX_K", "GND", "res_small", sec), C("1uF 63V", "FX_K", "FX_SO", "film", sec),
                 R("100R", "FX_SO", "SEND", "res_small", sec), R("100k", "SEND", "GND", "res_small", sec),
                 P("J", "SEND", "jack", {"T": "SEND", "S": "GND"}, sec, "rear", "FX SEND"),
                 P("J", "RETURN", "jack", {"T": "FX_RET", "TN": "SEND", "S": "GND"}, sec, "rear", "FX RETURN"),
                 R("1M", "FX_RET", "GND", "res_small", sec), R("33k", "FX_RET", "FXR_G", "res_small", sec))

        def ik(V):
            return gs.follower_bias("12AX7", V[sl.node], 1500.0)
        self.load(sl.node, ik)

        def fin(V):
            self.volts["FX_K"] = round(ik(V) * 1500.0, 1)
        self.fins.append(fin)
        div = 47e3 / 517e3
        self.gains.append(("Effects loop send", div * 0.72, "470k / 47k divider and a cathode follower: about "
                                                            "-7 dBV into the pedals"))
        self.path.append(gs.Net("Loop send", lambda f: np.full(np.shape(f), div * 0.72 + 0j)))
        p, _ = self.stage(sl, "FXR_G", "FXR", 100e3, 2700, 0.0, sec=sec, note="loop recovery", zs=33e3)
        return p

    # ------------------------------------------------------------------ phase inverters
    def ltp(self, sl: _Slot, inp: str, sec: str, nfb: str, presence: bool) -> tuple[str, str, float]:
        t = TUBES[sl.tube]
        sl.take(), sl.take()
        sl.nets.update({"PA": "PI_PA", "GA": "PI_GA", "KA": "PI_K", "PB": "PI_PB", "GB": "PI_GB", "KB": "PI_K"})
        tail = 22e3 if sl.tube == "12AT7" else 10e3
        # grid B is the pair's second input: its 100n goes to the feedback node, so the feedback is subtracted from
        # the signal on grid A (taken to ground it would only move both cathodes together - common mode, no effect)
        bottom = "PI_NFB" if nfb != "off" else "GND"
        self.add(C("22nF 400V", inp, "PI_GA", "film_hv", sec), R("1M", "PI_GA", "PI_BIAS", "res_small", sec),
                 R("1M", "PI_GB", "PI_BIAS", "res_small", sec), C("100nF 400V", "PI_GB", bottom, "film_hv", sec),
                 R("470R", "PI_K", "PI_BIAS", "res_small", sec))
        if nfb != "off":
            rf = e12({4: 33e3, 8: 47e3, 16: 68e3}[self.s.speaker] * (1.6 if nfb == "light" else 1.0))
            fbk = gs.Feedback(rf, {"light": 0.6, "normal": 0.4}[nfb])
            self.add(R("4k7", "PI_NFB", "GND", "res_small", sec))
            if self.s.depth:
                # depth (resonance): a cap in series with the feedback resistor, shunted by a rheostat; turning it up
                # takes feedback away in the lows (about +6 dB at 80 Hz, little above 300 Hz), so the power amp
                # thumps at the cabinet's resonance while the preamp stays tight
                cd = e6(1 / (2 * math.pi * (rf + 4.7e3) * 200.0))
                fbk.depth_c = cd
                self.add(R(fmt_r(rf), "SPK", "PI_DEP", "res_small", sec),
                         C(f"{fmt_c(cd)} 100V", "PI_DEP", "PI_NFB", "film", sec),
                         POT("B250K", "PI_DEP", "PI_NFB", "PI_NFB", "DEPTH", sec))
                self.vac["PI_DEP"] = round(math.sqrt(POWER[self.s.power].pout * self.s.speaker), 1)
            else:
                self.add(R(fmt_r(rf), "SPK", "PI_NFB", "res_small", sec))
            if presence:
                fbk.pres_c = 100e-9
                self.add(C("100nF 63V", "PI_NFB", "PRES", "film", sec),
                         POT("B5K", "GND", "GND", "PRES", "PRESENCE", sec))
            self.rep.feedback = fbk
        rt = self.add(R(fmt_r(tail), "PI_BIAS", bottom, "res", sec))
        ra_a = self.add(R("82k", sl.node, "PI_PA", "res", sec))
        ra_b = self.add(R("100k", sl.node, "PI_PB", "res", sec))
        side = 1.6e-3 if sl.tube == "12AT7" else 1.2e-3  # per side (a 12AX7 LTP runs harder than a gain stage)
        self.load(sl.node, lambda V: 2 * side)

        def fin(V):
            vb = V[sl.node]
            self.volts.update({"PI_PA": round(vb - side * 82e3), "PI_PB": round(vb - side * 100e3),
                               "PI_BIAS": round(2 * side * tail), "PI_GA": round(2 * side * tail),
                               "PI_GB": round(2 * side * tail), "PI_K": round(2 * side * (tail + 470))})
            rt.part = rpart(tail, 2 * side * tail)
            ra_a.part = rpart(82e3, side * 82e3)
            ra_b.part = rpart(100e3, side * 100e3)
        self.fins.append(fin)
        gain = t.mu * 100e3 / (2 * (100e3 + _rp(sl.tube, side)))
        self.gains.append((f"Phase inverter ({sl.tube} long-tail pair)", gain, "each output"))
        fb = {"off": 1.0, "light": 0.6, "normal": 0.4}[nfb]
        if fb < 1:
            self.gains.append(("Negative feedback", fb, f"{nfb} feedback from the {self.s.speaker} ohm tap"))
        return "PI_PA", "PI_PB", fb

    def cathodyne(self, sl: _Slot, inp: str, sec: str) -> tuple[str, str]:
        x = sl.take()
        sl.nets.update({"P" + x: "PI_P", "G" + x: "PI_G", "K" + x: "PI_K"})
        self.add(C("22nF 400V", inp, "PI_G", "film_hv", sec), R("1M", "PI_G", "PI_BIAS", "res_small", sec),
                 R("1k5", "PI_K", "PI_BIAS", "res_small", sec))
        rt = self.add(R("100k", "PI_BIAS", "GND", "res", sec))
        ra = self.add(R("100k", sl.node, "PI_P", "res", sec))
        self.load(sl.node, lambda V: 0.4 * V[sl.node] / 100e3)

        def fin(V):
            i = 0.4 * V[sl.node] / 100e3
            self.volts.update({"PI_P": round(V[sl.node] - i * 100e3), "PI_K": round(i * 101.5e3),
                               "PI_BIAS": round(i * 100e3), "PI_G": round(i * 100e3)})
            rt.part = rpart(100e3, i * 100e3)
            ra.part = rpart(100e3, i * 100e3)
        self.fins.append(fin)
        self.gains.append((f"Phase inverter ({sl.tube} cathodyne)", 0.9, "each output"))
        return "PI_P", "PI_K"


# --------------------------------------------------------------------------- tube amp

# Cathode bypass caps and coupling caps by tightness (fat, normal, tight, djent). A partly bypassed cathode gives the
# stage less gain below 1 / (2 pi Rk Ck); a small coupling cap cuts the lows before the next grid. Spread over the
# cascade this decides how much low end reaches the clipping stages - too much and fast palm mutes turn to mush.
_CK_INPUT = {2700: (2.2e-6, 0.68e-6, 0.47e-6, 0.33e-6), 1500: (4.7e-6, 1e-6, 0.68e-6, 0.47e-6)}
_CK_HOT = {820: (2.2e-6, 0.68e-6, 0.47e-6, 0.33e-6), 1500: (1e-6, 0.68e-6, 0.47e-6, 0.33e-6),
           2700: (1e-6, 0.47e-6, 0.33e-6, 0.22e-6)}
_C_INPUT = (22e-9, 22e-9, 10e-9, 4.7e-9)  # V1A into the gain control
_C_CLIP = (22e-9, 22e-9, 4.7e-9, 2.2e-9)  # into a cold clipper or the stage after it
_C_EARLY = (22e-9, 10e-9, 4.7e-9, 2.2e-9)
_C_LATE = (10e-9, 4.7e-9, 2.2e-9, 1e-9)  # deep in a five-stage cascade, where the lows would pile up most


def _high_gain(d: _D, v1: _Slot, PRE: str, GAIN: str, TONE: str) -> str:
    """The cascaded high-gain preamps: British (3 stages, JCM800 2203 style), modern (4 stages) and extreme (5).

    Every stage after the gain control is fed through a 1M grid leak and a 470k / 470p grid stopper (the stopper
    and the next stage's Miller capacitance roll off the fizz; the cap keeps the attack), a cold-clipper stage
    (10k unbypassed cathode) adds the asymmetric bite, and a DC-coupled cathode follower drives the tone stack after
    the distortion. The tightness choice sets the bypass and coupling caps.

    The late stages of the four- and five-stage preamps run unbypassed behind real 470k / 470k dividers. Gain
    after the GAIN control decides how punchy palm mutes are: a stage driven far past clipping keeps a decaying
    note at full level, and as its upper partials die it squares up the fundamental, so the low end swells after
    the pick instead of following the mute. Played through the tube simulation with a palm-muted riff, the
    divided cascade keeps the rhythm sweet spot around noon on the GAIN knob, as on the three-stage amp, and saves
    the saturation for the top of the knob."""
    s = d.s
    lvl = s.tight

    def T(vals):
        return gs.tight_pick(vals, lvl)

    def into(src: str, label: str, sec: str, caps, leak: float = 0.0) -> object:
        """Coupling cap, then a 470k / 470p stopper into ``label``'s grid; returns what feeds the grid. Without
        ``leak`` the coupling node has a 1M grid leak; with it the stopper and a ``leak`` resistor from the grid to
        ground make a divider (half the level in the lows, less in the treble the 470p lets past)."""
        gl = f"{label}_GL"
        if not leak:
            d.couple(src, gl, T(caps), sec)
            d.add(R("1M", gl, "GND", "res_small", sec))
            return d.treble(gl, f"{label}_G", sec)
        d.couple(src, gl, T(caps), sec, rload=470e3 + leak)
        z = d.treble(gl, f"{label}_G", sec, rload=leak)
        d.add(R(fmt_r(leak), f"{label}_G", "GND", "res_small", sec))
        return lambda f: 1 / (1 / z(f) + 1 / leak)

    key = s.voicing
    rk1 = 2700 if key == "highgain" else 1500
    p1, _ = d.stage(v1, "V1A_G", "V1A", 100e3, rk1, T(_CK_INPUT[rk1]), load=1.47e6, sec=PRE, zs=68e3,
                    note="input")
    d.couple(p1, "HG_A", T(_C_INPUT), PRE, rload=1.47e6)
    d.treble("HG_A", "GAIN_IN", PRE, rload=1e6)
    # bright cap on the gain control: more treble at low gain settings (the JCM800's 470p)
    d.volume("GAIN_IN", "V1B_G", "GAIN", "A1M", ("470pF" if key == "highgain" else "220pF") if s.bright else "", PRE)
    if key == "highgain":
        p2, _ = d.stage(v1, "V1B_G", "V1B", 100e3, 10e3, 0.0, sec=PRE, zs=300e3, note="cold clipper")
        v2 = d.slot("12AX7", TONE)
        z = into(p2, "V2A", TONE, _C_CLIP)
        last, st = d.stage(v2, "V2A_G", "V2A", 100e3, 820, T(_CK_HOT[820]), sec=TONE, zs=z, note="hot stage")
        cf_slot, ts_name = v2, "Marshall JCM800 2203"
    elif key == "modern":
        p2, _ = d.stage(v1, "V1B_G", "V1B", 100e3, 2700, T(_CK_HOT[2700]), sec=PRE, zs=300e3, note="second stage")
        v2 = d.slot("12AX7", GAIN)
        z = into(p2, "V2A", GAIN, _C_EARLY)
        p3, _ = d.stage(v2, "V2A_G", "V2A", 100e3, 10e3, 0.0, sec=GAIN, zs=z, note="cold clipper")
        z = into(p3, "V2B", GAIN, _C_LATE, leak=470e3)
        last, st = d.stage(v2, "V2B_G", "V2B", 100e3, 2700, 0.0, sec=GAIN, zs=z, note="fourth stage")
        cf_slot, ts_name = d.slot("12AX7", TONE), "Modern high gain (47k slope)"
    else:  # extreme: five stages sharing about the same total gain as four, so each clips a little less and the
        # distortion is smoother and more compressed without the hiss saturating; the fifth stage and the cathode
        # follower share V3
        p2, _ = d.stage(v1, "V1B_G", "V1B", 100e3, 2700, 0.0, sec=PRE, zs=300e3, note="second stage")
        v2 = d.slot("12AX7", GAIN)
        z = into(p2, "V2A", GAIN, _C_EARLY)
        p3, _ = d.stage(v2, "V2A_G", "V2A", 100e3, 10e3, 0.0, sec=GAIN, zs=z, note="cold clipper")
        z = into(p3, "V2B", GAIN, _C_LATE, leak=220e3)
        p4, _ = d.stage(v2, "V2B_G", "V2B", 100e3, 2700, 0.0, sec=GAIN, zs=z, note="fourth stage")
        v3 = d.slot("12AX7", TONE)
        z = into(p4, "V3A", TONE, _C_LATE, leak=220e3)
        last, st = d.stage(v3, "V3A_G", "V3A", 100e3, 2700, 0.0, sec=TONE, zs=z, note="fifth stage")
        cf_slot, ts_name = v3, "Deep scoop US high gain (82k slope, 10k mid)"
    cf = d.follower(cf_slot, last, st, "CF", TONE)
    d.rep.tight = lvl
    return d.tone_stack(PRESETS[ts_name], ts_name.split(" (")[0], cf, lambda V: st.vp(V) + 1.5, lambda V: 1e3, TONE)


def _rectifier(spec: AmpSpec, opt: PowerOption, i_full: float, warn: list) -> str:
    choice = spec.rectifier
    if choice == "ss":
        return "ss"
    want = opt.rect if choice == "auto" else (opt.rect if opt.rect != "ss" else "5AR4")
    if want == "ss":
        return "ss"
    order = ["EZ81", "5Y3GT", "5AR4", "5U4GB"] if want == "EZ81" else ["5Y3GT", "5AR4", "5U4GB"]
    for r in order[order.index(want):]:
        if RECT[r]["imax"] >= i_full:
            return r
    if choice == "tube":
        warn.append(f"No tube rectifier handles {i_full * 1000:.0f} mA: using a solid-state rectifier instead.")
    return "ss"


def _design_tube(d: _D) -> AmpDesign:
    s = d.s
    v = VOICINGS[s.voicing]
    opt = POWER[s.power]
    pt = TUBES[opt.tube]
    pp = opt.pp
    PRE, GAIN, TONE, LOOP, PI, PWR, PSU = "Preamp", "Gain", "Tone", "Loop", "PI", "Power", "Supply"
    nfb = s.nfb if (pp and v.pi == "ltp") else "off"
    if s.nfb not in ("off", "auto") and nfb == "off" and s.nfb != v.nfb:
        d.rep.tips.append("Negative feedback needs the long-tail phase inverter, so this design runs without it.")

    # --- input -----------------------------------------------------------------------------------------------
    d.add(P("J", "INPUT", "jack", {"T": "IN", "S": "GND"}, PRE, "front", "INPUT"),
          R("1M", "IN", "GND", "res_small", PRE), R("68k", "IN", "V1A_G", "res_small", PRE))

    # --- preamp per voicing -------------------------------------------------------------------------------
    v1 = d.slot(s.v1, PRE)
    key = s.voicing
    if key in ("blackface", "bass_tube", "chime"):
        stack = {"blackface": "Fender Blackface (AB763 Twin)", "bass_tube": "Bass amp (deep, Bassman with 47n bass cap)",
                 "chime": "Vox-voiced (100k slope, 1M bass)"}[key]
        rk1, ck1 = (1500, 0.0) if key == "bass_tube" else (1500, 25e-6)
        p1, st1 = d.stage(v1, "V1A_G", "V1A", 100e3, rk1, ck1, load=250e3, sec=PRE, zs=68e3)
        ts_out = d.tone_stack(PRESETS[stack], stack.split(" (")[0], p1, st1.vp, st1.rout, TONE)
        d.volume(ts_out, "VOL_W", "VOLUME", "A1M", "120pF" if s.bright else "", PRE)
        t2 = "12AU7" if key == "bass_tube" else s.v1
        ck2 = 0.0 if key == "chime" else 25e-6  # the chime voicing's recovery stage runs unbypassed (less gain)
        if t2 != s.v1:
            v2 = d.slot(t2, TONE)
            pre_out, _ = d.stage(v2, "VOL_W", "V2A", 100e3, 1500, ck2, sec=TONE, zs=100e3)
        else:
            pre_out, _ = d.stage(v1, "VOL_W", "V1B", 100e3, 1500, ck2, sec=PRE, zs=100e3)
    elif key == "tweed":
        p1, _ = d.stage(v1, "V1A_G", "V1A", 100e3, 1500, 25e-6, sec=PRE, zs=68e3)
        d.couple(p1, "VOL_IN", 22e-9, PRE)
        d.volume("VOL_IN", "V1B_G", "VOLUME", "A1M", "120pF" if s.bright else "", PRE)
        p2, _ = d.stage(v1, "V1B_G", "V1B", 100e3, 1500, 25e-6, sec=PRE, zs=40e3)
        d.couple(p2, "TONE_IN", 22e-9, TONE)
        d.add(R("1M", "TONE_IN", "GND", "res_small", TONE),
              C("4.7nF 400V", "TONE_IN", "TONE_C", "film_hv", TONE), POT("A1M", "TONE_C", "GND", "GND", "TONE", TONE))
        d.gains.append(("Tone control", 0.9, "treble cut, at noon"))

        def tweed_tone(f):  # the plate (about 40k) into 1M parallel with 4.7n + the pot at noon (100k)
            zsh = 1 / (1 / 1e6 + 1 / (100e3 + 1 / (2j * np.pi * np.asarray(f, dtype=float) * 4.7e-9)))
            return zsh / (zsh + 40e3)
        d.path.append(gs.Net("Tone control", tweed_tone))
        pre_out = "TONE_IN"
    elif key == "plexi":
        p1, _ = d.stage(v1, "V1A_G", "V1A", 100e3, 820, 0.68e-6, sec=PRE, zs=68e3)
        d.couple(p1, "VOL_IN", 22e-9, PRE)
        d.volume("VOL_IN", "V1B_G", "VOLUME", "A1M", "470pF" if s.bright else "", PRE)
        p2, st2 = d.stage(v1, "V1B_G", "V1B", 100e3, 820, 0.68e-6, sec=PRE, zs=40e3)
        v2 = d.slot("12AX7", TONE)
        cf = d.follower(v2, p2, st2, "CF", TONE)
        pre_out = d.tone_stack(PRESETS["Marshall JTM45 / 1959"], "Marshall JTM45 / 1959",
                               cf, lambda V: st2.vp(V) + 1.5, lambda V: 1e3, TONE)
    elif key in ("highgain", "modern", "extreme"):
        pre_out = _high_gain(d, v1, PRE, GAIN, TONE)
    else:
        raise ValueError(f"not a tube voicing: {key}")

    # --- effects loop, master, phase inverter -------------------------------------------------------------
    if s.fx_loop:
        pre_out = d.fx_loop(pre_out, LOOP)
        if not s.master:
            d.rep.tips.append("With the effects loop and no master volume the recovery stage drives the phase "
                              "inverter directly: the VOLUME and GAIN controls set the level.")
    if s.master:
        top = pre_out
        if pre_out not in ("TS_OUT", "TONE_IN"):  # a plate: block its DC first
            d.add(C("22nF 400V", pre_out, "MV_IN", "film_hv", PI))
            top = "MV_IN"
        d.volume(top, "MV_OUT", "MASTER", "A1M", "", PI)
        pre_out = "MV_OUT"
    fb = 1.0
    if pp:
        if v.pi == "cathodyne":
            pis = d.slot("12AX7", PI)
            out_a, out_b = d.cathodyne(pis, pre_out, PI)
        else:
            pis = d.slot("12AT7" if s.voicing in ("blackface", "bass_tube") else "12AX7", PI, pair=True)
            out_a, out_b, fb = d.ltp(pis, pre_out, PI, nfb, s.presence and nfb != "off")
        drives = [out_a, out_b]
    else:
        drives = [pre_out]
    if not s.master:  # the power tubes are the last thing to clip, at the PI drive that reaches their bias
        pi_gain = next((g for label, g, _n in d.gains if label.startswith("Phase inverter")), 1.0)
        vdrive = abs(opt.vbias) if opt.bias == "fixed" else (opt.ik_ma / 1000 * opt.count * opt.rk)
        d.path.append(gs.Net("Phase inverter", lambda f, g=pi_gain * fb: np.full(np.shape(f), g + 0j)))
        d.path.append(gs.Clip("Power tubes", vdrive))

    # --- power stage -------------------------------------------------------------------------------------------
    n_side = opt.count // len(drives)
    # more than about 3 A of heater current needs 1.5-2 mm traces: wire the power tubes' heaters off the board
    local_heaters = 0.3 * len(d.slots) + pt.heater_a * opt.count > 3.0
    fixed = opt.bias == "fixed"
    k_shared = "OUT_K"
    ref = "BIAS_OUT" if fixed else "GND"
    idle = opt.ik_ma / 1000.0
    for si, drive in enumerate(drives):
        side = "AB"[si]
        gl = f"GL{side}"
        d.add(C("100nF 630V" if pp else "22nF 400V", drive, gl, "film_hv", PWR))
        if fixed:
            d.volts[gl] = opt.vbias
        d.add(R(fmt_r(opt.grid_leak), gl, ref, "res_small", PWR))
        for k in range(n_side):
            i = si * n_side + k + 1
            g, scr = f"PT{i}_G", f"PT{i}_S"
            plate = ("OT_P1" if si == 0 else "OT_P2") if pp else "OT_P"
            cath = f"PT{i}_K" if fixed else k_shared
            nets = {"A": plate, "G1": g, "G2": scr, "K": cath}
            if pt.pin("G3"):
                nets["G3"] = cath
            if local_heaters:  # heavy heater load: each power tube gets its own pair of heater wire pads
                hn = (f"PT{i}_H1", f"PT{i}_H2")
                d.extra_tubes.append((opt.tube, PWR, nets, hn))
                d.add(PADS(["H1", "H2"], list(hn), f"heater wires for this {opt.tube} (twisted pair)", PWR))
                d.vac.update({hn[0]: 3.2, hn[1]: 3.2})
                d.amps.update({hn[0]: pt.heater_a, hn[1]: pt.heater_a})
            else:
                d.extra_tubes.append((opt.tube, PWR, nets))
            d.add(R(fmt_r(opt.stopper), gl, g, "res_small", PWR),
                  R(fmt_r(opt.screen_r), "B+2", scr, opt.screen_part, PWR))
            d.volts[scr] = None  # filled in below
            if fixed:
                d.add(R("1R", cath, "GND", "res_small", PWR))
                d.volts[cath] = round(idle * 1.0, 3)
                d.volts[g] = opt.vbias
            else:
                d.volts[g] = 0.0
    if fixed:
        d.add(PADS([f"K{i}" for i in range(1, opt.count + 1)] + ["GND"],
                   [f"PT{i}_K" for i in range(1, opt.count + 1)] + ["GND"], "bias measurement: 1 mV = 1 mA", PWR))
    else:
        vk = opt.ik_ma / 1000.0 * opt.count * opt.rk
        pk = (opt.ik_ma / 1000.0 * opt.count) ** 2 * opt.rk
        d.add(R(fmt_r(opt.rk), k_shared, "GND", rpart(opt.rk, math.sqrt(pk * opt.rk)) if pk else "res5w", PWR),
              CP("100uF 63V", k_shared, "GND", "elco_63", PWR))
        d.volts[k_shared] = round(vk, 1)
        d.amps[k_shared] = round(idle * opt.count * 1.5, 3)
    if pp:
        d.add(PADS(["P1", "B+", "P2"], ["OT_P1", "B+1", "OT_P2"], f"push-pull OT primary ({opt.raa / 1000:g}k a-a)",
                   PWR, 10.16))
    else:
        d.add(PADS(["P", "B+"], ["OT_P", "B+1"], f"single-ended OT primary ({opt.raa / 1000:g}k)", PWR, 10.16))
    d.add(PADS(["SPK", "COM"], ["SPK", "GND"], f"OT {s.speaker} ohm secondary to the speaker jack", PWR))

    # --- currents ---------------------------------------------------------------------------------------------
    i_idle = idle * opt.count
    i_full = i_idle if not pp else max(i_idle, opt.pout / (opt.bplus * 0.55))
    rect = _rectifier(s, opt, i_full + 0.01, d.rep.warnings)
    rinfo = RECT[rect]

    # --- bias supply ---------------------------------------------------------------------------------------------
    bias_vac = 0.0
    if fixed:
        bias_vac = round(abs(opt.vbias) * 1.4 / SQ2 / 5 + 0.49) * 5 + 5
        d.add(PADS(["BIAS", "0V"], ["BIAS_AC", "GND"], f"PT bias tap (about {bias_vac:g} VAC)", PWR),
              D("1N4007", "BIAS_RAW", "BIAS_AC", "do41", PWR),
              CP("47uF 100V", "GND", "BIAS_RAW", "elco_8", PWR), R("2k2", "BIAS_RAW", "BIAS_F", "res_small", PWR),
              CP("47uF 100V", "GND", "BIAS_F", "elco_8", PWR), R("15k", "BIAS_F", "BIAS_OUT", "res_small", PWR),
              R("10k", "BIAS_OUT", "BIAS_ADJ", "res_small", PWR),
              P("RV", "B50K", "trimmer", {"1": "BIAS_ADJ", "2": "GND", "3": "GND"}, PWR, label="BIAS"),
              CP("22uF 100V", "GND", "BIAS_OUT", "elco_8", PWR))
        vf = -(bias_vac * SQ2 - 1.0) * 0.95
        d.volts.update({"BIAS_RAW": round(vf / 0.95), "BIAS_F": round(vf), "BIAS_OUT": opt.vbias,
                        "BIAS_ADJ": round(opt.vbias * 0.6)})
        d.vac["BIAS_AC"] = bias_vac
        lo, hi = vf * 10 / 25, vf * 60 / 75
        d.rep.power_rows.append(("Bias adjust range", f"{lo:.0f} V to {hi:.0f} V (fail-safe: an open trimmer gives "
                                                      "maximum negative bias)"))

    # --- B+ supply chain ---------------------------------------------------------------------------------------
    pre_slots = [sl for sl in d.slots if sl.section != PI]
    pi_slots = [sl for sl in d.slots if sl.section == PI]
    nodes = ["B+1", "B+2"]
    target = {"B+1": opt.bplus, "B+2": opt.bplus - (8 if s.choke else 15)}
    names = {}
    if pi_slots:
        nodes.append("B+3")
        target["B+3"] = opt.bplus * 0.88
        for sl in pi_slots:
            names[sl.node] = "B+3"
    level = target[nodes[-1]]
    for sl in reversed(pre_slots):  # the input tube gets the last, cleanest node
        n = f"B+{len(nodes) + 1}"
        nodes.append(n)
        level = min(level * 0.9, 320.0)  # preamp nodes: keep 12AX7 plates (and cathode followers) under 330 V
        target[n] = level
        names[sl.node] = n
    for sl in d.slots:
        if sl.node not in names:
            names[sl.node] = nodes[-1]
    # resolve placeholders
    for p in d.parts:
        p.nets = {k: names.get(n, n) for k, n in p.nets.items()}
    for sl in d.slots:
        sl.nets = {k: names.get(n, n) for k, n in sl.nets.items()}
        sl.node = names[sl.node]
    loads: dict = {}
    for node, fns in d.loads.items():
        loads.setdefault(names.get(node, node), []).extend(fns)
    screens = idle * opt.count * 0.08

    def node_currents(V):
        own = {n: sum(fn(V) for fn in loads.get(n, [])) for n in nodes}
        own["B+2"] = own.get("B+2", 0.0) + screens
        down, acc = {}, 0.0
        for n in reversed(nodes[1:]):
            acc += own[n]
            down[n] = acc
        return own, down

    V = dict(target)
    drops = {}
    for _ in range(3):
        _own, down = node_currents(V)
        for a, b in zip(nodes, nodes[1:]):
            if b == "B+2" and s.choke:
                drops[b] = ("choke", 100.0)
            elif b not in drops or drops[b][0] != "fixed":
                r = e12(max(100.0, (V[a] - target[b]) / max(down[b], 1e-4)))
                drops[b] = ("R", r)
            V[b] = V[a] - down[b] * drops[b][1]
    own, down = node_currents(V)
    V["@GND"] = 0.0
    for p_ in list(d.fins):
        p_(V)
    for i in range(1, opt.count + 1):
        d.volts[f"PT{i}_S"] = round(V["B+2"] - 3)

    # supply parts
    vac = math.ceil((opt.bplus + rinfo["drop"]) / (SQ2 * 0.95) / 5) * 5
    vnl = vac * SQ2 - (1 if rect == "ss" else 0)
    d.add(PADS(["HV1", "CT", "HV2"], ["HV1", "GND", "HV2"], f"PT HV secondary {vac:g}-0-{vac:g} VAC", PSU, 10.16))
    first = "B+0" if s.standby else "B+1"
    if rect == "ss":
        for leg in ("HV1", "HV2"):
            d.add(D("1N4007", leg, f"{leg}_D", "do41", PSU), D("1N4007", f"{leg}_D", first, "do41", PSU))
            d.vac[f"{leg}_D"] = vac / 2
    else:
        rt = TUBES[rect]
        nets = {"A1": "HV1", "A2": "HV2"}
        if rt.pin("HK"):
            nets["HK"], nets["H"] = first, "FIL"
            d.add(PADS(["5V1", "5V2"], ["FIL", first], f"PT 5 V {rinfo['heater'][1]:g} A rectifier heater winding",
                       PSU, 10.16))
            d.extra_tubes.append((rect, PSU, nets, None))
            d.volts["FIL"] = opt.bplus
            d.vac["FIL"] = 5.0
            d.amps["FIL"] = rinfo["heater"][1]
        else:
            nets["K"] = first
            d.extra_tubes.append((rect, PSU, nets))
    if s.standby:
        d.add(PADS(["SB1", "SB2"], ["B+0", "B+1"], "standby switch (on the chassis)", PSU, 10.16))
    d.vac.update({"HV1": vac, "HV2": vac})
    caps: list = []

    def hv_cap(net, farads, sec=PSU, volts_on=None):
        # a solid-state or directly heated rectifier charges every node to the no-load voltage before the tubes
        # conduct; a slow-starting (indirectly heated) tube rectifier only ever reaches the working voltage
        vmax = vnl if (rect == "ss" or rinfo["direct"]) else (volts_on or V.get(net, 0)) * 1.05
        uf = farads * 1e6
        working = volts_on or V.get(net, 0)
        rating = next((r for r in (400, 450, 500) if vmax <= r and working <= 0.9 * r), None)
        if rating is not None:  # single part: rated for switch-on and run at no more than 90 % of its rating
            sizes = ["elco_hv", "elco_hv33", "elco_hv_big", "snapin_25", "snapin_35"]
            k = 0 if uf <= 22 else 1 if uf <= 33 else 2 if uf <= 47 else 3 if uf <= 100 else 4
            key = sizes[min(4, k + (1 if rating == 500 else 0))]  # 500 V parts are a size larger
            d.add(CP(f"{uf:g}uF {rating}V", net, "GND", key, sec))
            caps.append((net, f"{uf:g} uF / {rating} V"))
            return
        mid = f"{net}_MID"  # two caps in series with balancing resistors
        each = next((c for c in STD_UF if c >= 2 * uf * 0.95), 2 * uf)
        key = "elco_hv33" if each <= 33 else "elco_hv_big" if each <= 47 else "snapin_25" if each <= 100 else "snapin_35"
        d.add(CP(f"{each:g}uF 350V", net, mid, key, sec), CP(f"{each:g}uF 350V", mid, "GND", key, sec),
              R("220k", net, mid, "res2w", sec), R("220k", mid, "GND", "res2w", sec))
        d.volts[mid] = round(V.get(net, opt.bplus) / 2)
        caps.append((net, f"2 x {each:g} uF / 350 V in series (balanced by 220k)"))

    if rect == "ss":
        c1 = 100e-6 if opt.pout <= 60 else 220e-6
        if opt.pout <= 20:
            c1 = 47e-6
    else:
        c1 = min(rinfo["cmax"], 32e-6 if rect != "5Y3GT" else 16e-6)
    if s.standby:
        hv_cap("B+0", c1)
        d.add(R("220k", "B+0", "GND", "res3w", PSU))
        d.volts["B+0"] = round(V["B+1"])
        hv_cap("B+1", 22e-6)
    else:
        hv_cap("B+1", c1)
    # each node's dropping resistor and filter cap sit next to the stage they feed, so B+ runs as a short chain
    # along the board instead of every preamp node being wired back to the supply corner
    node_sec = {"B+2": PWR}
    for sl in d.slots:
        node_sec.setdefault(sl.node, sl.section)
    for a, b in zip(nodes, nodes[1:]):
        kind, val = drops[b]
        sec = node_sec.get(b, PSU)
        if kind == "choke":
            d.add(PADS(["CHK1", "CHK2"], [a, b], "filter choke", PSU, 10.16))
        else:
            d.add(R(fmt_r(val), a, b, rpart(val, V[a] - V[b]), sec))
        hv_cap(b, (47e-6 if opt.pout >= 60 else 32e-6) if b == "B+2" else 22e-6, sec=sec)
    bleeder_v = V["B+1"]
    d.add(R("220k", "B+1", "GND", rpart(220e3, bleeder_v), PSU))
    for n in nodes:
        d.volts[n] = round(V[n])
    d.volts["B+1"] = round(opt.bplus)
    d.amps["B+1"] = round(i_full + down.get("B+2", 0), 3)
    if rect != "ss" and TUBES[rect].pin("HK"):
        d.amps["FIL"] = max(d.amps.get("FIL", 0), d.amps["B+1"])

    # --- power tube nets ------------------------------------------------------------------------------------------
    swing = opt.bplus / SQ2
    for n in (["OT_P1", "OT_P2"] if pp else ["OT_P"]):
        d.volts[n] = round(opt.bplus - 5)
        d.vac[n] = round(swing)
        d.amps[n] = round(i_full / (2 if pp else 1), 3)
    vout = math.sqrt(opt.pout * s.speaker)
    d.vac["SPK"] = round(vout, 1)
    d.amps["SPK"] = round(vout / s.speaker, 2)

    # --- heaters ------------------------------------------------------------------------------------------------
    h_ref = "GND"
    if d.cf:
        h_ref = "HTR_EL"
        top = nodes[2] if len(nodes) > 2 else "B+2"
        r1 = e12(100e3 * (V[top] / 55.0 - 1))
        d.add(R(fmt_r(r1), top, "HTR_EL", rpart(r1, V[top] - 55), PSU), R("100k", "HTR_EL", "GND", "res_small", PSU),
              CP("47uF 100V", "HTR_EL", "GND", "elco_8", PSU))
        d.volts["HTR_EL"] = round(V[top] * 100e3 / (100e3 + r1))
        d.rep.tips.append(f"The heaters are elevated to about +{d.volts['HTR_EL']} V: the cathode follower's cathode "
                          "sits near 200 V, and this keeps the heater-to-cathode voltage inside the 12AX7's rating "
                          "(and lowers hum).")
    d.add(PADS(["H1", "H2"], ["HTR1", "HTR2"], "PT 6.3 V heater winding", PSU),
          P("W", "STAR GND", "star", {"1": "GND"}, PSU, show_value=False))
    dc_slots = [sl for sl in d.slots if sl.section != PI] if s.dc_heaters else []
    i_dc = 0.0
    if dc_slots:
        # the preamp tubes' heaters on DC: Schottky bridge, CRC filter; the bridge also references the AC winding
        # (so no 100R hum-balance pair), and its negative sits on the heater elevation when there is one
        i_dc = sum(TUBES[sl.tube].heater_a for sl in dc_slots)
        ripple = i_dc / (2 * 50 * 0.01)
        v_raw = 6.3 * SQ2 - 2 * 0.45 - ripple / 2
        r_h = max(0.1, e12((v_raw - 6.3) / i_dc))
        d.add(D("1N5822", "HTR1", "HDC_R", "do201", PSU), D("1N5822", "HTR2", "HDC_R", "do201", PSU),
              D("1N5822", h_ref, "HTR1", "do201", PSU), D("1N5822", h_ref, "HTR2", "do201", PSU),
              CP("10000uF 16V", "HDC_R", h_ref, "elco_heater", PSU),
              R(fmt_r(r_h), "HDC_R", "HDC", rpart(r_h, r_h * i_dc), PSU),
              CP("10000uF 16V", "HDC", h_ref, "elco_heater", PSU))
        lift = d.volts.get("HTR_EL", 0.0) if h_ref != "GND" else 0.0
        d.volts.update({"HDC_R": round(lift + v_raw, 1), "HDC": round(lift + v_raw - r_h * i_dc, 1)})
        d.amps.update({"HDC_R": round(i_dc, 2), "HDC": round(i_dc, 2)})
        d.rep.tips.append(f"The {len(dc_slots)} preamp tubes' heaters run on filtered DC (about "
                          f"{v_raw - r_h * i_dc:.1f} V, {i_dc:.1f} A): no heater hum in the high-gain stages. "
                          "Measure it with the tubes in: 6.0-6.6 V is right; change the "
                          f"{fmt_r(r_h)} dropping resistor if it is outside that.")
    else:
        d.add(R("100R", "HTR1", h_ref, "res_small", PSU), R("100R", "HTR2", h_ref, "res_small", PSU))

    # --- tubes ---------------------------------------------------------------------------------------------------
    for sl in d.slots:
        for x in sl.free:  # spare section: ground grid and cathode
            sl.nets.update({"G" + x: "GND", "K" + x: "GND"})
        d.add(TUBE(sl.tube, sl.nets, heater=("HDC", h_ref) if sl in dc_slots else ("HTR1", "HTR2"),
                   sec=sl.section))
    for entry in d.extra_tubes:
        name, sec, nets = entry[0], entry[1], entry[2]
        heater = entry[3] if len(entry) > 3 else ("HTR1", "HTR2")
        d.add(TUBE(name, nets, heater=heater, sec=sec))
    tubes = [p.value for p in d.parts if p.prefix == "V"]
    if local_heaters:
        d.rep.tips.append(f"The {opt.count} {opt.tube}s draw {pt.heater_a * opt.count:.1f} A of heater current: run "
                          "twisted pairs from the 6.3 V winding to each power tube's H1/H2 pads (or daisy-chain the "
                          "pads) instead of wide board traces; the preamp tubes' heaters stay on the board.")
    h63 = sum(TUBES[t].heater_a for t in tubes if TUBES[t].heater_v == 6.3 and not (TUBES[t].pin("HK")))
    h63 += i_dc * 0.8  # a capacitor-input rectifier draws about 1.8 x its DC current (rms) from the winding
    d.vac.update({"HTR1": 3.2, "HTR2": 3.2})
    if h_ref != "GND":
        d.volts.update({"HTR1": d.volts["HTR_EL"], "HTR2": d.volts["HTR_EL"]})
        for i in range(1, opt.count + 1):
            if local_heaters:
                d.volts.update({f"PT{i}_H1": d.volts["HTR_EL"], f"PT{i}_H2": d.volts["HTR_EL"]})
    h_board = h63 - (pt.heater_a * opt.count if local_heaters else 0.0)  # what the board's heater traces carry
    d.amps.update({"HTR1": round(h_board, 2), "HTR2": round(h_board, 2)})
    if dc_slots:
        d.vac.update({"HTR1": 4.5, "HTR2": 4.5})  # referenced by the bridge: each leg swings 0 to 9 V

    # --- report ------------------------------------------------------------------------------------------------
    rep = d.rep
    rep.tubes = tubes
    rep.pout = opt.pout
    va = opt.bplus - (0 if fixed else (opt.ik_ma / 1000 * opt.count * opt.rk))
    ia_plate = idle * 0.9
    pd = va * ia_plate
    rep.power_rows[:0] = [
        ("Output", f"{opt.count} x {opt.tube}, {'push-pull class AB' if pp else 'single-ended class A'}, "
                   f"{opt.bias_text}"),
        ("Output power", f"about {opt.pout:g} W clean into {s.speaker} ohm"),
        ("B+ / plate", f"{opt.bplus:g} V at the OT, about {va:.0f} V plate to cathode"),
        ("Idle current", f"{opt.ik_ma:g} mA per tube" + (f" (bias about {opt.vbias:g} V)" if fixed else
                                                          f" through a shared {fmt_r(opt.rk)} cathode resistor "
                                                          f"({d.volts.get(k_shared, 0):g} V)")),
        ("Plate dissipation", f"{pd:.1f} W per tube = {pd / pt.pa_max:.0%} of the {pt.pa_max:g} W rating"),
    ]
    if pd > 0.92 * pt.pa_max:
        rep.warnings.append(f"The {opt.tube}s idle at {pd / pt.pa_max:.0%} of their plate rating: expect short tube life.")
    if opt.bplus > pt.va_max:
        rep.tips.append(f"Like the classic amps it is modelled on, this runs the {opt.tube}s above their "
                        f"{pt.va_max:g} V data-sheet plate rating (DRC notes it): fit rugged modern {opt.tube}s "
                        f"({'JJ 6V6S or Tung-Sol 6V6GT' if opt.tube == '6V6GT' else 'JJ or Electro-Harmonix EL84'}).")
    rep.spl = 100 + 10 * math.log10(opt.pout)
    # gain and headroom
    drive_pk = abs(opt.vbias) if fixed else (opt.ik_ma / 1000 * opt.count * opt.rk)
    _headroom(d, drive_pk / SQ2)
    knobs = [el.label for el in d.path if isinstance(el, gs.Net) and el.pot]
    gain_knob = "GAIN" if "GAIN" in knobs else ("VOLUME" if "VOLUME" in knobs else "")
    rep.analysis = gs.analyse(d.path, 1.0 if s.instrument == "bass" else 0.42, gain_knob)
    if s.voicing in HIGH_GAIN and gain_knob:
        # with a master volume the preamp does the distorting: where on the GAIN knob it starts
        rep.breakup = tuple(round(gs.breakup_knob(d.path, lv * SQ2, gain_knob), 1) for lv in (0.1, 0.3))
        rep.breakup_knob = gain_knob
        b = rep.breakup[1]  # humbuckers: what high-gain players use
        rep.character = ("High gain: saturated from low GAIN settings - lead and heavy rhythm" if b < 2 else
                         "Crunch to high gain: crunchy low on the GAIN, saturated as you turn it up" if b < 5 else
                         "Clean to crunch on the GAIN knob")
    # supply table
    for n in nodes:
        feeds = {"B+1": "output transformer (plates)", "B+2": "screens"}.get(n, "")
        if not feeds:
            users = sorted({sl.section for sl in d.slots if sl.node == n})
            feeds = ", ".join({"PI": "phase inverter"}.get(u, u.lower()) for u in users) or "-"
        filt = next((c for net, c in caps if net == n), "")
        how = "" if n == "B+1" else (f"choke from {nodes[nodes.index(n) - 1]}" if drops[n][0] == "choke"
                                     else f"{fmt_r(drops[n][1])} from {nodes[nodes.index(n) - 1]}")
        rep.supply.append((n, round(V[n]), round((own.get(n, 0) + (i_full if n == "B+1" else 0)) * 1000, 1),
                           feeds, ", ".join(x for x in (how, filt) if x)))
    # what to buy
    i_hv = (i_full + down.get("B+2", 0)) * 1.15
    rect_h = "" if (rect == "ss" or rinfo["heater"][0] == 6.3) else f", 5 V {rinfo['heater'][1]:g} A (rectifier)"
    h_total = h63 + (rinfo["heater"][1] if rect == "EZ81" else 0)
    va_pt = vac * 2 * i_hv * 0.75 + 6.3 * h_total + (rinfo["heater"][1] * 5 if rect_h else 0) + (5 if fixed else 0)
    fuse = _fuse(va_pt / s.mains * 1.6)
    rep.buy = [
        ("Power transformer", f"{vac:g}-0-{vac:g} VAC at {i_hv * 1000:.0f} mA DC, 6.3 V {h_total * 1.2:.1f} A"
                              f"{rect_h}" + (f", bias tap about {bias_vac:g} VAC" if fixed else "") +
                              f"; {s.mains} V primary, about {va_pt:.0f} VA"),
        ("Output transformer", f"{opt.raa / 1000:g}k {'plate-to-plate' if pp else 'primary (gapped, '}"
                               f"{'' if pp else f'{i_idle * 1000:.0f} mA DC)'} to {s.speaker} ohm, "
                               f"{max(opt.pout * 1.3, 5):.0f} W or more"),
    ]
    if s.choke:
        rep.buy.append(("Filter choke", f"5-10 H, {max(down.get('B+2', 0) * 1000 * 1.5, 30):.0f} mA or more"))
    rep.buy += [("Mains fuse", f"T{fuse} A slow-blow ({s.mains} V), plus a power switch"),
                ("Tubes", ", ".join(f"{tubes.count(t)} x {t}" for t in dict.fromkeys(tubes))),
                ("Rectifier", f"{rect} tube" if rect != "ss" else "4 x 1N4007 on the board (solid state)"),
                ("Speaker", f"{s.speaker} ohm, {opt.pout * 1.5:.0f} W or more"),
                ("Chassis parts", "1/4\" speaker jack, power and (optional) standby switches, mains inlet, "
                                  "pilot lamp, knobs")]
    _tips_tube(d, opt, rect, nfb)
    if s.voicing in HIGH_GAIN:
        _tips_metal(d, opt)
    _voltage_chart(d)
    rep.powerup = [
        "Check every electrolytic's polarity, the heater wiring and the mains wiring before the first switch-on, "
        "and bring the amp up through a dim-bulb tester or a variac.",
        f"With no tubes fitted the heaters should read 6.3 VAC at the sockets and B+ will sit high (about "
        f"{vnl:.0f} V): the filter caps are rated for it.",
        "Always connect a speaker (or a load resistor) before playing: an unloaded output transformer can arc "
        "and destroy the power tubes or itself.",
        ("Fit the tubes with the BIAS trimmer at maximum negative bias, then set "
         f"{opt.ik_ma * 0.9:.0f} mA per tube ({opt.ik_ma * 0.9:.0f} mV across each 1R)." if fixed else
         f"Fit the tubes and check the shared cathode reads about {d.volts.get(k_shared, 0):g} V."),
        "Measure the B+ nodes and the tube pins against the tables below: within 10-15 % means the amp is "
        "healthy.",
    ]
    title = s.name or f"{v.label} {opt.pout:g}W"
    # the feedback is taken from SPK into the long-tail pair's tail, so SPK must be in phase with the PI input,
    # which is in phase with P1 (PI plate A drives the P1 side, and both stages invert)
    d.ot = {"primary_ohms": opt.raa, "secondary_ohms": s.speaker, "power_w": opt.pout,
            "nfb_polarity": 1, "push_pull": pp}
    return _assemble(d, title, [PSU, PWR, PI, LOOP, TONE, GAIN, PRE])


def _voltage_chart(d: _D) -> None:
    """Expected DC voltage at every tube pin, in board order (V1, V2 ...), like a schematic's voltage chart."""
    n = 0
    for part in d.parts:
        if part.prefix != "V":
            continue
        n += 1
        t = TUBES[part.value]
        rows = []
        for pin in sorted(part.nets, key=int):
            net = part.nets[pin]
            fn = t.pins.get(pin, "")
            if fn in ("H", "HCT") and net in ("HTR1", "HTR2") or net.endswith(("_H1", "_H2")):
                lift = d.volts.get(net)
                rows.append((pin, fn, f"6.3 VAC on +{lift:g} V" if lift else "6.3 VAC"))
                continue
            volts = 0.0 if net == "GND" else d.volts.get(net)
            if volts is None and fn.startswith("G"):  # a grid returned to ground through its grid leak
                volts = 0.0
            if volts is None and net in d.vac:  # rectifier anodes: the HV winding
                rows.append((pin, fn, f"{d.vac[net]:g} VAC"))
            elif volts is not None:
                rows.append((pin, fn, f"{volts:g} V" if abs(volts) >= 10 else f"{volts:.1f} V"))
        d.rep.chart.append((f"V{n}", part.value, rows))


def _fuse(amps: float) -> str:
    for f in (0.5, 0.63, 0.8, 1, 1.25, 1.6, 2, 2.5, 3.15, 4, 5, 6.3):
        if f >= amps:
            return f"{f:g}"
    return "8"


def _headroom(d: _D, drive_rms: float) -> None:
    rep = d.rep
    g = 1.0
    for label, gain, note in d.gains:
        g *= gain
        rep.stages.append((label, gain, note))
    rep.gain_db = 20 * math.log10(max(g, 1e-9))
    rep.sensitivity_mv = drive_rms / max(g, 1e-9) * 1000
    pos = []
    levels = (0.25, 0.7) if d.s.instrument == "bass" else (0.1, 0.3)  # passive / active bass; single coil / humbucker
    rep.instrument = d.s.instrument
    for guitar in levels:  # typical instrument output, volts rms
        a = min(1.0, drive_rms / max(g * guitar, 1e-12))
        pos.append(round(10 * math.log(1 + 80 * a) / math.log(81), 1))
    rep.breakup = tuple(pos)
    b = pos[0]
    if b < 2:
        rep.character = "High gain: it saturates from low settings - for lead and heavy rhythm"
    elif b < 4:
        rep.character = "Crunch: breaks up early; roll your guitar's volume back to clean up"
    elif b < 7:
        rep.character = "Edge of breakup: clean at low settings, growls when you dig in or turn up"
    else:
        rep.character = "Clean headroom: stays clean - a great pedal platform"


HIGH_GAIN = ("highgain", "modern", "extreme")


def _tips_metal(d: _D, opt: PowerOption) -> None:
    """Advice for high-gain metal amps: tightness, noise, the pedals that suit them, speakers."""
    s, rep, an = d.s, d.rep, d.rep.analysis
    if an is not None and an.lows:
        e, b, fs = (round(x[2]) for x in an.lows)
        rep.tips.insert(0, f"Tightness '{s.tight}': going into the distortion the low E (82 Hz) is {abs(e)} dB down "
                           f"on the mids, a 7-string's low B {abs(b)} dB and an 8-string's F# {abs(fs)} dB. "
                           + {"fat": "Big and loose - for doom, stoner and slow, heavy riffs.",
                              "normal": "Classic thrash and hard-rock tightness.",
                              "tight": "Fast palm mutes stay articulate; the DEPTH control puts the thump back in "
                                       "the power amp.",
                              "djent": "Very tight for extended-range guitars and drop tunings - the low end comes "
                                       "back from the power amp's DEPTH control and the cabinet."}[s.tight])
    rep.pedals = [("noise_gate", "in the effects loop, keyed from your guitar (4-cable method): silence between "
                                 "riffs without choking the notes"),
                  ("tight_boost", "in front of the input: tightens the low end and focuses the mids for palm "
                                  "mutes and solos"),
                  ("distortion", "a high-gain distortion pedal for a second voice, or into a clean amp")]
    rep.tips += [
        "Hiss: " + (f"with the gain on 10 the input stage's hiss comes within {an.hiss_margin:.0f} dB of clipping "
                    f"{an.hiss_stage}, so expect audible hiss between riffs - " if an and an.hiss_margin < 25 else
                    "the hiss stays well below the clipping stages; ") +
        "a noise gate in the effects loop (keyed from the guitar) is the standard cure - see Amp > Metal pedals.",
        "Low noise: fit a low-noise (selected) 12AX7 as V1, use metal-film resistors in the first two stages, "
        "shielded wire to the input jack, and keep the heater and mains wiring twisted and away from V1/V2.",
        "A tight boost in front (Tube Screamer style, drive at zero, level up) is the classic metal trick: it "
        "cuts the lows before the preamp and pushes the mids - the Tight Boost pedal in Amp > Metal pedals.",
        "Cabinet: a closed-back 2x12 or 4x12 with Vintage 30 / G12K-100 class speakers; set DEPTH for the low-end "
        "thump of your cab and PRESENCE for the cut." if s.depth else
        "Cabinet: a closed-back 2x12 or 4x12 with Vintage 30 / G12K-100 class speakers.",
    ]
    if not s.dc_heaters:
        rep.tips.append("For the quietest amp, tick 'DC heaters' to run the preamp tubes' heaters on DC.")
    if not s.fx_loop:
        rep.tips.append("Add the effects loop: a noise gate and time effects (delay, reverb) belong after the "
                        "preamp's distortion.")
    if opt.bias == "fixed":
        rep.tips.append("For the tightest low end bias the power tubes on the cool side (60-70 % of their plate "
                        "rating) and use a solid-state rectifier - both are this design's defaults.")


def _tips_tube(d: _D, opt: PowerOption, rect: str, nfb: str) -> None:
    s, rep = d.s, d.rep
    if opt.bias == "fixed":
        ma = opt.ik_ma * 0.9
        rep.tips.append(f"Before the first power-up turn the BIAS trimmer for the most negative bias, then set it for "
                        f"about {ma:.0f} mA per tube: {ma:.0f} mV across each 1R cathode resistor (pads K1-K"
                        f"{opt.count}).")
    if nfb != "off":
        rep.tips.append("If the amp squeals or motorboats when you turn it up, the feedback is positive: swap the two "
                        "output-transformer secondary leads (SPK / COM).")
    if rect != "ss":
        rep.tips.append(f"The {rect} rectifier sags under load: softer attack and compression when you play hard.")
        if s.instrument == "bass":
            rep.tips.append("For tighter bass use the solid-state rectifier option.")
    else:
        rep.tips.append("Solid-state rectification gives a tight, punchy response with full B+ at switch-on; the filter "
                        "caps are rated for the no-load voltage.")
    if s.voicing == "blackface" and s.v1 == "12AX7":
        rep.tips.append("Want even more clean headroom? Try a 12AT7 or 5751 as V1 (change it above).")
    if s.voicing == "tweed" and opt.pp:
        rep.tips.append("Tweed amps get their character from the power stage running flat out: keep the speaker "
                        "efficient and the rectifier a tube.")
    if not s.master and s.voicing in ("plexi", "tweed", "chime"):
        rep.tips.append("These amps sound best loud. Add a master volume above if you need the crunch at home "
                        "levels.")
    rep.tips.append("Mains wiring (inlet, fuse, switch, transformer primary) stays on the chassis. The board "
                    "carries lethal voltages: the bleeder drains the caps in about a minute - always measure B+ "
                    "before touching anything.")


# --------------------------------------------------------------------------- solid-state amp

def _design_ss(d: _D) -> AmpDesign:
    s = d.s
    v = VOICINGS[s.voicing]
    label, rail, vac = SS_POWER[s.power]
    if rail > 30 and s.speaker < 8:
        d.rep.warnings.append("+/-35 V rails overheat an LM3886 into 4 ohm: using +/-28 V instead.")
        label, rail, vac = SS_POWER["lm3886_40"]
    PRE, TONE, OUT, PSU = "Preamp", "Tone", "Output", "Supply"
    bass = s.instrument == "bass"
    drive = s.voicing == "ss_drive"
    stack = {"ss_clean": "Fender Blackface (AB763 Twin)", "ss_drive": "Marshall JCM800 2203",
             "ss_bass": "Bass amp (deep, Bassman with 47n bass cap)"}[s.voicing]
    d.add(P("J", "INPUT", "jack", {"T": "IN", "S": "GND"}, PRE, "front", "INPUT"),
          R("1M", "IN", "GND", "res_small", PRE), C("100nF 63V", "IN", "U1_INP", "film", PRE),
          R("1M", "U1_INP", "GND", "res_small", PRE),
          P("U", "TL072", "dip8", {"1": "U1A_OUT", "2": "U1A_FB", "3": "U1_INP", "4": "V-15", "5": "U1B_INP",
                                   "6": "U1B_FB", "7": "U1B_OUT", "8": "V+15"}, PRE),
          R("10k", "U1A_FB", "U1A_GF", "res_small", PRE), CP("10uF 25V", "U1A_GF", "GND", "elco_lv", PRE),
          R("10k", "U1A_FB", "U1A_RV", "res_small", PRE),
          POT("A100K" if not drive else "A500K", "U1A_RV", "U1A_OUT", "U1A_OUT", "GAIN", PRE),
          C("100pF 50V", "U1A_OUT", "U1A_FB", "ceramic", PRE),
          CP("47uF 25V", "V+15", "GND", "elco_lv", PRE), CP("47uF 25V", "GND", "V-15", "elco_lv", PRE),
          C("100nF 63V", "V+15", "GND", "film_small", PRE), C("100nF 63V", "GND", "V-15", "film_small", PRE))
    g1 = 1 + (10e3 + (500e3 if drive else 100e3)) / 10e3
    d.gains.append(("Gain stage (TL072)", g1, "non-inverting, gain control in the feedback loop"))
    tsi = "U1A_OUT"
    if drive:
        d.add(R("4k7", "U1A_OUT", "CLIP", "res_small", PRE), D("1N4148", "CLIP", "GND", "do35", PRE),
              D("1N4148", "GND", "CLIP", "do35", PRE))
        tsi = "CLIP"
        d.gains.append(("Diode clipper", 1.0, "1N4148 pair: soft clipping above about 0.5 V"))
    ts = PRESETS[stack]
    d.add(*stack_parts(ts, tsi, "TS_OUT", "TS", TONE))
    loss = 10 ** (response_db(replace(ts, rs=100.0), 5, 5, 5, np.array([1000.0]))[0] / 20)
    d.gains.append(("Tone stack", loss, f"{stack.split(' (')[0]}, controls at noon (1 kHz)"))
    d.rep.tone, d.rep.tone_name = replace(ts, rs=100.0), stack.split(" (")[0]
    d.add(R("1M", "TS_OUT", "GND", "res_small", TONE), R("10k", "TS_OUT", "U1B_INP", "res_small", TONE),
          R("100k", "U1B_OUT", "U1B_FB", "res_small", TONE), R("10k", "U1B_FB", "U1B_GF", "res_small", TONE),
          CP("10uF 25V", "U1B_GF", "GND", "elco_lv", TONE))
    d.gains.append(("Recovery stage (TL072)", 11.0, "makes up the tone-stack loss"))
    feed = "U1B_OUT"
    if s.fx_loop:
        d.add(R("100R", "U1B_OUT", "SEND", "res_small", TONE),
              P("J", "SEND", "jack", {"T": "SEND", "S": "GND"}, OUT, "front", "SEND"),
              P("J", "RETURN", "jack", {"T": "RET", "TN": "U1B_OUT", "S": "GND"}, OUT, "front", "RETURN"))
        feed = "RET"
    master_top = feed
    d.add(POT("A10K", "GND", "MASTER", master_top, "MASTER" if s.master else "VOLUME", OUT))
    d.add(C("1uF 63V", "MASTER", "U2_INA", "film", OUT), R("47k", "U2_INA", "GND", "res_small", OUT),
          R("1k", "U2_INA", "U2_INP", "res_small", OUT),
          P("U", "LM3886TF", "lm3886", {"1": "V+", "3": "SPK", "4": "V-", "5": "V+", "7": "GND", "8": "MUTE",
                                        "9": "U2_INN", "10": "U2_INP"}, OUT, "rear"),
          R("20k", "SPK", "U2_INN", "res_small", OUT), R("1k", "U2_INN", "U2_GF", "res_small", OUT),
          CP("47uF 25V", "U2_GF", "GND", "elco_lv", OUT), R("10k", "MUTE", "V-", "res_small", OUT),
          R("2R7", "SPK", "ZOB", "res1w", OUT), C("100nF 63V", "ZOB", "GND", "film", OUT),
          CP("220uF 63V", "V+", "GND", "elco_63", OUT), CP("220uF 63V", "GND", "V-", "elco_63", OUT),
          C("100nF 63V", "V+", "GND", "film_small", OUT), C("100nF 63V", "GND", "V-", "film_small", OUT))
    d.gains.append(("LM3886 power amp", 21.0, "gain 21 (20k / 1k)"))
    d.add(P("U", "KBU810", "bridge", {"1": "V+", "2": "AC1", "3": "AC2", "4": "V-"}, PSU),
          PADS(["AC1", "CT", "AC2"], ["AC1", "GND", "AC2"], f"PT secondary 2 x {vac:g} VAC", PSU, 7.62),
          CP("10000uF 50V" if rail <= 30 else "10000uF 63V", "V+", "GND", "snapin", PSU),
          CP("10000uF 50V" if rail <= 30 else "10000uF 63V", "GND", "V-", "snapin", PSU),
          R("4k7", "V+", "GND", "res1w", PSU), R("4k7", "GND", "V-", "res1w", PSU),
          R(fmt_r(e12((rail - 15) / 0.013)), "V+", "V+15", "res1w", PSU),
          R(fmt_r(e12((rail - 15) / 0.013)), "V-15", "V-", "res1w", PSU),
          D("1N4744A", "GND", "V+15", "do41", PSU), D("1N4744A", "V-15", "GND", "do41", PSU),
          P("W", "STAR GND", "star", {"1": "GND"}, PSU, show_value=False))
    if bass and s.di_out:
        d.add(P("J", "DI OUT", "xlr_out", {"1": "GND", "2": "DI_H", "3": "DI_C", "G": "GND"}, PRE, "front", "DI OUT"),
              C("1uF 63V", "U1A_OUT", "DI_A", "film", PRE), R("100k", "DI_A", "GND", "res_small", PRE),
              R("100R", "DI_A", "DI_H", "res_small", PRE), R("100R", "DI_C", "DI_CG", "res_small", PRE),
              C("1uF 63V", "DI_CG", "GND", "film", PRE))
    if bass:
        d.add(P("J", "SPEAKER", "speakon", {"1+": "SPK", "1-": "GND"}, OUT, "front", "SPEAKER"))
    else:
        d.add(P("J", "SPEAKER", "jack", {"T": "SPK", "S": "GND"}, OUT, "front", "SPEAKER"))
    vpk = rail - 4.0
    pout = min(vpk * vpk / (2 * s.speaker), 68.0 if s.speaker <= 4 else 60.0)
    d.volts.update({"V+": rail, "V-": -rail, "V+15": 15, "V-15": -15, "MUTE": -1})
    d.vac.update({"AC1": vac, "AC2": vac, "SPK": round(vpk / SQ2, 1)})
    ia = vpk / s.speaker / SQ2 * 1.2
    d.amps.update({"V+": round(ia, 2), "V-": round(ia, 2), "AC1": round(ia * 1.4, 2), "AC2": round(ia * 1.4, 2),
                   "SPK": round(vpk / s.speaker / SQ2, 2), "GND": round(ia, 2)})
    rep = d.rep
    rep.pout = round(pout)
    rep.spl = 100 + 10 * math.log10(pout)
    rep.tubes = []
    rep.power_rows = [("Output", "LM3886TF chip amplifier (isolated tab), gain 21"),
                      ("Output power", f"about {pout:.0f} W into {s.speaker} ohm"),
                      ("Rails", f"+/-{rail:g} V from a 2 x {vac:g} VAC transformer"),
                      ("Heatsink", f"{max(0.5, min(1.5, 40 / pout)):.1f} K/W or better (the chip dissipates up to "
                                   f"{pout * 0.6:.0f} W)")]
    _headroom(d, vpk / SQ2)
    va = pout * 2.2
    rep.buy = [("Power transformer", f"2 x {vac:g} VAC (centre-tapped {vac * 2:g} VAC), {va:.0f} VA, "
                                     f"{s.mains} V primary"),
               ("Mains fuse", f"T{_fuse(va / s.mains * 2.0)} A slow-blow"),
               ("Heatsink", rep.power_rows[-1][1]),
               ("Speaker", f"{s.speaker} ohm, {pout * 1.5:.0f} W or more"),
               ("Chassis parts", "mains inlet with fuse holder, power switch, knobs")]
    rep.powerup = [
        "Check the bridge, electrolytic polarity and the transformer wiring, then power up through a dim-bulb "
        "tester or a variac.",
        f"Measure the rails: about +/-{rail:g} V, and +/-15 V after the zener regulators.",
        "With no speaker connected, the DC at the speaker output must be under 50 mV before you plug one in.",
    ]
    rep.tips += ["Bolt the LM3886TF (isolated package) to the heatsink with thermal paste; the board's rear edge "
                 "lines the tab up.",
                 "The 10k from MUTE to -V releases the mute; the amp stays silent if it is missing."]
    if s.fx_loop:
        rep.tips.append("The RETURN jack's switch passes the signal straight through when nothing is plugged in.")
    if bass and s.di_out:
        rep.tips.append("The XLR DI is impedance balanced and taken before the tone controls (pin 2 hot).")
    title = s.name or f"{v.label} {pout:.0f}W"
    return _assemble(d, title, [PSU, OUT, TONE, PRE])


# --------------------------------------------------------------------------- assembly & entry point

def _assemble(d: _D, title: str, sections: list) -> AmpDesign:
    rep = d.rep
    rep.title = title
    rep.parts = len(d.parts)
    volts = {k: v for k, v in d.volts.items() if v is not None}
    used = [s for s in sections if any(p.section == s for p in d.parts)]
    notes = report_text(rep)
    n = len(d.parts)
    height = 115.0 if n <= 55 else 130.0 if n <= 75 else 145.0 if n <= 95 else 160.0  # taller, not wider
    from dataclasses import asdict
    return AmpDesign(title, used, d.parts, volts=volts, vac=d.vac, amps=d.amps, notes=notes, height=height,
                     spec=asdict(d.s), ot=dict(d.ot))


def design_amp(spec: AmpSpec) -> tuple[AmpDesign, Report]:
    """Design an amp from the user's choices. Returns the circuit (for build_amp) and the report."""
    s = spec.resolved()
    d = _D(s)
    design = _design_ss(d) if s.tech == "ss" else _design_tube(d)
    return design, d.rep


def options_for(instrument: str, tech: str) -> tuple[list, list]:
    """(voicing keys, power keys) that fit an instrument and technology."""
    vs = [k for k, v in VOICINGS.items() if v.tech == tech and v.instrument in (instrument, "any")]
    if tech == "ss":
        return vs, list(SS_POWER)
    ps = [k for k, o in POWER.items() if instrument == "guitar" or o.pout >= 35]
    return vs, ps


def power_label(key: str) -> str:
    return POWER[key].label if key in POWER else SS_POWER[key][0]


# --------------------------------------------------------------------------- report rendering

PEDAL_NAMES = {"noise_gate": "Noise gate (4-cable, for the effects loop)", "tight_boost": "Tight boost",
               "distortion": "High-gain distortion"}


def _drive_state(db: float) -> str:
    return "clean" if db < -3 else "on the edge" if db < 0 else f"clips, +{db:.0f} dB"


def _power_effects(fb: gs.Feedback) -> list:
    """(control, text) for the presence and depth controls: their largest boost and where."""
    out = []
    f = np.array([80.0, 4000.0])
    flat = gs.power_response(fb, f)
    if fb.pres_c:
        db = gs.power_response(fb, f, presence=10.0) - flat
        out.append(("Presence", f"up to +{db[1]:.0f} dB at 4 kHz (in the power amp, after the distortion)"))
    if fb.depth_c:
        db = gs.power_response(fb, f, depth=10.0) - flat
        out.append(("Depth", f"up to +{db[0]:.0f} dB at 80 Hz - low-end thump at the cabinet's resonance without "
                             "loosening the preamp"))
    return out


def report_text(rep: Report) -> str:
    lines = [rep.title, f"{rep.character}.", ""]
    lines += [f"{k}: {v}" for k, v in rep.power_rows]
    if rep.feedback is not None:
        lines += [f"{k}: {v}" for k, v in _power_effects(rep.feedback)]
    an = rep.analysis
    if an is not None and an.drive:
        lines += ["", "Where it distorts (gain on 10): " + an.summary]
        lines += [f"  {d.label}{' (' + d.note + ')' if d.note else ''}: {_drive_state(d.db)}" for d in an.drive]
        if rep.tight:
            lines.append(f"Tightness {rep.tight}: " + ", ".join(f"{name} {db:.0f} dB" for name, _hz, db in an.lows) +
                         " (into the distortion, relative to 1 kHz)")
        lines.append(f"Hiss with the gain on 10: about {an.hiss_db:.0f} dB below the playing level "
                     f"({an.hiss_db - 20:.0f} dB with the gain at noon)")
    if rep.pedals:
        lines += [""] + [f"Pedal: {PEDAL_NAMES.get(k, k)} - {why}" for k, why in rep.pedals]
    lines.append("")
    lines += [f"{k}: {v}" for k, v in rep.buy]
    if rep.warnings:
        lines += [""] + [f"WARNING: {w}" for w in rep.warnings]
    if rep.tips:
        lines += [""] + [f"- {t}" for t in rep.tips]
    if rep.powerup:
        lines += ["", "First power-up:"] + [f"{i}. {t}" for i, t in enumerate(rep.powerup, 1)]
    if rep.chart:
        lines += ["", "Voltage chart (DC to ground at idle):"]
        lines += [f"{ref} {tube}: " + ", ".join(f"{pin} {fn} {v}" for pin, fn, v in rows) for ref, tube, rows in rep.chart]
    return "\n".join(lines)


def _bar(fraction: float, colour: str, width: int = 220) -> str:
    w = max(2, min(width - 2, int(width * fraction)))
    return (f"<table cellspacing='0' cellpadding='0' border='0'><tr><td bgcolor='{colour}' width='{w}' height='9'>"
            f"</td><td bgcolor='#2a2f38' width='{width - w}' height='9'></td></tr></table>")


def report_html(rep: Report) -> str:
    """The spec sheet as HTML (for the designer window and the saved spec sheet)."""
    h = [f"<h2 style='margin:0'>{rep.title}</h2>"]
    tubes = f" &nbsp;·&nbsp; {len(rep.tubes)} tubes" if rep.tubes else ""
    h.append(f"<p style='font-size:14px'><b>{rep.pout:g} W</b> &nbsp;·&nbsp; about {rep.spl:.0f} dB SPL at 1 m with "
             f"a 100 dB/W speaker{tubes} &nbsp;·&nbsp; {rep.parts} board parts</p>")
    if rep.warnings:
        h.append("<p style='color:#ff8a6b'>" + "<br>".join(f"⚠ {w}" for w in rep.warnings) + "</p>")
    # sound
    h.append("<h3>Sound and gain</h3>")
    h.append(f"<p><b>{rep.character}.</b></p>")
    single, hum = rep.breakup
    h.append("<table cellspacing='0' cellpadding='3'>")
    labels = (("Breaks up with a passive bass at", "... with an active bass at") if rep.instrument == "bass"
              else ("Breaks up with single coils at", "... with humbuckers at"))
    if rep.breakup_knob:
        labels = (f"Starts to distort with single coils at {rep.breakup_knob}", "... with humbuckers at")
    for label, pos in zip(labels, (single, hum)):
        colour = "#5fb36a" if pos >= 6 else "#e0a23a" if pos >= 3 else "#e0603a"
        h.append(f"<tr><td>{label}</td><td><b>{pos:.1f}</b> / 10</td><td>{_bar(pos / 10, colour)}</td></tr>")
    mv = rep.sensitivity_mv
    sens = f"{mv * 1000:.0f} µV" if mv < 0.1 else f"{mv:.1f} mV"
    h.append(f"<tr><td>Gain to the output {'tubes' if rep.tubes else 'stage'}</td><td colspan='2'>"
             f"{rep.gain_db:.0f} dB with everything on 10 ({sens} in for full power)</td></tr></table>")
    h.append("<table cellspacing='0' cellpadding='3' style='margin-top:6px'><tr style='color:#8b93a1'><td>Stage</td>"
             "<td>Gain</td><td></td></tr>")
    for label, gain, note in rep.stages:
        g = f"x{gain:.1f}" if gain >= 1 else f"x{gain:.2f}" if gain >= 0.9 else f"{20 * math.log10(max(gain, 1e-9)):.0f} dB"
        h.append(f"<tr><td>{label}</td><td><b>{g}</b></td><td style='color:#8b93a1'>{note}</td></tr>")
    h.append("</table>")
    an = rep.analysis
    if an is not None and an.drive:
        h.append("<h3>Where it distorts</h3>")
        h.append(f"<p>{an.summary} <span style='color:#8b93a1'>Gain and volume on 10, "
                 f"{'an active bass' if rep.instrument == 'bass' else 'a humbucker'}; an estimate from each stage's "
                 "operating point.</span></p><table cellspacing='0' cellpadding='3'>")
        mid = {d.label: d.db for d in an.drive_mid}
        for d in an.drive:
            colour = "#5fb36a" if d.db < -3 else "#e0a23a" if d.db < 6 else "#e07a3a" if d.db < 20 else "#e0503a"
            side = {"cutoff": "cuts off on one half-wave", "grid": "grid current on one half-wave",
                    "both": "both half-waves", "": ""}[d.side] if d.db >= 0 else ""
            noon = f"noon: {_drive_state(mid[d.label])}" if d.label in mid else ""
            h.append(f"<tr><td><b>{d.label}</b> <span style='color:#8b93a1'>{d.note}</span></td>"
                     f"<td>{_bar(min(1.0, max(0.0, (d.db + 20) / 60)), colour, 160)}</td>"
                     f"<td><b>{_drive_state(d.db)}</b> <span style='color:#8b93a1'>{side}</span></td>"
                     f"<td style='color:#8b93a1'>{noon}</td></tr>")
        h.append("</table>")
        hiss = an.hiss_db
        hc = "#5fb36a" if hiss < -45 else "#e0a23a" if hiss < -25 else "#e0603a"
        h.append(f"<p>Hiss with the gain on 10: <b style='color:{hc}'>{hiss:.0f} dB</b> below the playing level "
                 f"(about {hiss - 20:.0f} dB with the gain at noon).</p>")
        if rep.tight:
            h.append(f"<h3>Low end into the distortion</h3><p>Tightness <b>{gs.TIGHT_LABELS[rep.tight]}</b>: how far "
                     "the low strings arrive below the mids (1 kHz) at the clipping stages. Less bass into the "
                     "distortion keeps palm mutes tight and chords clear; the DEPTH control and the cabinet put "
                     "the weight back afterwards.</p><table cellspacing='0' cellpadding='3'>")
            for name, hz, db in an.lows:
                h.append(f"<tr><td>{name}, {hz:g} Hz</td><td>{_bar(min(1.0, -db / 30), '#5a8fd8', 160)}</td>"
                         f"<td><b>{db:.0f} dB</b></td></tr>")
            h.append("</table>")
    # power
    h.append("<h3>Power stage</h3><table cellspacing='0' cellpadding='3'>")
    for k, v in rep.power_rows + (_power_effects(rep.feedback) if rep.feedback is not None else []):
        h.append(f"<tr><td style='color:#8b93a1'>{k}</td><td>{v}</td></tr>")
    h.append("</table>")
    if rep.supply:
        h.append("<h3>B+ supply</h3><table cellspacing='0' cellpadding='3'><tr style='color:#8b93a1'><td>Node</td>"
                 "<td>Volts</td><td>Draw</td><td>Feeds</td><td>Filter</td></tr>")
        for node, volts, ma, feeds, filt in rep.supply:
            h.append(f"<tr><td><b>{node}</b></td><td>{volts} V</td><td>{ma:g} mA</td><td>{feeds}</td>"
                     f"<td style='color:#8b93a1'>{filt}</td></tr>")
        h.append("</table>")
    h.append("<h3>What to buy (off the board)</h3><table cellspacing='0' cellpadding='3'>")
    for k, v in rep.buy:
        h.append(f"<tr><td style='color:#8b93a1'>{k}</td><td>{v}</td></tr>")
    h.append("</table>")
    if rep.pedals:
        h.append("<h3>Pedals for this amp</h3><ul>" + "".join(
            f"<li><a href='pedal:{k}' style='color:#6ea8ff'><b>{PEDAL_NAMES.get(k, k)}</b></a> - {why}</li>"
            for k, why in rep.pedals) + "</ul><p style='color:#8b93a1'>Click one to design its board (also in "
            "Amp &gt; Metal pedals).</p>")
    if rep.tips:
        h.append("<h3>Tips</h3><ul>" + "".join(f"<li>{t}</li>" for t in rep.tips) + "</ul>")
    if rep.powerup:
        h.append("<h3>First power-up</h3><ol>" + "".join(f"<li>{t}</li>" for t in rep.powerup) + "</ol>")
    if rep.chart:
        h.append("<h3>Voltage chart</h3><p style='color:#8b93a1'>Expected DC to ground at each tube pin, at idle "
                 "(within about 15 %).</p><table cellspacing='0' cellpadding='3'>")
        for ref, tube, rows in rep.chart:
            cells = " &nbsp; ".join(f"<b>{pin}</b> {fn} {v}" for pin, fn, v in rows)
            h.append(f"<tr><td><b>{ref}</b></td><td>{tube}</td><td>{cells}</td></tr>")
        h.append("</table>")
    return "".join(h)
