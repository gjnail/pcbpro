"""Off-board hardware of an amplifier board, so the board can be simulated and played as a whole amp.

Amp boards built by PCBPro wire their chassis parts to labelled pads ("AmpWirePads_..." footprints):

* ``HV1/CT/HV2``, ``AC1/CT/AC2``, ``BIAS/0V``: power transformer windings, with their AC voltage in
  ``project.amp["nets"]``. Each rectified supply becomes a DC source behind the rectifier's source resistance at the
  rectifier output, so B+ sags under load like the real supply but there is no mains hum. The rectifier parts
  themselves are then left out.
* ``P1/B+/P2`` (push-pull) or ``P/B+`` (single-ended): the output transformer primary. It is modelled as an ideal
  transformer plus magnetising inductance, leakage inductance, winding and core losses. Its primary impedance comes
  from ``project.amp["ot"]`` or the power tubes and topology.
* ``SPK/COM``: the transformer secondary and speaker (the negative feedback is taken from SPK). Without these pads the
  secondary drives an internal node named ``SPEAKER``.
* ``CHK1/CHK2``: a filter choke.

The speaker is a real speaker's impedance: voice coil resistance and inductance plus the bass resonance. That matters
because a pentode output stage without much feedback follows the speaker's impedance curve.
"""
from __future__ import annotations

import contextvars
import math
import re
from dataclasses import dataclass, field

from .devices import Capacitor, Inductor, Resistor, Transformer

SPEAKER_NET = "SPEAKER"
WIRE_PREFIX = "AmpWirePads_"

# output transformer primary impedance (ohms, plate to plate for push-pull) and rated power per pair / per tube
OT_PP = {"EL84": 8000, "6V6GT": 8000, "6AQ5": 8000, "6L6GC": 4200, "5881": 4200, "KT66": 4200, "EL34": 3400,
         "KT88": 4000, "6550": 4000}
OT_SE = {"EL84": 5200, "6V6GT": 5000, "6AQ5": 5000, "6L6GC": 3000, "5881": 3000, "KT66": 2500, "EL34": 3000,
         "KT88": 2500, "6550": 2500}
WATTS_PP = {"EL84": 17, "6V6GT": 14, "6AQ5": 12, "6L6GC": 45, "5881": 40, "KT66": 40, "EL34": 50, "KT88": 70,
            "6550": 70}
WATTS_SE = {"EL84": 5, "6V6GT": 5, "6AQ5": 4, "6L6GC": 10, "5881": 9, "KT66": 9, "EL34": 11, "KT88": 15, "6550": 15}
RECT_R = {"5Y3GT": 350.0, "5AR4": 120.0, "5U4GB": 180.0, "EZ81": 200.0, "6X4": 300.0}  # tube rectifier source R
RECT_DROP = {"5Y3GT": 50.0, "5AR4": 17.0, "5U4GB": 45.0, "EZ81": 25.0, "6X4": 25.0}
CHOKE = (10.0, 100.0)  # henries, ohms

# forced OT polarity while probing which way round gives negative feedback (see nfb_polarity)
_FORCE_POLARITY: contextvars.ContextVar = contextvars.ContextVar("ot_polarity", default=None)
_POLARITY_CACHE: dict = {}


@dataclass
class AmpHardware:
    replaced: dict = field(default_factory=dict)  # uid -> note (rectifiers replaced by the supply model)
    supplies: list = field(default_factory=list)  # source dicts for auto_sources
    ot: dict | None = None
    speaker: dict | None = None
    chokes: list = field(default_factory=list)  # (net a, net b, henries, ohms)
    links: list = field(default_factory=list)  # (net a, net b, ohms): low-resistance windings
    notes: list = field(default_factory=list)


def _roles(project) -> dict[str, list[str]]:
    """Wire-pad name -> the nets wired to it (H1/H2 and friends can appear several times)."""
    out: dict[str, list[str]] = {}
    for c in project.components:
        if c.footprint.name.startswith(WIRE_PREFIX):
            for pad, net in c.pad_nets.items():
                if net:
                    out.setdefault(pad.upper(), []).append(net)
    return out


def is_amp(project) -> bool:
    return bool(getattr(project, "amp", None)) or any(c.footprint.name.startswith(WIRE_PREFIX) or
                                                      c.footprint.model.get("type") == "tube"
                                                      for c in project.components)


def _net_info(project, net: str) -> dict:
    return ((getattr(project, "amp", None) or {}).get("nets") or {}).get(net) or {}


def _ground(net: str | None) -> bool:
    from .models import is_ground_net
    return net is not None and is_ground_net(net)


def _tubes(project, res: dict) -> list[tuple]:
    """(component, Tube) for every tube socket."""
    from ..amp.tubes import find_tube
    out = []
    for c in project.components:
        r = res.get(c.uid)
        if r is not None and r.kind in ("tube", "rectifier"):
            t = find_tube(c.value) or find_tube(c.mpn)
            if t is not None:
                out.append((c, t))
    return out


def _power_tubes_on(project, res, net: str) -> list:
    return [t for c, t in _tubes(project, res) if t.kind == "power" and
            any(c.pad_nets.get(p) == net for p in res[c.uid].pins.get("A", []))]


# --------------------------------------------------------------------------- analysis

def analyse(project, res: dict) -> AmpHardware | None:
    """What lives off the board, from the wire pads, the parts and ``project.amp``. ``res``: uid -> Resolution."""
    if not is_amp(project):
        return None
    hw = AmpHardware()
    roles = _roles(project)
    _supplies(project, res, roles, hw)
    _output_transformer(project, res, roles, hw)
    if hw.speaker is None:  # solid-state amp: a speaker jack on the board
        for c in project.components:
            fpn = c.footprint.name
            if "speakon" in fpn.lower() or (c.value or "").upper().startswith("SPEAKER"):
                nets = [n for n in c.pad_nets.values() if n and not _ground(n)]
                gnd = [n for n in c.pad_nets.values() if n and _ground(n)]
                if nets:
                    hw.speaker = {"net": nets[0], "com": gnd[0] if gnd else None, "z": _speaker_ohms(project)}
                    break
    for a, b in zip(roles.get("CHK1", []), roles.get("CHK2", [])):
        ch = (getattr(project, "amp", None) or {}).get("choke") or {}
        hw.chokes.append((a, b, float(ch.get("henries", CHOKE[0])), float(ch.get("ohms", CHOKE[1]))))
    for a, b in zip(roles.get("5V1", []), roles.get("5V2", [])):  # rectifier filament winding
        hw.links.append((a, b, 0.1))
    return hw


def _speaker_ohms(project) -> float:
    amp = getattr(project, "amp", None) or {}
    v = (amp.get("ot") or {}).get("secondary_ohms") or (amp.get("spec") or {}).get("speaker") or 8
    try:
        return float(v)
    except (TypeError, ValueError):
        return 8.0


def _supplies(project, res, roles, hw: AmpHardware) -> None:
    """Rectified supplies -> DC sources (with source resistance) at the rectifier outputs."""
    # net -> (volts RMS to ground, whole-winding volts RMS, winding has a grounded centre tap)
    ac_nets: dict[str, tuple[float, float, bool]] = {}
    for keys in (("HV1", "HV2", "HV"), ("AC1", "AC2", "AC"), ("BIAS",), ("H1", "H2")):
        ct = keys == ("BIAS",) or (keys[0] != "H1" and any(_ground(n) for n in roles.get("CT", [])))
        nets = [(net, _net_info(project, net).get("ac")) for k in keys for net in roles.get(k, [])]
        whole = sum(float(v) for _, v in nets if v)
        for net, vac in nets:
            if vac:
                ac_nets[net] = (float(vac), whole, ct)
    if not ac_nets:
        return
    by_net: dict[str, list] = {}
    for c in project.components:
        r = res.get(c.uid)
        if r is None:
            continue
        for term, pads in r.pins.items():
            for p in pads:
                if c.pad_nets.get(p):
                    by_net.setdefault(c.pad_nets[p], []).append((c, r, term))
    outputs: dict[str, dict] = {}

    def out(net, sign, peak, kind, uids):
        o = outputs.setdefault(net, {"sign": sign, "peak": 0.0, "kind": kind, "uids": set(), "from": set()})
        o["peak"] = max(o["peak"], peak)
        o["uids"] |= uids
        return o

    def follow(net, forward, uids):
        """Through a chain of series diodes: the last net, and the diodes on the way."""
        seen = set()
        while True:
            nxt = None
            items = [i for i in by_net.get(net, []) if i[0].uid not in uids]
            diodes = [i for i in items if i[1].kind == "diode" and i[2] == ("A" if forward else "K")]
            others = [i for i in by_net.get(net, []) if i[1].kind not in ("diode", "none")]
            if len(diodes) == 1 and not others and net not in seen:
                c, r, _ = diodes[0]
                pads = r.pins.get("K" if forward else "A", [])
                nxt = c.pad_nets.get(pads[0]) if pads else None
            if nxt is None:
                return net
            seen.add(net)
            uids.add(diodes[0][0].uid)
            net = nxt

    for net, (vac, whole, ct) in ac_nets.items():
        peak = math.sqrt(2.0) * (vac if ct else whole)  # full-wave CT: per side; bridge: the whole winding
        for c, r, term in by_net.get(net, []):
            if r.kind == "rectifier" and term in ("A1", "A2"):
                k = r.pins.get("K") or r.pins.get("HK") or []
                knet = c.pad_nets.get(k[0]) if k else None
                if knet:
                    o = out(knet, 1, peak, r.params.get("tube", "tube"), {c.uid})
                    o["from"].add(net)
            elif r.kind == "diode" and term in ("A", "K"):
                fwd = term == "A"
                pads = r.pins.get("K" if fwd else "A", [])
                first = c.pad_nets.get(pads[0]) if pads else None
                if not first or first in ac_nets:
                    continue
                uids = {c.uid}
                end = follow(first, fwd, uids)
                if _ground(end):  # the return half of a bridge
                    continue
                o = out(end, 1 if fwd else -1, peak, "silicon", uids)
                o["from"].add(net)
            elif r.kind == "bridge" and term in ("AC1", "AC2"):
                for t_, sg in (("+", 1), ("-", -1)):
                    n = c.pad_nets.get(r.pins[t_][0])
                    if n and not _ground(n):
                        o = out(n, sg, peak, "bridge", {c.uid})
                        o["from"].add(net)
    power_idle = 0.0
    for c, t in _tubes(project, res):
        if t.kind == "power":
            power_idle += 0.65 * t.pa_max * 1.1  # W at idle (plate + screen), ~65 % of the rating
        elif t.kind in ("triode2", "pentode"):
            power_idle += 0.3
    for net, o in outputs.items():
        for u in o["uids"]:
            hw.replaced[u] = f"replaced by the {net} supply model"
        kind = o["kind"]
        tube = kind not in ("silicon", "bridge")
        peak = o["peak"]
        drop = RECT_DROP.get(kind, 25.0) if tube else (1.4 if kind == "bridge" else 0.8 * len(o["uids"]))
        hv = peak > 100.0
        r_s = RECT_R.get(kind, 200.0) if tube else (60.0 if hv else 0.3)
        if o["sign"] < 0 and kind == "silicon" and not hv:  # a bias supply: small current, high impedance
            r_s = 470.0
        design = _net_info(project, net).get("v")
        if design is not None and abs(float(design)) > 1.0:
            v_target = abs(float(design))
            i_est = power_idle / v_target if hv and o["sign"] > 0 else 0.0
            v0 = min(v_target + i_est * r_s, peak - (0 if tube else 0.5))
            v0 = max(v0, v_target)
        else:
            v0 = peak - drop
        v0 *= o["sign"]
        what = {"silicon": "silicon diodes", "bridge": "bridge rectifier"}.get(kind, f"{kind} rectifier")
        src = ", ".join(sorted(o["from"]))
        hw.supplies.append({"net": net, "kind": "dc", "v": round(v0, 1), "r": r_s, "enabled": True, "auto": True,
                            "label": f"rectified {src} ({what}, {r_s:g} Ω source)"})


def _output_transformer(project, res, roles, hw: AmpHardware) -> None:
    amp = getattr(project, "amp", None) or {}
    cfg = amp.get("ot") or {}
    p1, p2, bp = roles.get("P1", []), roles.get("P2", []), roles.get("B+", [])
    se = roles.get("P", [])
    if p1 and p2 and bp:
        kind, plates = "pp", (p1[0], p2[0])
    elif se and bp:
        kind, plates = "se", (se[0],)
    else:
        return
    tubes = [_power_tubes_on(project, res, n) for n in plates]
    name = next((ts[0].name for ts in tubes if ts), "EL34")
    per_side = max(1, max(len(ts) for ts in tubes))
    zp = cfg.get("primary_ohms") or (OT_PP if kind == "pp" else OT_SE).get(name, 4000) / per_side
    zs = _speaker_ohms(project)
    spk = roles.get("SPK", [None])[0]
    com = (roles.get("COM") or [None])[0]
    hw.ot = {"kind": kind, "plates": plates, "bplus": bp[0], "zp": float(zp), "zs": zs, "tube": name,
             "per_side": per_side, "spk": spk, "com": com, "polarity": cfg.get("nfb_polarity"),
             "watts": cfg.get("power_w") or cfg.get("watts") or _rated_watts(amp, kind, name, per_side)}
    hw.speaker = {"net": spk, "com": com, "z": zs}


def _rated_watts(amp: dict, kind: str, tube: str, per_side: int) -> float:
    m = re.search(r"(\d+(?:\.\d+)?)\s*W\b", str(amp.get("design", "")), re.I)
    if m:
        return float(m.group(1))
    return float((WATTS_PP if kind == "pp" else WATTS_SE).get(tube, 20) * per_side)


def rated_watts(project) -> float | None:
    """Rated output power, for scaling the speaker output to a sensible audio level."""
    if not is_amp(project):
        return None
    amp = getattr(project, "amp", None) or {}
    if (amp.get("ot") or {}).get("power_w"):
        return float(amp["ot"]["power_w"])
    m = re.search(r"(\d+(?:\.\d+)?)\s*W\b", str(amp.get("design", "")), re.I)
    if m:
        return float(m.group(1))
    from .models import resolve
    res = {c.uid: resolve(c) for c in project.components}
    hw = analyse(project, res)
    if hw and hw.ot:
        return float(hw.ot["watts"])
    return 20.0 if hw and hw.speaker else None


def output_net(project) -> str | None:
    """The net to listen to on an amp board: the speaker (OT secondary or speaker jack), else None."""
    if not is_amp(project):
        return None
    roles = _roles(project)
    if roles.get("SPK"):
        return roles["SPK"][0]
    if (roles.get("P1") and roles.get("P2")) or roles.get("P"):
        return SPEAKER_NET
    for c in project.components:
        if "speakon" in c.footprint.name.lower() or (c.value or "").upper().startswith("SPEAKER"):
            nets = [n for n in c.pad_nets.values() if n and not _ground(n)]
            if nets:
                return nets[0]
    return None


def full_scale_volts(project) -> float:
    """The speaker voltage that maps to full scale when listening to an amp: twice the peak voltage at rated power
    into the nominal impedance (the real speaker's impedance peaks let the voltage swing higher than that)."""
    w = rated_watts(project) or 20.0
    return 2.0 * math.sqrt(2.0 * w * _speaker_ohms(project))


# --------------------------------------------------------------------------- circuit

def add_hardware(ck, hw: AmpHardware, node_of) -> None:
    """Add the transformer, speaker, chokes and windings to the circuit. ``node_of(net)`` -> node index."""
    for a, b, ohms in hw.links:
        ck.add(Resistor(node_of(a), node_of(b), ohms, name="winding"))
    for a, b, hen, ohms in hw.chokes:
        mid = ck.internal("choke")
        ck.add(Resistor(node_of(a), mid, ohms, name="choke"))
        ck.add(Inductor(mid, node_of(b), hen, name="choke"))
        hw.notes.append(f"Choke between {a} and {b}: {hen:g} H, {ohms:g} Ω")
    spk_node, com = None, 0
    sp = hw.speaker
    if sp is not None:
        spk_node = node_of(sp["net"]) if sp.get("net") else ck.internal(SPEAKER_NET)
        com = node_of(sp["com"]) if sp.get("com") else 0
        ck.net_node.setdefault(SPEAKER_NET, spk_node)
        ck.node_nets.setdefault(spk_node, set()).add(SPEAKER_NET)
        _speaker(ck, spk_node, com, sp["z"])
        hw.notes.append(f"Speaker: {sp['z']:g} Ω nominal, with its bass resonance and voice-coil inductance")
    ot = hw.ot
    if ot is not None:
        pol = _FORCE_POLARITY.get() or (ot.get("polarity") if ot.get("polarity") in (1, -1) else 1)
        _transformer(ck, ot, node_of, spk_node, com, int(pol))
        hw.notes.append(f"Output transformer: {ot['zp']:.0f} Ω {'plate to plate' if ot['kind'] == 'pp' else ''}"
                        f" : {ot['zs']:g} Ω ({ot['tube']}, {'push-pull' if ot['kind'] == 'pp' else 'single-ended'})")


def _speaker(ck, a: int, com: int, z: float) -> None:
    """Voice coil resistance Re and lossy inductance (Le parallel R2: the impedance rises with frequency, then levels
    off as eddy currents take over) in series with the bass resonance (parallel R, L, C) at about 85 Hz."""
    re_, le, r2 = 0.75 * z, 0.08e-3 * z, 4.0 * z
    res, fs, q = 4.5 * z, 85.0, 3.0
    w0 = 2 * math.pi * fs
    n1, n2 = ck.internal("speaker coil"), ck.internal("speaker motion")
    ck.add(Resistor(a, n1, re_, name="speaker"))
    ck.add(Inductor(n1, n2, le, name="speaker"))
    ck.add(Resistor(n1, n2, r2, name="speaker"))
    ck.add(Resistor(n2, com, res, name="speaker"))
    ck.add(Inductor(n2, com, res / (w0 * q), name="speaker"))
    ck.add(Capacitor(n2, com, q / (w0 * res), name="speaker"))


def _transformer(ck, ot: dict, node_of, spk_node: int, com: int, polarity: int) -> None:
    zp, zs = ot["zp"], ot["zs"]
    n = math.sqrt(zp / zs)  # primary turns per secondary turn
    se = ot["kind"] == "se"
    lp = zp / (2 * math.pi * (60.0 if se else 20.0))  # magnetising inductance of the whole primary
    lleak = zp / (2 * math.pi * 40e3)  # leakage, referred to the whole primary
    rp, rs = 0.03 * zp, 0.04 * zs  # winding resistance
    t = ck.internal("OT core")
    bp = node_of(ot["bplus"])
    wind = []
    if se:
        a = ck.internal("OT primary")
        ck.add(Resistor(node_of(ot["plates"][0]), a, rp, name="OT primary"))
        wind.append((a, bp, n))
    else:
        a1, a2 = ck.internal("OT primary 1"), ck.internal("OT primary 2")
        ck.add(Resistor(node_of(ot["plates"][0]), a1, rp / 2, name="OT primary"))
        ck.add(Resistor(node_of(ot["plates"][1]), a2, rp / 2, name="OT primary"))
        wind += [(a1, bp, n / 2), (bp, a2, n / 2)]
    # winding capacitance across the primary, resonating with the leakage inductance at ~30 kHz as in a real
    # transformer: it takes up the leakage energy when a tube cuts off instead of an unbounded flyback spike. Its
    # losses (the series resistor, about the resonance's characteristic impedance) damp the ringing to Q ~ 1: the
    # ringing is above hearing anyway, and undamped it would make every clipped edge ring at the sample rate
    w_r = 2 * math.pi * 30e3
    cw = 1.0 / (w_r * w_r * lleak)
    mid = ck.internal("OT winding C")
    ck.add(Resistor(wind[0][0], mid, w_r * lleak, name="OT winding C loss"))
    ck.add(Capacitor(mid, wind[-1][1] if not se else bp, cw, name="OT winding C"))
    s1, s2 = ck.internal("OT secondary"), ck.internal("OT leakage")
    wind.append((s1, com, float(polarity)))
    ck.add(Transformer(wind, t, name="output transformer"))
    ck.add(Inductor(t, 0, lp / (n * n), name="OT magnetising"))
    ck.add(Resistor(t, 0, 30.0 * zp / (n * n), name="OT core loss"))
    ck.add(Resistor(s1, s2, rs, name="OT secondary"))
    ck.add(Inductor(s2, spk_node, lleak / (n * n), name="OT leakage"))


# --------------------------------------------------------------------------- feedback polarity

def forced_polarity():
    return _FORCE_POLARITY.get()


def _signature(project) -> tuple:
    return tuple(sorted((c.ref, c.value, tuple(sorted(c.pad_nets.items()))) for c in project.components))


def nfb_polarity(project, hw: AmpHardware, in_net: str = "IN") -> int:
    """Which way round the OT secondary gives negative feedback: simulate both, keep the one with less gain.

    Real amps are wired so the feedback from the speaker is negative (the other way they oscillate); a board does not
    record which secondary lead goes where, so the simulation finds it the way a builder would."""
    ot = hw.ot
    if ot is None or ot.get("polarity") in (1, -1):
        return int(ot.get("polarity") or 1) if ot else 1
    spk = ot.get("spk")
    feedback = spk and any(net == spk for c in project.components if not c.footprint.name.startswith(WIRE_PREFIX)
                           for net in c.pad_nets.values())
    if not feedback or in_net not in project.nets():
        return 1
    key = _signature(project)
    if key in _POLARITY_CACHE:
        return _POLARITY_CACHE[key]
    import numpy as np

    from .audio import build_for_audio
    from .engine import Simulator
    gains = {}
    for pol in (1, -1):
        tok = _FORCE_POLARITY.set(pol)
        try:
            ck, src, n_in, n_out = build_for_audio(project, in_net, SPEAKER_NET, None, None)
            sim = Simulator(ck)
            sim.start_op()
            h = sim.ac_sweep(np.array([150.0, 1000.0, 4000.0]), src, [n_out])[:, 0]
            gains[pol] = float(np.mean(np.abs(h)))
        except Exception:
            gains[pol] = float("inf")
        finally:
            _FORCE_POLARITY.reset(tok)
    pol = 1 if gains[1] <= gains[-1] else -1
    _POLARITY_CACHE[key] = pol
    return pol
