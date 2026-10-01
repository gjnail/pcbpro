"""Passive tone-stack calculator: the Fender / Marshall / Vox "TMB" (treble-middle-bass) stack solved as a complex
nodal network, with real pot tapers.

Topology (as in the Fender 5F6-A and the Marshall JTM45)::

    IN --Rs-- S --C1-- T                          T = top of the treble pot
              |        |  treble pot  (wiper = OUT, loaded by RL)
              R1       B = bottom of the treble pot = one end of the bass pot
              |        |  bass pot as a rheostat (B to M)
              A --C2-- B
              A --C3-- M --mid pot (rheostat)-- GND

Rs is the driving stage's output impedance (about 1 k for a cathode follower, ~40 k from a 12AX7 plate).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np


@dataclass
class ToneStack:
    c1: float = 250e-12  # treble cap
    r1: float = 56e3  # slope resistor
    c2: float = 20e-9  # bass cap
    c3: float = 20e-9  # mid cap
    rt: float = 250e3  # treble pot
    rb: float = 1e6  # bass pot
    rm: float = 25e3  # mid pot (or the fixed mid resistor)
    rs: float = 1e3  # source impedance
    rl: float = 1e6  # load (volume pot / next grid)
    mid_fixed: bool = False


PRESETS = {
    "Fender Bassman 5F6-A": ToneStack(250e-12, 56e3, 20e-9, 20e-9, 250e3, 1e6, 25e3, 1e3),
    "Fender Blackface (AB763 Twin)": ToneStack(250e-12, 100e3, 100e-9, 47e-9, 250e3, 250e3, 10e3, 38e3),
    "Fender Deluxe Reverb (6.8k fixed mid)": ToneStack(250e-12, 100e3, 100e-9, 47e-9, 250e3, 250e3, 6.8e3, 38e3,
                                                       mid_fixed=True),
    "Marshall JTM45 / 1959": ToneStack(500e-12, 33e3, 22e-9, 22e-9, 220e3, 1e6, 25e3, 1e3),
    "Marshall JCM800 2203": ToneStack(470e-12, 33e3, 22e-9, 22e-9, 220e3, 1e6, 22e3, 1e3),
    "Vox-voiced (100k slope, 1M bass)": ToneStack(100e-12, 100e3, 47e-9, 22e-9, 1e6, 1e6, 10e3, 38e3),
    "Bass amp (deep, Bassman with 47n bass cap)": ToneStack(250e-12, 56e3, 47e-9, 22e-9, 250e3, 1e6, 25e3, 1e3),
    # high-gain stacks, driven by a cathode follower after the distortion: a little more slope resistance than the
    # JCM800 deepens the mid scoop; the 250p / 47n version scoops lower and keeps the bass tight
    "Modern high gain (47k slope)": ToneStack(470e-12, 47e3, 22e-9, 22e-9, 250e3, 1e6, 25e3, 1e3),
    "Scooped US high gain (250p, 47n mid)": ToneStack(250e-12, 47e3, 22e-9, 47e-9, 250e3, 1e6, 25e3, 1e3),
    # the big American high-gain sound: a large slope resistor and a small (10k) middle pot scoop the mids hard even
    # with the knobs at noon, the 47n bass cap keeps the low end big
    "Deep scoop US high gain (82k slope, 10k mid)": ToneStack(250e-12, 82e3, 47e-9, 22e-9, 250e3, 1e6, 10e3, 1e3),
}


def taper(x: float, kind: str = "A") -> float:
    """Resistance fraction of a pot turned to x (0..1). A = audio (10 % at half travel), B = linear."""
    x = min(1.0, max(0.0, x))
    if kind.upper() == "A":
        return (81.0 ** x - 1.0) / 80.0
    return x


def response(ts: ToneStack, treble: float, bass: float, mid: float, freqs) -> np.ndarray:
    """Complex transfer function OUT / IN at ``freqs`` (Hz) for knob settings 0..10."""
    t = taper(treble / 10.0, "A")
    b = taper(bass / 10.0, "A")
    m = 1.0 if ts.mid_fixed else taper(mid / 10.0, "B")
    eps = 1.0
    # nodes: 0 S, 1 T, 2 W (out), 3 B, 4 A, 5 M ; IN is the 1 V source, GND the reference
    r_tu = max(eps, ts.rt * (1.0 - t))
    r_tl = max(eps, ts.rt * t)
    r_b = max(eps, ts.rb * b)
    r_m = max(eps, ts.rm * m)
    rs = max(eps, ts.rs)
    out = np.empty(len(freqs), dtype=complex)
    for k, f in enumerate(freqs):
        s = 2j * math.pi * f
        Y = np.zeros((6, 6), dtype=complex)
        I = np.zeros(6, dtype=complex)

        def add(a, bnode, y):
            if a is not None:
                Y[a, a] += y
            if bnode is not None:
                Y[bnode, bnode] += y
            if a is not None and bnode is not None:
                Y[a, bnode] -= y
                Y[bnode, a] -= y

        add(0, None, 1 / rs)
        I[0] += 1 / rs  # source through Rs
        add(0, 1, s * ts.c1)
        add(0, 4, 1 / ts.r1)
        add(4, 3, s * ts.c2)
        add(4, 5, s * ts.c3)
        add(1, 2, 1 / r_tu)
        add(2, 3, 1 / r_tl)
        add(3, 5, 1 / r_b)
        add(5, None, 1 / r_m)
        add(2, None, 1 / max(eps, ts.rl))
        v = np.linalg.solve(Y, I)
        out[k] = v[2]
    return out


def response_db(ts: ToneStack, treble: float, bass: float, mid: float, freqs) -> np.ndarray:
    h = response(ts, treble, bass, mid, freqs)
    return 20.0 * np.log10(np.maximum(np.abs(h), 1e-9))


def summary(ts: ToneStack, treble=5.0, bass=5.0, mid=5.0) -> str:
    """Mid-scoop frequency and depth, and the insertion loss at 1 kHz."""
    f = np.logspace(math.log10(20), math.log10(20000), 400)
    db = response_db(ts, treble, bass, mid, f)
    i = int(np.argmin(db[20:-20])) + 20
    at1k = float(np.interp(math.log10(1000), np.log10(f), db))
    return (f"Loss at 1 kHz {at1k:.1f} dB; deepest point {db[i]:.1f} dB at {f[i]:.0f} Hz; "
            f"range {db.max() - db.min():.1f} dB")


def stack_parts(ts: ToneStack, in_net: str, out_net: str, prefix: str = "TS", section: str = "") -> list:
    """The stack as amp-builder parts (values formatted for the BOM)."""
    from ..sim.units import fmt_eng
    from .builder import C, POT, R

    def cap(v):
        return fmt_eng(v, "F").replace(" ", "")

    def res(v):
        return fmt_eng(v, "").replace(" ", "").replace("M", "M").rstrip("Ω")

    def pot(v, taper_kind):
        return f"{taper_kind}{res(v).upper()}"

    t, a, b, m = f"{prefix}_T", f"{prefix}_A", f"{prefix}_B", f"{prefix}_M"
    parts = [C(f"{cap(ts.c1)} 500V", in_net, t, "ceramic_hv", section), R(res(ts.r1), in_net, a, "res", section),
             C(f"{cap(ts.c2)} 400V", a, b, "film_hv", section), C(f"{cap(ts.c3)} 400V", a, m, "film_hv", section),
             POT(pot(ts.rt, "A"), b, out_net, t, "TREBLE", section), POT(pot(ts.rb, "A"), b, m, m, "BASS", section)]
    if ts.mid_fixed:
        parts.append(R(res(ts.rm), m, "GND", "res_small", section))
    else:
        parts.append(POT(pot(ts.rm, "B"), m, "GND", "GND", "MIDDLE", section))
    return parts


def with_values(ts: ToneStack, **kw) -> ToneStack:
    return replace(ts, **kw)
