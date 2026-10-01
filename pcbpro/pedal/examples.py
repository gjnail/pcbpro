"""Built-in pedal example: a three-knob op-amp overdrive in a Hammond 125B.

Circuit (single 9 V supply, VREF = 4.5 V):
  input      1M pull-down, 100n coupling, 1M bias to VREF
  gain       TL072 A non-inverting: 4k7 + 47n to VREF, 51k + DRIVE (B500K) feedback, 47p roll-off,
             1N4148 pair across the feedback path (soft clipping)
  tone       1k series, then 100n + TONE (B25K, rheostat) to VREF: a variable treble cut
  output     TL072 B follower, 10u coupling cap, LEVEL (A100K) volume pot
  power      1N5817 reverse protection, 47R + 100u / 100n filter, 10k/10k/47u VREF, 4k7 LED resistor
The LED cathode goes to the LED pad so the footswitch's third pole can switch it.
"""
from __future__ import annotations

from shapely.geometry import box

from ..model.board import Component, Text
from .templates import (BlockPart, PedalOptions, block_components, new_pedal_project, pack_components, part,
                        parts_region)


def overdrive_example(route: bool = True):
    p, _notes = new_pedal_project(PedalOptions(name="Three-knob overdrive", enclosure="125B",
                                               knobs=["LEVEL", "TONE", "DRIVE"], power=False, vref=False,
                                               led="board3", color="Orange"))
    p.author = "PCBPro"
    p.notes = __doc__.strip()
    pots = {c.value: c for c in p.components if c.ref.startswith("RV")}
    pots["A100K"].pad_nets.update({"1": "GND", "2": "OUT", "3": "VOL"})
    pots["B25K"].pad_nets.update({"1": "TONE_C", "2": "VREF", "3": "VREF"})
    pots["B500K"].pad_nets.update({"1": "DRV", "2": "OA1", "3": "OA1"})

    u1 = Component(p.next_ref("U"), "TL072", part("dip8"), 0, 0, 0, "top",
                   {"1": "OA1", "2": "FB1", "3": "NIN", "4": "GND", "5": "TONE", "6": "OB", "7": "OB", "8": "V+"})
    u1.show_value = True
    x0, y0, x1, y1 = p.board.bounds()
    xm = (x0 + x1) / 2
    top = y0 + 30.0  # below the pot pins and the jack bodies
    u1.x, u1.y = round(xm / 1.27) * 1.27, top + 9.0
    p.components.append(u1)

    groups = [
        # input network, left of the op-amp
        ([BlockPart("R", "1M", "res", {"1": "IN", "2": "GND"}), BlockPart("C", "100n", "film_small", {"1": "IN", "2": "NIN"}),
          BlockPart("R", "1M", "res", {"1": "NIN", "2": "VREF"}), BlockPart("R", "1k", "res", {"1": "OA1", "2": "TONE"}),
          BlockPart("C", "100n", "film_small", {"1": "TONE", "2": "TONE_C"})],
         box(x0 + 1.5, top, xm - 5.5, top + 27)),
        # gain network, right of the op-amp
        ([BlockPart("R", "4k7", "res", {"1": "FB1", "2": "GN"}), BlockPart("C", "47n", "film_small", {"1": "GN", "2": "VREF"}),
          BlockPart("R", "51k", "res", {"1": "FB1", "2": "DRV"}), BlockPart("C", "47p", "ceramic", {"1": "OA1", "2": "FB1"}),
          BlockPart("D", "1N4148", "do35", {"2": "OA1", "1": "FB1"}), BlockPart("D", "1N4148", "do35", {"2": "FB1", "1": "OA1"})],
         box(xm + 5.5, top, x1 - 1.5, top + 27)),
        # output, power supply and bias below
        ([BlockPart("C", "10u", "elco", {"1": "OB", "2": "VOL"}),
          BlockPart("D", "1N5817", "do41", {"2": "9V", "1": "VD"}), BlockPart("R", "47R", "res", {"1": "VD", "2": "V+"}),
          BlockPart("C", "100u", "elco", {"1": "V+", "2": "GND"}), BlockPart("C", "100n", "film_small", {"1": "V+", "2": "GND"}),
          BlockPart("R", "10k", "res", {"1": "V+", "2": "VREF"}), BlockPart("R", "10k", "res", {"1": "VREF", "2": "GND"}),
          BlockPart("C", "47u", "elco", {"1": "VREF", "2": "GND"})],
         box(x0 + 1.5, top + 27, x1 - 1.5, y1 - 1.5)),
    ]
    p.texts.append(Text("THREE-KNOB OD", xm, y1 - 11.0, 1.4, "F.SilkS"))
    p.texts.append(Text("PCBPro pedal example  rev A", xm, y1 - 16.0, 1.0, "B.SilkS"))
    free = parts_region(p, "top")  # clear of the top-mounted jack and DC socket bodies
    for parts, region in groups:
        comps = block_components(p, parts)
        placed = pack_components(p, comps, region.intersection(free), "top", gap=1.2)
        missing = [c for c in comps if c not in placed]
        if missing:  # anywhere free on the board rather than nowhere
            pack_components(p, missing, free, "top", gap=0.8)
    if route:
        from ..model.copper import fill_all_zones
        from ..route.autorouter import Autorouter
        Autorouter(p).run()  # pours are filled by the router's pour phase
        fill_all_zones(p)
    return p
