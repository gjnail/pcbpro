"""Gain-staging analysis for the Amp Designer: where the preamp distorts, how tight its low end is going into the
distortion, how much hiss the gain brings up, and what the presence / depth controls do to the power amp.

The designer records the signal path as it builds the preamp: triode stages (with their operating points, filled in
once the B+ supply has been solved) and the passive networks between them (coupling caps, treble-peaking
attenuators, gain and volume controls, the tone stack). The analysis then walks that path from the input jack:

* small-signal frequency response, with real cathode-bypass shelves, coupling-cap high-passes, the 470k / 470p
  "bright" attenuators and each stage's Miller input capacitance against the impedance that feeds its grid;
* a peak-level cascade that follows the positive and negative half-waves separately, so a cold clipper (which cuts
  off on one half-wave) and a hot stage (which runs into grid current on the other) are told apart, and each stage's
  output is limited where the tube cuts off or its grid conducts;
* thermal noise of the input stage (grid stopper, pickup and the triode's equivalent noise resistance) carried
  through the same response, compared with each stage's clipping point.

It is a designer's estimate (about +/-3 dB), not a circuit simulation.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

KT = 1.380649e-23 * 300.0  # Boltzmann's constant x 300 K
# grid-to-cathode and grid-to-plate capacitance (pF) of common preamp triodes
TRIODE_CAPS = {"12AX7": (1.6, 1.7), "12AT7": (2.2, 1.5), "12AU7": (1.6, 1.5), "12AY7": (1.3, 1.3),
               "5751": (1.4, 1.4), "ECC88": (3.3, 1.4), "6SN7": (2.4, 3.9), "6SL7": (3.0, 2.8)}
# Koren triode model constants (mu, ex, kg1, kp, kvb)
KOREN = {"12AX7": (100.0, 1.4, 1060.0, 600.0, 300.0), "12AT7": (60.0, 1.35, 460.0, 300.0, 300.0),
         "12AU7": (21.5, 1.3, 1180.0, 84.0, 300.0), "5751": (70.0, 1.4, 1060.0, 600.0, 300.0)}

FREQS = np.logspace(math.log10(20.0), math.log10(20000.0), 300)
BAND = (60.0, 6000.0)  # what a guitar cabinet reproduces: the hiss that matters
TIGHT_LEVELS = ("fat", "normal", "tight", "djent")
TIGHT_LABELS = {"fat": "Fat (full low end)", "normal": "Normal", "tight": "Tight (palm-mute focus)",
                "djent": "Djent (extended-range, very tight)"}
STRINGS = (("low E (6-string)", 82.4), ("low B (7-string)", 61.7), ("low F# (8-string)", 46.2))


def koren_ia(tube: str, va: float, vg: float) -> float:
    """Plate current (A) of a triode from Norman Koren's model."""
    mu, ex, kg1, kp, kvb = KOREN.get(tube, KOREN["12AX7"])
    e1 = va / kp * math.log1p(math.exp(min(60.0, kp * (1.0 / mu + vg / math.sqrt(kvb + va * va)))))
    return 2.0 * e1 ** ex / kg1 if e1 > 0 else 0.0


def follower_bias(tube: str, vb: float, rk: float) -> float:
    """Idle current of a cathode-biased stage with its grid at 0 V and the plate straight on the B+ node (a cathode
    follower): solves Ia = f(Va = Vb - Vk, Vg = -Ia Rk)."""
    lo, hi = 0.0, 20e-3
    for _ in range(60):
        mid = (lo + hi) / 2
        if koren_ia(tube, vb - mid * rk, -mid * rk) > mid:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def tight_pick(values, level: str):
    """Pick the value for a tightness level from a (fat, normal, tight, djent) tuple."""
    return values[TIGHT_LEVELS.index(level if level in TIGHT_LEVELS else "normal")]


# --------------------------------------------------------------------------- the signal path

@dataclass
class Stage:
    """A common-cathode triode gain stage."""
    label: str
    tube: str
    mu: float
    ra: float
    rk: float
    ck: float
    load: float  # AC load in parallel with the plate resistor (the next grid leak or pot)
    zs: object = 0.0  # impedance feeding the grid (ohms, or fn(f) -> complex): sets the Miller roll-off
    note: str = ""
    ia: float = 0.0  # operating point, filled in when the supply is solved
    rp: float = 0.0
    vb: float = 0.0
    vp: float = 0.0
    vk: float = 0.0

    @property
    def raeff(self) -> float:
        return self.ra * self.load / (self.ra + self.load) if self.load else self.ra

    def zk(self, f) -> np.ndarray:
        f = np.asarray(f, dtype=float)
        if self.ck <= 0:
            return np.full(f.shape, complex(self.rk))
        return self.rk / (1.0 + 2j * np.pi * f * self.rk * self.ck)

    def gain(self, f, miller: bool = True) -> np.ndarray:
        f = np.asarray(f, dtype=float)
        a = self.mu * self.raeff / (self.raeff + self.rp + (self.mu + 1.0) * self.zk(f))
        if miller:
            zs = self.zs(f) if callable(self.zs) else np.full(f.shape, complex(self.zs))
            cgk, cga = TRIODE_CAPS.get(self.tube, (1.6, 1.7))
            cin = (cgk + cga * (1.0 + np.abs(a))) * 1e-12
            a = a / (1.0 + zs * 2j * np.pi * f * cin)
        return a

    def thresholds(self, f: float = 1000.0) -> tuple[float, float]:
        """(cutoff, grid conduction): the input peak (V) that drives the stage to each limit at ``f``."""
        z = float(abs(self.zk(np.array([f]))[0]))  # the cathode's AC impedance: 0 when fully bypassed
        frac = z / self.rk if self.rk else 0.0
        va = self.vp + self.ia * self.raeff  # where the plate goes when the tube cuts off
        cut = max(0.05, va / self.mu - self.vk * (1.0 - frac))
        k = (self.raeff + self.rp + (self.mu + 1.0) * z) / (self.raeff + self.rp + z)
        grid = max(0.05, (self.vk - 0.2) * k)  # grid current starts a little below 0 V grid-to-cathode
        return cut, grid

    def swings(self, f: float = 1000.0) -> tuple[float, float]:
        """(up, down): the largest output peaks - the plate rising to cutoff, and falling until the grid conducts."""
        _cut, grid = self.thresholds(f)
        a = float(abs(self.gain(np.array([f]), miller=False)[0]))
        up = self.ia * self.raeff
        down = min(a * grid, max(1.0, self.vp - 0.3 * self.vb))
        return up, down


@dataclass
class Net:
    """A passive network on the signal path: H(f), or a pot whose setting scales the signal."""
    label: str
    h: object  # fn(freqs) -> complex array
    pot: str = ""  # "A" / "B" for a gain or volume control in the path (its setting is applied separately)


@dataclass
class Clip:
    """A limiter that is not a triode stage (the power tubes): clips symmetrically at ``level`` peak volts."""
    label: str
    level: float


@dataclass
class Drive:
    label: str
    db: float  # input peak relative to the clipping point: > 0 dB means it clips (by that much)
    side: str  # "cutoff" | "grid" | "both" | ""
    level: float  # input peak volts
    note: str = ""  # the stage's role (input, cold clipper, ...)


@dataclass
class Analysis:
    drive: list = field(default_factory=list)  # [Drive] with the gain control on 10
    drive_mid: list = field(default_factory=list)  # [Drive] with the gain control at noon
    freqs: np.ndarray | None = None
    pre_db: np.ndarray | None = None  # response into the last clipping stage, 0 dB at 1 kHz
    lows: list = field(default_factory=list)  # (string, Hz, dB re 1 kHz)
    corner: float = 0.0  # -3 dB low-cut frequency of that response
    hiss_margin: float = 0.0  # dB between the hiss and the clipping point of the stage it comes closest to
    hiss_stage: str = ""
    hiss_db: float = 0.0  # hiss relative to the distorted playing level at the end of the preamp
    first: str = ""  # the first stage to clip
    summary: str = ""


def _pot_frac(x: float, kind: str) -> float:
    x = min(1.0, max(0.0, x))
    return (81.0 ** x - 1.0) / 80.0 if kind.upper() == "A" else x


def _resp(path: list, f: np.ndarray, upto: int, settings: dict | None = None) -> np.ndarray:
    """Complex response from the input jack to the input of path[upto]."""
    h = np.ones(f.shape, dtype=complex)
    for el in path[:upto]:
        if isinstance(el, Stage):
            h = h * el.gain(f)
        elif isinstance(el, Net):
            h = h * el.h(f)
            if el.pot:
                h = h * _pot_frac((settings or {}).get(el.label, 1.0), el.pot)
    return h


def _cascade(path: list, level: float, settings: dict) -> list[Drive]:
    pos = neg = level
    out = []
    f1k = np.array([1000.0])
    for el in path:
        if isinstance(el, Net):
            g = float(abs(el.h(f1k)[0]))
            if el.pot:
                g *= _pot_frac(settings.get(el.label, 1.0), el.pot)
            pos, neg = pos * g, neg * g
        elif isinstance(el, Clip):
            pk = max(pos, neg)
            out.append(Drive(el.label, 20 * math.log10(max(pk, 1e-9) / el.level), "both", pk, "power amp"))
            pos, neg = min(pos, el.level), min(neg, el.level)
        elif isinstance(el, Stage):
            cut, grid = el.thresholds()
            r_cut, r_grid = neg / cut, pos / grid
            side = "cutoff" if r_cut >= r_grid else "grid"
            if r_cut >= 1 and r_grid >= 1:
                side = "both"
            out.append(Drive(el.label, 20 * math.log10(max(r_cut, r_grid, 1e-9)), side, max(pos, neg), el.note))
            a = float(abs(el.gain(f1k)[0]))
            up, down = el.swings()
            # an inverting stage: the negative input half-wave becomes the positive output half-wave
            pos, neg = min(a * neg, up), min(a * pos, down)
    return out


def analyse(path: list, level: float, gain_label: str = "") -> Analysis:
    """Gain staging of a preamp ``path`` driven by an instrument peaking at ``level`` volts."""
    an = Analysis()
    if not any(isinstance(el, Stage) for el in path):
        return an
    f = FREQS
    an.freqs = f
    an.drive = _cascade(path, level, {})
    if gain_label:
        an.drive_mid = _cascade(path, level, {gain_label: 0.5})
    stages = [i for i, el in enumerate(path) if isinstance(el, Stage)]
    clipping = [i for i, el in enumerate(path) if isinstance(el, Stage) and
                next((d.db for d in an.drive if d.label == el.label), -99) > 0]
    last = clipping[-1] if clipping else stages[-1]
    h = _resp(path, f, last)
    db = 20 * np.log10(np.maximum(np.abs(h), 1e-12))
    ref = float(np.interp(math.log10(1000.0), np.log10(f), db))
    an.pre_db = db - ref
    an.lows = [(name, hz, float(np.interp(math.log10(hz), np.log10(f), an.pre_db))) for name, hz in STRINGS]
    below = np.where(an.pre_db[: int(np.searchsorted(f, 1000.0))] < -3.0)[0]
    an.corner = float(f[below[-1]]) if len(below) else float(f[0])
    first = next((d for d in an.drive if d.db > 0), None)
    an.first = first.label if first else ""
    # hiss: the input stage's thermal noise (68k grid stopper + about 10k of pickup + the triode's noise resistance)
    s0 = path[stages[0]]
    gm = s0.mu / max(s0.rp, 1.0)
    en2 = 4 * KT * (68e3 + 10e3 + 2.5 / gm)
    band = (f >= BAND[0]) & (f <= BAND[1])
    df = np.gradient(f)
    worst = (99.0, "")
    for i in stages:
        el = path[i]
        hi = _resp(path, f, i)
        noise = math.sqrt(float(np.sum((np.abs(hi[band]) ** 2) * en2 * df[band])))
        cut, grid = el.thresholds()
        margin = 20 * math.log10(min(cut, grid) / max(noise * math.sqrt(2.0), 1e-12))
        if margin < worst[0]:
            worst = (margin, el.label)
    an.hiss_margin, an.hiss_stage = worst
    # hiss relative to the (distorted) playing level at the end of the preamp
    h_end = _resp(path, f, len(path))
    noise_end = math.sqrt(float(np.sum((np.abs(h_end[band]) ** 2) * en2 * df[band])))
    play = _end_level(path, level)
    an.hiss_db = 20 * math.log10(max(noise_end * math.sqrt(2.0), 1e-12) / max(play, 1e-9))
    an.summary = _summary(an)
    return an


def breakup_knob(path: list, level: float, label: str) -> float:
    """Setting (0-10) of the control ``label`` at which the first preamp stage starts to clip, for an instrument
    peaking at ``level`` volts: 0 when it clips with the control at zero, 10 when it never does."""
    def worst(x):
        return max((d.db for d in _cascade(path, level, {label: x}) if d.side != "both" or d.note != "power amp"),
                   default=-99.0)
    if worst(0.0) >= 0.0:
        return 0.0
    if worst(1.0) < 0.0:
        return 10.0
    lo, hi = 0.0, 1.0
    for _ in range(24):
        mid = (lo + hi) / 2
        if worst(mid) >= 0.0:
            hi = mid
        else:
            lo = mid
    return 10.0 * hi


def _end_level(path: list, level: float) -> float:
    pos = neg = level
    f1k = np.array([1000.0])
    for el in path:
        if isinstance(el, Net):
            g = float(abs(el.h(f1k)[0]))
            pos, neg = pos * g, neg * g
        elif isinstance(el, Clip):
            pos, neg = min(pos, el.level), min(neg, el.level)
        elif isinstance(el, Stage):
            a = float(abs(el.gain(f1k)[0]))
            up, down = el.swings()
            pos, neg = min(a * neg, up), min(a * pos, down)
    return max(pos, neg)


def _summary(an: Analysis) -> str:
    hard = [d for d in an.drive if d.db > 6]
    if not any(d.db > 0 for d in an.drive):
        return "Clean all the way through, even with everything on 10: a pedal platform."
    if [d.label for d in an.drive if d.db > 0] == ["Power tubes"]:
        return ("The preamp stays clean; with the volume on 10 the power tubes do the distorting - classic "
                "cranked-amp breakup.")
    worst = max(an.drive, key=lambda d: d.db)
    if len(hard) >= 3:
        text = (f"The distortion is spread over {len(hard)} stages ({', '.join(d.label for d in hard)}): smooth, "
                "saturated and compressed")
    elif len(hard) == 2:
        a, b = ("the power tubes" if d.label == "Power tubes" else d.label for d in hard)
        text = f"Two stages do the distorting ({a} and {b}): a crunchy, open distortion"
    else:
        text = f"{'The power tubes do' if worst.label == 'Power tubes' else worst.label + ' does'} most of the "                "distorting"
    if worst.db > 40:
        text += f"; {worst.label} is driven {worst.db:.0f} dB past clipping - turn the gain down a little if it fizzes"
    return text + "."


# --------------------------------------------------------------------------- power amp: presence and depth

@dataclass
class Feedback:
    """The global negative-feedback network: R from the speaker tap into a 4k7 shunt at the phase inverter's tail,
    a presence pot + cap that shunts it at high frequencies, and an optional depth pot + cap in series with R."""
    rf: float
    fb: float  # the closed-loop gain relative to open loop at mid frequencies (0.4 = about 8 dB of feedback)
    rsh: float = 4.7e3
    pres_c: float = 0.0
    pres_r: float = 5e3
    depth_c: float = 0.0
    depth_r: float = 250e3


def power_response(nf: Feedback, f, presence: float = 0.0, depth: float = 0.0) -> np.ndarray:
    """Closed-loop power-amp response (dB, relative to 1 kHz with presence and depth off) for knob settings 0..10."""
    f = np.asarray(f, dtype=float)

    def beta(fr, pres, dep):
        ww = 2j * np.pi * fr
        zsh = np.full(np.shape(fr), complex(nf.rsh))
        if nf.pres_c:
            rp = (1.0 - pres / 10.0) * nf.pres_r + 1.0
            zp = rp + 1.0 / (ww * nf.pres_c)
            zsh = nf.rsh * zp / (nf.rsh + zp)
        zser = nf.rf
        if nf.depth_c:
            rd = dep / 10.0 * nf.depth_r + 1.0
            zc = 1.0 / (ww * nf.depth_c)
            zser = nf.rf + rd * zc / (rd + zc)
        return zsh / (zsh + zser)

    b0 = beta(np.array([1000.0]), 0.0, 0.0)[0]
    loop = (1.0 / nf.fb - 1.0) / abs(b0)  # open-loop gain that gives the feedback factor at 1 kHz
    ref = abs(1.0 / (1.0 + loop * b0))
    h = 1.0 / (1.0 + loop * beta(f, presence, depth))
    return 20 * np.log10(np.abs(h) / ref)
