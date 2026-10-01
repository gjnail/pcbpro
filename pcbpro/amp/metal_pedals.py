"""Metal pedals: complete, placed and routed pedal boards that go with a high-gain amp.

* **Tight boost** - an input buffer, a TIGHT control (a variable low cut, 30-340 Hz) and a Tube Screamer style
  op-amp stage with soft clipping and its 720 Hz mid hump. Drive down and level up in front of a high-gain amp is
  the classic metal trick: the lows that would turn palm mutes to mush are cut before the preamp, the mids are
  pushed, the attack gets sharper.
* **Noise gate (4-cable)** - a keyed gate: it listens to the guitar (IN, buffered out to SEND for the amp's
  input) and gates the amp's effects loop (RETURN to OUT), so it cuts the preamp's hiss between riffs without
  choking notes (the "4-cable method"). With nothing in RETURN, the jack's switch feeds the guitar back in and it
  works as an ordinary 2-jack gate. THRESHOLD and RELEASE; a J201 shunt gate keyed by an envelope detector and
  a comparator with hysteresis, fast to open and fading out to close.
* **High-gain distortion** - two cascaded op-amp gain stages, each hard-clipped by a silicon diode pair (the
  first with a 720 Hz pre-emphasis so the lows stay tight), then an amp-style passive bass / middle / treble
  stack (the same FMV network as the Amp Designer's high-gain amps) and a recovery stage.

Everything runs from 9 V (centre negative) with a VREF = 4.5 V half-supply. Jacks and the 3PDT footswitch are
panel-mounted and wired to labelled pads. The boards use the pedal framework (enclosure, drilling, 3D, checks), and
the simulator can play guitar through them.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from shapely.geometry import box
from shapely.ops import unary_union

from ..model.board import Component, Text
from ..model.copper import pad_geom
from ..pedal.enclosure import PanelHole, get_enclosure, set_enclosure, side_position
from ..pedal.templates import BlockPart, PedalOptions, block_components, new_pedal_project, pack_components, part, \
    parts_region


@dataclass(frozen=True)
class PedalKind:
    key: str
    title: str
    blurb: str
    enclosure: str
    knobs: tuple


PEDALS = {k.key: k for k in (
    PedalKind("tight_boost", "Tight Boost",
              "Tube Screamer style boost / overdrive with a TIGHT low-cut control: in front of a high-gain amp it "
              "tightens the low end and pushes the mids (drive low, level high).", "125B",
              ("LEVEL", "TONE", "DRIVE", "TIGHT")),
    PedalKind("noise_gate", "Noise Gate (4-cable)",
              "A keyed gate for the amp's effects loop: listens to the guitar, silences the preamp's hiss between "
              "riffs. Also works as a plain 2-jack gate.", "1590BB2", ("THRESHOLD", "RELEASE")),
    PedalKind("distortion", "High-Gain Distortion",
              "Two cascaded clipping stages and an amp-style bass / middle / treble stack: thick, tight metal "
              "distortion into a clean amp, or stacked into a crunch channel.", "1590BB2",
              ("LEVEL", "GAIN", "BASS", "MID", "TREBLE")),
)}


def _power(caps: int = 1, vref: str = "10k") -> list[BlockPart]:
    """9 V in: series Schottky (reverse polarity), 47R + 100u / 100n filter, ``vref`` / ``vref`` / 47u VREF."""
    out = [BlockPart("D", "1N5817", "do41", {"2": "9V", "1": "VD"}), BlockPart("R", "47R", "res", {"1": "VD", "2": "V+"}),
           BlockPart("C", "100u", "elco", {"1": "V+", "2": "GND"})]
    out += [BlockPart("C", "100n", "film_small", {"1": "V+", "2": "GND"}) for _ in range(caps)]
    out += [BlockPart("R", vref, "res", {"1": "V+", "2": "VREF"}), BlockPart("R", vref, "res", {"1": "VREF", "2": "GND"}),
            BlockPart("C", "47u", "elco", {"1": "VREF", "2": "GND"})]
    return out


def _pots(p, knobs, nets: dict, values: dict | None = None) -> None:
    """Wire the generator's pots (made in knob order; pins 1-2-3 seen from the front, CW moves the wiper to 3)."""
    pots = [c for c in p.components if c.ref.startswith("RV")]
    for c, lab in zip(pots, knobs):
        if lab in nets:
            c.pad_nets.update(nets[lab])
        if values and lab in values:
            c.value = values[lab]


def _prepare(p) -> None:
    """Tidy the generated panel: push a lower-row pot down until its courtyard (pins and bracket) clears the row
    above, and take out the generator's LED resistor - it is placed again with the circuit, after any extra
    panel holes are in."""
    pots = sorted((c for c in p.components if c.ref.startswith("RV")), key=lambda c: c.y)
    for i, c in enumerate(pots):
        for other in pots[:i]:
            while c.y > other.y + 1.0 and c.courtyard_polygon().buffer(0.6).intersects(other.courtyard_polygon()):
                c.y += 0.5
                for t in p.texts:
                    if t.layer == "F.SilkS" and abs(t.x - c.x) < 0.01:
                        t.y += 0.5
    for c in list(p.components):
        if c.ref.startswith("R") and not c.ref.startswith("RV") and set(c.pad_nets.values()) == {"V+", "LED_A"}:
            p.components.remove(c)


def _wire_strip(p, labels: list[str]) -> None:
    """Off-board wire pads (jacks, DC, footswitch, LED) along the bottom edge of the board."""
    from ..library.gen_pedal import wire_pads
    wp = Component(p.next_ref("W"), "Off-board", wire_pads(labels), 0, 0, 0, "top", {k: k for k in labels})
    wp.show_ref = False
    bx0, by0, bx1, by1 = p.board.bounds()
    region = box(bx0, by1 - 9.0, bx1, by1).intersection(_free(p))
    if not pack_components(p, [wp], region, "top"):
        pack_components(p, [wp], _free(p), "top")


def _free(p):
    """Where top-side parts may go: clear of the side-wall hardware and of the face-side parts' pins."""
    region = parts_region(p, "top")
    pins = [pad_geom(c, pad).buffer(1.4) for c in p.components if c.side != "top" for pad in c.footprint.pads
            if pad.kind in ("tht", "npth")]
    return region.difference(unary_union(pins)) if pins else region


def _place(p, ics: list[Component], parts: list[BlockPart]) -> list[str]:
    """Put the ICs in the middle of the free area, then every other part next to the pins it connects to. If the
    board is too crowded for that, try again tighter: smaller gaps, then 1/8 W resistors on a 7.62 mm pitch."""
    from ..amp.builder import _pack
    parts = parts + [BlockPart("R", "4k7", "res", {"1": "V+", "2": "LED_A"})]  # the status LED's resistor
    base = list(p.components)
    missing: list = []
    for gap, small in ((1.0, False), (0.6, False), (0.6, True), (0.3, True)):
        p.components[:] = base
        free = _free(p)
        cx, cy = free.centroid.x, free.centroid.y
        for k, ic in enumerate(ics):
            dx = (k - (len(ics) - 1) / 2) * 16.0
            for r in (10.0, 15.0, 22.0, 32.0, 60.0):  # nearest the middle that is free
                if pack_components(p, [ic], free.intersection(box(cx + dx - r, cy - r, cx + dx + r, cy + r)), "top",
                                   gap=1.5):
                    break
        use = [replace(bp, part="res_small") if small and bp.part == "res" else bp for bp in parts]
        comps = block_components(p, use)
        placed = _pack(p, comps, _free(p), step=1.27, gap=gap)
        rest = [c for c in comps if c not in placed]
        if rest:
            pack_components(p, rest, _free(p), "top", gap=0.4)
        missing = [c.ref for c in comps if c not in p.components]
        if not missing:
            break
    return missing


def _finish(p, title: str, notes: str, route: bool, missing: list | None = None) -> None:
    if missing:
        raise RuntimeError(f"{title}: no room on the board for {', '.join(missing)}")
    bx0, by0, bx1, by1 = p.board.bounds()
    p.texts.append(Text(f"PCBPro {title}  rev A", (bx0 + bx1) / 2, by1 - 3.0, 1.0, "B.SilkS"))
    p.author = "PCBPro"
    p.notes = notes.strip()
    if route:
        from ..model.copper import fill_all_zones
        from ..route.autorouter import Autorouter
        Autorouter(p).run()  # the router's pour phase fills the zones
        fill_all_zones(p)


# --------------------------------------------------------------------------- tight boost

def tight_boost(route: bool = True):
    kind = PEDALS["tight_boost"]
    p, _ = new_pedal_project(PedalOptions(name=kind.title, enclosure=kind.enclosure, knobs=list(kind.knobs),
                                          power=False, vref=False, wire_pads=False, led="board3", color="Green"))
    _pots(p, kind.knobs, {"LEVEL": {"1": "GND", "2": "OUT", "3": "VOL"},  # A100K volume
              "TONE": {"1": "TONE_C", "2": "VREF", "3": "VREF"},  # B25K rheostat: more resistance CW = brighter
              "DRIVE": {"1": "DRV", "2": "OA", "3": "OA"},  # B500K rheostat in the feedback: more gain CW
              "TIGHT": {"1": "TGT", "2": "TGT", "3": "VREF"}},  # C100K: less resistance CW = higher low cut
          {"TIGHT": "C100K"})  # reverse log: wiper-to-3 falls 100k -> 10k -> 0, so the cut sweeps evenly in octaves
    _prepare(p)
    _wire_strip(p, ["9V", "GND", "IN", "OUT", "LED"])
    u1 = Component(p.next_ref("U"), "TL072", part("dip8"), 0, 0, 0, "top",
                   {"1": "BUF", "2": "BUF", "3": "NIN", "4": "GND", "5": "HP", "6": "FB", "7": "OA", "8": "V+"})
    parts = [
        # input buffer
        BlockPart("R", "1M", "res", {"1": "IN", "2": "GND"}), BlockPart("C", "100n", "film_small", {"1": "IN", "2": "NIN"}),
        BlockPart("R", "1M", "res", {"1": "NIN", "2": "VREF"}),
        # TIGHT: 47n into 10k + B100K to VREF = a 30-340 Hz low cut ahead of the gain stage
        BlockPart("C", "47n", "film_small", {"1": "BUF", "2": "HP"}), BlockPart("R", "10k", "res", {"1": "HP", "2": "TGT"}),
        # gain stage: 4k7 + 47n to VREF (720 Hz: the mids get the gain, the lows stay at unity), 51k + DRIVE,
        # 51p roll-off, 1N4148 pair in the feedback (soft clipping)
        BlockPart("R", "4k7", "res", {"1": "FB", "2": "GN"}), BlockPart("C", "47n", "film_small", {"1": "GN", "2": "VREF"}),
        BlockPart("R", "51k", "res", {"1": "FB", "2": "DRV"}), BlockPart("C", "51p", "ceramic", {"1": "OA", "2": "FB"}),
        BlockPart("D", "1N4148", "do35", {"2": "OA", "1": "FB"}), BlockPart("D", "1N4148", "do35", {"2": "FB", "1": "OA"}),
        # tone (variable treble cut) and output
        BlockPart("R", "1k", "res", {"1": "OA", "2": "TONE"}), BlockPart("C", "100n", "film_small", {"1": "TONE", "2": "TONE_C"}),
        BlockPart("C", "10u", "elco", {"1": "TONE", "2": "VOL"}), BlockPart("R", "100k", "res", {"1": "VOL", "2": "GND"}),
    ] + _power()
    missing = _place(p, [u1], parts)
    _finish(p, kind.title, f"""
{kind.title} - {kind.blurb}

Circuit (9 V, VREF 4.5 V, TL072):
  input      1M pull-down, 100n coupling, 1M bias to VREF, op-amp A as a unity buffer (1M input impedance)
  TIGHT      47n into 10k + C100K (reverse log) to VREF: a low cut from about 30 Hz (CCW) through 170 Hz (noon)
             to 340 Hz (CW), before the gain
  gain       op-amp B non-inverting: 4k7 + 47n to VREF (gain rises above 720 Hz - the mid hump), 51k + DRIVE (B500K)
             feedback, 51p roll-off, 1N4148 pair across the feedback (soft clipping)
  tone       1k series, then 100n + TONE (B25K, rheostat) to VREF: a variable treble cut
  output     10u coupling, LEVEL (A100K) volume pot; 100k keeps the output at 0 V DC (no switch pop)
  power      1N5817 reverse protection, 47R + 100u / 100n filter, 10k / 10k / 47u VREF, 4k7 LED resistor

With a high-gain amp: DRIVE near zero, LEVEL up, TIGHT to taste (more for down-tuned and extended-range guitars).
Wire the 3PDT footswitch for true bypass: pads IN and OUT go to the footswitch's effect side, the jacks to its
common lugs, and the third pole switches the LED pad to ground.
""", route, missing)
    return p


# --------------------------------------------------------------------------- noise gate

def noise_gate(route: bool = True):
    kind = PEDALS["noise_gate"]
    p, _ = new_pedal_project(PedalOptions(name=kind.title, enclosure=kind.enclosure, knobs=list(kind.knobs),
                                          jacks="side", power=False, vref=False, wire_pads=False, led="board3",
                                          color="Black"))
    _pots(p, kind.knobs, {"THRESHOLD": {"1": "VREF", "2": "THW", "3": "THT"},  # higher threshold CW
              "RELEASE": {"1": "REL", "2": "VREF", "3": "VREF"}},  # longer release CW
          {"THRESHOLD": "B10K", "RELEASE": "B1M"})
    _prepare(p)
    # SEND and RETURN on the top wall either side of the DC socket, deep enough that their bodies clear the board
    enc = get_enclosure(p)
    W, H = enc.cavity_size
    _near, far = enc.z_levels(p)
    z = far + 9.0 + 0.4
    for label, u in (("SEND", 20.0), ("RETURN", -20.0)):
        sx, sy = side_position(enc, "B", u, H / 2, z)
        enc.holes.append(PanelHole.of("jack", "B", sx, sy, label))
    set_enclosure(p, enc)
    _wire_strip(p, ["9V", "GND", "IN", "SEND", "RET", "OUT", "LED", "BYP"])
    u1 = Component(p.next_ref("U"), "TL074", part("DIP-14 (300 mil)"), 0, 0, 0, "top",
                   {"1": "BUF", "2": "BUF", "3": "GIN", "4": "V+", "5": "BUF", "6": "DFB", "7": "DOUT",
                    "8": "GCTL", "9": "ENV", "10": "THH", "11": "GND", "12": "GN", "13": "OBUF", "14": "OBUF"})
    j1 = BlockPart("Q", "J201", "jfet", {"D": "GN", "S": "VREF", "G": "JG"})
    parts = [
        # guitar in: buffer A, buffered out to SEND (the amp's input in the 4-cable method)
        BlockPart("R", "1M", "res", {"1": "IN", "2": "GND"}), BlockPart("C", "100n", "film_small", {"1": "IN", "2": "GIN"}),
        BlockPart("R", "1M", "res", {"1": "GIN", "2": "VREF"}),
        BlockPart("C", "10u", "elco", {"1": "BUF", "2": "SEND_C"}), BlockPart("R", "100k", "res", {"1": "SEND_C", "2": "GND"}),
        BlockPart("R", "100R", "res", {"1": "SEND_C", "2": "SEND"}),
        # envelope: B is a precision half-wave rectifier with a gain of 22 (470k / 22k), charging 470n at ENV;
        # 47k + RELEASE (B1M) let it fall back in 25-550 ms. The gain network is DC-coupled to VREF on purpose (a
        # cap there would charge up to the envelope and stop the detector), and the impedances are high so the
        # envelope's current hardly moves VREF (which is stiffened to 4k7 / 4k7)
        BlockPart("D", "1N4148", "do35", {"2": "DOUT", "1": "ENV"}), BlockPart("R", "470k", "res", {"1": "ENV", "2": "DFB"}),
        BlockPart("R", "22k", "res", {"1": "DFB", "2": "VREF"}),
        BlockPart("C", "470n", "film", {"1": "ENV", "2": "VREF"}), BlockPart("R", "47k", "res", {"1": "ENV", "2": "REL"}),
        # threshold: VREF .. VREF + 1 V on the wiper; comparator C with hysteresis (10k / 1M)
        BlockPart("R", "33k", "res", {"1": "V+", "2": "THT"}), BlockPart("R", "10k", "res", {"1": "THW", "2": "THH"}),
        BlockPart("R", "1M", "res", {"1": "GCTL", "2": "THH"}),
        # the gate: J201 from the loop signal to VREF. Comparator high (no signal) -> the JFET conducts -> mute;
        # low -> pinched off -> pass. Opens fast through the diode and 10k, closes through 1M x 47n (a 20 ms fade).
        j1, BlockPart("R", "1M", "res", {"1": "GCTL", "2": "JG"}), BlockPart("D", "1N4148", "do35", {"2": "JG", "1": "GQ"}),
        BlockPart("R", "10k", "res", {"1": "GQ", "2": "GCTL"}), BlockPart("C", "47n", "film_small", {"1": "JG", "2": "GND"}),
        BlockPart("R", "1k", "res", {"1": "BYP", "2": "JG"}),
        # the loop path: RETURN -> 100n -> 47k into the JFET node -> buffer D -> OUT
        BlockPart("C", "100n", "film_small", {"1": "RET", "2": "RETB"}), BlockPart("R", "1M", "res", {"1": "RETB", "2": "VREF"}),
        BlockPart("R", "47k", "res", {"1": "RETB", "2": "GN"}),
        BlockPart("C", "10u", "elco", {"1": "OBUF", "2": "OUT_C"}), BlockPart("R", "100k", "res", {"1": "OUT_C", "2": "GND"}),
        BlockPart("R", "100R", "res", {"1": "OUT_C", "2": "OUT"}),
    ] + _power(vref="4k7")
    missing = _place(p, [u1], parts)
    _finish(p, kind.title, f"""
{kind.title} - {kind.blurb}

The 4-cable method: guitar -> IN; SEND -> the amp's INPUT; the amp's FX SEND -> RETURN; OUT -> the amp's FX RETURN.
The gate listens to your guitar (before the amp's gain, where it is clean) and gates the loop (after the preamp,
where the hiss is), so notes are not cut off and the hiss between riffs is. With nothing plugged into RETURN its
switch feeds the guitar signal in: a normal 2-jack gate, IN -> OUT.

Circuit (9 V, VREF 4.5 V, TL074):
  A  input buffer (1M), buffered out to SEND through 10u / 100R
  B  envelope detector: precision half-wave rectifier (the diode inside the loop), gain 22 (470k / 22k to VREF),
     into 470n; 47k + RELEASE (B1M) discharge it (25-550 ms)
  C  comparator: ENV against THRESHOLD (B10K wiper, VREF to VREF + 1 V), 10k / 1M hysteresis
  D  output buffer after the gate, out to OUT through 10u / 100R
  gate  J201 from the 47k-fed loop node to VREF: with no signal the comparator turns it on (-35 dB); it pinches
        off within 0.5 ms when you play and fades back in over about 20 ms
  power 1N5817, 47R + 100u / 100n, 4k7 / 4k7 / 47u VREF (stiff, so the envelope does not move it), 4k7 LED
        resistor

Wiring: RETURN jack tip -> RET pad, its switch lug (closed with no plug) -> SEND pad. Bypass: a 3PDT pole joins
BYP to GND (the gate is held open, buffered bypass); another pole switches the LED pad to ground when it is on.
""", route, missing)
    return p


# --------------------------------------------------------------------------- high-gain distortion

def distortion(route: bool = True):
    from .tonestack import PRESETS
    kind = PEDALS["distortion"]
    ts = PRESETS["Modern high gain (47k slope)"]
    p, _ = new_pedal_project(PedalOptions(name=kind.title, enclosure=kind.enclosure, knobs=list(kind.knobs),
                                          jacks="side", power=False, vref=False, wire_pads=False, led="board3",
                                          color="Red"))
    _pots(p, kind.knobs, {"LEVEL": {"1": "VREF", "2": "LV", "3": "O3"},
              "GAIN": {"1": "GR1", "2": "O1", "3": "O1"},
              "TREBLE": {"1": "TS_B", "2": "TS_OUT", "3": "TS_T"},
              "BASS": {"1": "TS_B", "2": "TS_M", "3": "TS_M"},
              "MID": {"1": "TS_M", "2": "VREF", "3": "VREF"}},
          {"LEVEL": "A100K", "GAIN": "B500K", "TREBLE": "A250K", "BASS": "A1M", "MID": "B25K"})
    _prepare(p)
    _wire_strip(p, ["9V", "GND", "IN", "OUT", "LED"])
    u1 = Component(p.next_ref("U"), "TL074", part("DIP-14 (300 mil)"), 0, 0, 0, "top",
                   {"1": "O1", "2": "F1", "3": "G1", "4": "V+", "5": "CL1", "6": "F2", "7": "O2", "8": "O3",
                    "9": "F3", "10": "TS_OUT", "11": "GND", "12": "LV", "13": "O4", "14": "O4"})
    parts = [
        BlockPart("R", "1M", "res", {"1": "IN", "2": "GND"}), BlockPart("C", "22n", "film_small", {"1": "IN", "2": "G1"}),
        BlockPart("R", "1M", "res", {"1": "G1", "2": "VREF"}),
        # stage 1: 4k7 + 47n (720 Hz pre-emphasis keeps the lows out of the clipping), 10k + GAIN (B500K), 100p
        BlockPart("R", "4k7", "res", {"1": "F1", "2": "GN1"}), BlockPart("C", "47n", "film_small", {"1": "GN1", "2": "VREF"}),
        BlockPart("R", "10k", "res", {"1": "F1", "2": "GR1"}), BlockPart("C", "100p", "ceramic", {"1": "O1", "2": "F1"}),
        BlockPart("R", "2k2", "res", {"1": "O1", "2": "CL1"}),
        BlockPart("D", "1N4148", "do35", {"2": "CL1", "1": "VREF"}), BlockPart("D", "1N4148", "do35", {"2": "VREF", "1": "CL1"}),
        # stage 2: x16 (2k2 + 100n to VREF, 33k), 220p roll-off, second hard clipper
        BlockPart("R", "2k2", "res", {"1": "F2", "2": "GN2"}), BlockPart("C", "100n", "film_small", {"1": "GN2", "2": "VREF"}),
        BlockPart("R", "33k", "res", {"1": "F2", "2": "O2"}), BlockPart("C", "220p", "ceramic", {"1": "O2", "2": "F2"}),
        BlockPart("R", "2k2", "res", {"1": "O2", "2": "CL2"}),
        BlockPart("D", "1N4148", "do35", {"2": "CL2", "1": "VREF"}), BlockPart("D", "1N4148", "do35", {"2": "VREF", "1": "CL2"}),
        # amp-style tone stack (470p / 47k / 22n / 22n, 250k treble, 1M bass, 25k mid), returned to VREF
        BlockPart("C", "470p", "ceramic", {"1": "CL2", "2": "TS_T"}), BlockPart("R", "47k", "res", {"1": "CL2", "2": "TS_A"}),
        BlockPart("C", "22n", "film_small", {"1": "TS_A", "2": "TS_B"}), BlockPart("C", "22n", "film_small", {"1": "TS_A", "2": "TS_M"}),
        # recovery x11, LEVEL, output buffer
        BlockPart("R", "4k7", "res", {"1": "F3", "2": "GN3"}), BlockPart("C", "10u", "elco", {"1": "GN3", "2": "VREF"}),
        BlockPart("R", "47k", "res", {"1": "F3", "2": "O3"}),
        BlockPart("C", "10u", "elco", {"1": "O4", "2": "OUT_C"}), BlockPart("R", "100k", "res", {"1": "OUT_C", "2": "GND"}),
        BlockPart("R", "100R", "res", {"1": "OUT_C", "2": "OUT"}),
    ] + _power()
    missing = _place(p, [u1], parts)
    _finish(p, kind.title, f"""
{kind.title} - {kind.blurb}

Circuit (9 V, VREF 4.5 V, TL074):
  input      1M pull-down, 22n coupling, 1M bias to VREF
  stage 1    U1A non-inverting: 4k7 + 47n to VREF (gain rises above 720 Hz: tight lows), 10k + GAIN (B500K)
             feedback (x3 to x110), 100p roll-off; 2k2 into a 1N4148 pair to VREF (hard clipping)
  stage 2    U1B: x16 above 720 Hz (2k2 + 100n, 33k), 220p roll-off; 2k2 into a second 1N4148 pair
  tone       the amp-style FMV stack ({ts.c1 * 1e12:g}p / {ts.r1 / 1e3:g}k / 22n / 22n with 250k treble, 1M bass, 25k mid),
             returned to VREF: BASS, MID and TREBLE work like a Marshall's
  recovery   U1C x11 (47k / 4k7 + 10u), LEVEL (A100K) to U1D, a unity output buffer, 10u / 100R to OUT
  power      1N5817, 47R + 100u / 100n, 10k / 10k / 47u VREF, 4k7 LED resistor

Wire the 3PDT footswitch for true bypass (IN / OUT pads to the effect side, the third pole switches the LED pad).
""", route, missing)
    return p


def tight_boost_response(f, tight: float = 0.5, drive: float = 0.0, tone: float = 0.7):
    """Small-signal response (complex) of the Tight Boost for knob settings 0..1: the TIGHT high-pass, the Tube
    Screamer gain shelf and the tone control - what it does to the lows going into an amp."""
    import numpy as np
    s = 2j * np.pi * np.asarray(f, dtype=float)
    r_tight = 10e3 + 100e3 * (81.0 ** (1.0 - tight) - 1.0) / 80.0  # 10k + the C100K from wiper to pin 3
    hp = s * r_tight * 47e-9 / (1 + s * r_tight * 47e-9)
    rf = 51e3 + drive * 500e3
    zf = rf / (1 + s * rf * 51e-12)
    zg = 4.7e3 + 1 / (s * 47e-9)
    gain = 1 + zf / zg
    zt = (1 - tone) * 25e3 + 1.0 + 1 / (s * 100e-9)  # the tone pot is a rheostat: brighter CW
    return hp * gain * zt / (zt + 1e3)


BUILDERS = {"tight_boost": tight_boost, "noise_gate": noise_gate, "distortion": distortion}
# placed and routed copies shipped in resources/examples (rebuilt by tools/build_examples.py)
METAL_EXAMPLES = {"tight_boost": "Metal_Tight_Boost_125B.pcbpro", "noise_gate": "Metal_Noise_Gate_1590BB2.pcbpro",
                  "distortion": "Metal_High_Gain_Distortion_1590BB2.pcbpro"}


def build_pedal(key: str, route: bool = True):
    """A complete metal pedal project by key (see PEDALS)."""
    return BUILDERS[key](route=route)
