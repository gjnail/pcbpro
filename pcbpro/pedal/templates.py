"""New-pedal generator, reusable circuit blocks and a simple placement packer."""
from __future__ import annotations

from dataclasses import dataclass, field

from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union
from shapely.strtree import STRtree

from ..model import footprints as fplib
from ..model.board import Board, Component, Footprint, NetClass, Project, Text, Zone
from ..model.copper import pad_geom
from .enclosure import (CATALOG, HARDWARE, Enclosure, PanelHole, fit_outline, knob_layout, set_enclosure,
                        side_position)

# Library names of the through-hole parts pedal builders use (with fallbacks to the core generators).
PARTS = {
    "res": "Resistor axial 1/4 W P10.16",
    "res_small": "Resistor axial 1/8 W P7.62",
    "film": "Film box L7.2 W3.5 P5",
    "film_small": "Film box L7.2 W2.5 P5",
    "ceramic": "MLCC radial P5.08",
    "elco": "Electrolytic D6.3 P2.5 H11",
    "elco_small": "Electrolytic D5 P2 H11",
    "elco_low": "Electrolytic D4 P1.5 H7",
    "do35": "Diode DO-35",
    "do41": "Diode DO-41",
    "dip8": "DIP-8 (300 mil)",
    "led3": "LED 3 mm THT",
    "led5": "LED 5 mm THT",
    "pot16": "Alpha 16 mm pot (PCB right-angle)",
    "pot9": "Alpha 9 mm pot (PCB vertical)",
    "npn": "TO-92 E-B-C (BJT, wide)",
    "jfet": "TO-92 D-S-G (JFET, wide)",
}


def part(key: str) -> Footprint:
    lp = fplib.find_part(PARTS.get(key, key))
    if lp is not None:
        return lp.make()
    fallback = {"res": fplib.resistor_axial, "res_small": fplib.resistor_axial, "do41": fplib.diode_do41,
                "do35": fplib.diode_do41, "dip8": lambda: fplib.dip(8), "led3": lambda: fplib.led_tht(3),
                "led5": lambda: fplib.led_tht(5), "elco": lambda: fplib.cap_radial(6.3, 2.5, 11),
                "elco_small": lambda: fplib.cap_radial(5, 2.0, 11), "elco_low": lambda: fplib.cap_radial(5, 2.0, 7)}
    if key in fallback:
        return fallback[key]()
    raise KeyError(f"Library part not found: {PARTS.get(key, key)}")


def pot_value(label: str) -> str:
    l = label.upper()
    if any(k in l for k in ("LEVEL", "VOL", "OUTPUT", "MASTER")):
        return "A100K"
    if any(k in l for k in ("DRIVE", "GAIN", "FUZZ", "DIST", "SUSTAIN")):
        return "B500K"
    if any(k in l for k in ("TONE", "TREBLE", "BASS", "MID", "FILTER")):
        return "B25K"
    if any(k in l for k in ("BLEND", "MIX")):
        return "B50K"
    return "B100K"


# --------------------------------------------------------------------------- placement packer

def _keepouts(project: Project, side: str, extra: float = 0.6) -> list:
    geoms = []
    silk = "F.SilkS" if side == "top" else "B.SilkS"
    for t in project.texts:
        if t.layer == silk:
            try:
                from ..model.textgeom import text_geometry
                geoms.append(text_geometry(t.text, t.x, t.y, t.size, t.rotation, t.mirrored).envelope.buffer(0.3))
            except Exception:  # no Qt font engine available: skip text keep-outs
                pass
    for c in project.components:
        if c.side == side:
            geoms.append(footprint_area(c).buffer(extra, join_style="mitre"))
        else:  # through-hole pads of parts on the other side still block this side
            for pad in c.footprint.pads:
                if pad.kind in ("tht", "npth"):
                    geoms.append(pad_geom(c, pad).buffer(0.8 + extra))
    return geoms


def footprint_area(c: Component) -> Polygon:
    """Courtyard plus the silkscreen reference (above) and value (below) text bands."""
    x0, y0, x1, y1 = c.footprint.courtyard
    if c.show_ref and c.ref:
        y0 = min(y0, c.footprint.ref_pos[1] - 0.7)
    if c.show_value and c.value:
        y1 = y1 + 1.6
    return c.geom_to_board(box(x0, y0, x1, y1))


def parts_region(project: Project, side: str = "top", reach: float = 12.0) -> Polygon:
    """The board minus the space taken by side-wall hardware (jack and DC socket bodies) at the depth where
    parts up to ``reach`` mm tall on ``side`` of the board would sit."""
    from .checks import _overlap, _side_body
    from .enclosure import get_enclosure
    board = project.board.polygon()
    enc = get_enclosure(project)
    if enc is None:
        return board
    near, far = enc.z_levels(project)
    zr = (near - reach, near) if side == enc.face_side else (far, far + reach)
    blocks = [enc.geom_to_board(rect.buffer(1.0)) for rect, hz in
              (_side_body(enc, h) for h in enc.holes if h.face != "A") if _overlap(hz, zr)]
    return board.difference(unary_union(blocks)) if blocks else board


def pack_components(project: Project, comps: list[Component], region: Polygon | None = None, side: str = "top",
                    step: float = 1.27, gap: float = 0.6, start: tuple | None = None) -> list[Component]:
    """Place components row by row (left to right, top to bottom) into free space inside ``region`` (defaults to
    the board, inset from the edge). Components that do not fit are left where they are. Returns the placed ones."""
    board = project.board.polygon()
    area = (region or board).intersection(board.buffer(-1.0, join_style="mitre"))
    if area.is_empty:
        return []
    blocked = _keepouts(project, side, gap)
    placed = []
    x0, y0, x1, y1 = area.bounds
    if start:
        x0, y0 = max(x0, start[0]), max(y0, start[1])
    for c in comps:
        c.side = side
        tree = STRtree(blocked) if blocked else None
        done = False
        cx0, cy0, cx1, cy1 = c.footprint.courtyard
        y = y0 - cy0
        while not done and y + cy1 <= y1 + 1e-6:
            x = x0 - cx0
            while x + cx1 <= x1 + 1e-6:
                c.x, c.y = round(x / step) * step, round(y / step) * step
                cy = c.courtyard_polygon()
                fa = footprint_area(c)
                if area.contains(cy) and (tree is None or not any(
                        blocked[i].intersects(fa) for i in tree.query(fa))):
                    done = True
                    break
                x += step
            if not done:
                y += step
        if done:
            project.components.append(c)
            blocked.append(footprint_area(c).buffer(gap, join_style="mitre"))
            placed.append(c)
    return placed


# --------------------------------------------------------------------------- circuit blocks

@dataclass
class BlockPart:
    prefix: str
    value: str
    part: str
    nets: dict
    rotation: float = 0.0
    show_value: bool = True


def power_block(elco: str = "elco") -> list[BlockPart]:
    """Centre-negative 9 V input: series Schottky for reverse polarity, RC filter, bulk + HF decoupling."""
    return [
        BlockPart("D", "1N5817", "do41", {"2": "9V", "1": "VD"}),
        BlockPart("R", "47R", "res", {"1": "VD", "2": "V+"}),
        BlockPart("C", "100uF", elco, {"1": "V+", "2": "GND"}),
        BlockPart("C", "100nF", "film_small", {"1": "V+", "2": "GND"}),
    ]


def vref_block(elco: str = "elco") -> list[BlockPart]:
    """Half-supply bias (VREF = 4.5 V) for single-supply op-amp stages."""
    return [
        BlockPart("R", "10k", "res", {"1": "V+", "2": "VREF"}),
        BlockPart("R", "10k", "res", {"1": "VREF", "2": "GND"}),
        BlockPart("C", "47uF", elco, {"1": "VREF", "2": "GND"}),
    ]


def led_block(board_led: str | None = "led3") -> list[BlockPart]:
    """Status LED current-limit resistor; the 3PDT's third pole switches the LED cathode (LED pad) to ground."""
    out = [BlockPart("R", "4k7", "res", {"1": "V+", "2": "LED_A" if board_led else "LED"})]
    if board_led:
        out.append(BlockPart("D", "Red", board_led, {"2": "LED_A", "1": "LED"}, show_value=False))
    return out


BLOCKS = {
    "Power supply (9 V filter + reverse polarity)": power_block,
    "Bias voltage VREF (4.5 V)": vref_block,
    "Status LED + resistor": led_block,
}


def block_components(project: Project, parts: list[BlockPart]) -> list[Component]:
    out = []
    taken: set[str] = set()
    for bp in parts:
        fp = part(bp.part)
        ref = project.next_ref(bp.prefix)
        n = int(ref[len(bp.prefix):])
        while f"{bp.prefix}{n}" in taken:
            n += 1
        ref = f"{bp.prefix}{n}"
        taken.add(ref)
        c = Component(ref, bp.value, fp, 0.0, 0.0, bp.rotation, "top", dict(bp.nets))
        c.show_value = bp.show_value
        out.append(c)
        project.components.append(c)  # reserve the reference while numbering the rest
    for c in out:
        project.components.remove(c)
    return out


def insert_block(project: Project, parts: list[BlockPart], region: Polygon | None = None,
                 side: str = "top") -> list[Component]:
    comps = block_components(project, parts)
    return pack_components(project, comps, region, side)


# --------------------------------------------------------------------------- new pedal

@dataclass
class PedalOptions:
    name: str = "My Pedal"
    enclosure: str = "125B"
    orientation: str = ""
    knobs: list = field(default_factory=lambda: ["LEVEL", "TONE", "DRIVE"])
    pot: str = "pot"  # pot (16 mm) | pot9
    jacks: str = "auto"  # auto | top | side
    led: str = "board3"  # board3 | board5 | panel | none
    power: bool = True
    vref: bool = True
    wire_pads: bool = True
    pour: bool = True
    silk_values: bool = True
    color: str = "Raw aluminium"
    # extra panel holes (e.g. SEND / RETURN jacks): taken into account when the board and parts are laid out
    extra_holes: list = field(default_factory=list)


def pedal_rules(p: Project) -> None:
    """Hand-soldering friendly rules for through-hole pedal boards."""
    r = p.rules
    r.clearance, r.track_width, r.min_track, r.edge_clearance = 0.25, 0.4, 0.2, 0.5
    r.via_diameter, r.via_drill = 0.9, 0.45
    p.netclasses["Default"] = NetClass("Default", 0.25, 0.4, 0.9, 0.45)
    p.netclasses["Power"] = NetClass("Power", 0.3, 0.6, 1.0, 0.5)
    for n in ("9V", "VD", "V+", "GND"):
        p.net_class_map[n] = "Power"


def _elco_for(enc: Enclosure, project: Project) -> str:
    return "elco" if enc.free_depth(project) >= 12.5 else "elco_low"


def new_pedal_project(o: PedalOptions) -> tuple[Project, list[str]]:
    """Build a starting point for a pedal: enclosure-shaped board, pots at the knob positions, panel holes for the
    footswitch and jacks, optional power / bias / LED sections and off-board wire pads. Returns (project, notes)."""
    notes: list[str] = []
    p = Project(o.name)
    enc = Enclosure(o.enclosure if o.enclosure in CATALOG else "125B", o.orientation, color=o.color)
    W, H = enc.face_size
    Wc, Hc = enc.cavity_size
    enc.cx, enc.cy = round(W / 2, 2), round(H / 2, 2)
    spec = enc.spec
    pedal_rules(p)
    p.board = Board(outline=[(0, 0), (W, 0), (W, H), (0, H)])  # provisional; standoff needs a thickness
    hw_pot = HARDWARE[o.pot]
    near = spec.face_t + hw_pot.body_len
    far = near + p.board.thickness

    # --- panel layout (face coordinates) --------------------------------------------------------------
    v_fs = -Hc / 2 + 17.0
    fs_r = HARDWARE["footswitch"].body_r
    enc.holes.append(PanelHole.of("footswitch", "A", 0.0, v_fs, "FOOTSWITCH"))
    jack_hw, dc_hw = HARDWARE["jack"], HARDWARE["dc"]
    jacks = o.jacks
    if jacks == "auto":
        # top-mounted jacks only when their bodies fit between the board and the base plate
        z_top = min(spec.depth - jack_hw.body_r - 1.5, max(far + jack_hw.body_r + 3.0, spec.depth / 2))
        jacks = "top" if W >= 58 and z_top - jack_hw.body_r >= far + 0.5 else "side"
    if jacks == "top":
        z_j = min(spec.depth - jack_hw.body_r - 1.5, max(far + jack_hw.body_r + 3.0, spec.depth / 2))
        xj = min(W * 0.3, W / 2 - spec.corner_r - 8.0)
        for label, x in (("INPUT", xj), ("OUTPUT", -xj)):
            sx, sy = side_position(enc, "B", x, Hc / 2, z_j)
            enc.holes.append(PanelHole.of("jack", "B", sx, sy, label))
        z_dc = min(spec.depth - dc_hw.body_r - 1.5, z_j)
    else:
        v_j = v_fs + fs_r + jack_hw.body_r + 3.0
        z_j = spec.depth / 2 + 1.0
        # jacks from opposite walls would meet in narrow boxes: stagger them (input lower, as usual)
        stagger = 2 * jack_hw.body_r + 1.0 if Wc < 2 * jack_hw.body_len + 2.0 else 0.0
        for label, wall, u, v in (("INPUT", "E", Wc / 2, v_j), ("OUTPUT", "C", -Wc / 2, v_j + stagger)):
            sx, sy = side_position(enc, wall, u, v, z_j)
            enc.holes.append(PanelHole.of("jack", wall, sx, sy, label))
        z_dc = spec.depth - dc_hw.body_r - 1.5
    sx, sy = side_position(enc, "B", 0.0, Hc / 2, z_dc)
    enc.holes.append(PanelHole.of("dc", "B", sx, sy, "9V DC"))
    enc.holes.extend(o.extra_holes)

    # keep the board and the pot bodies clear of the side-wall hardware
    from .checks import _overlap, _side_body
    pcb_z, pot_z, parts_z = (near, far), (spec.face_t, near), (far, far + 12.0)
    v_top_board, v_top_pots = Hc / 2, Hc / 2 - hw_pot.body_r - 2.5
    v_bottom = v_fs + fs_r + 2.0
    part_keepouts = []
    for h in enc.holes:
        if h.face == "A":
            continue
        rect, zr = _side_body(enc, h)
        if h.face == "B":
            if _overlap(zr, pcb_z):
                v_top_board = min(v_top_board, rect.bounds[1] - 1.0)
            if _overlap(zr, pot_z):
                v_top_pots = min(v_top_pots, rect.bounds[1] - hw_pot.body_r - 1.0)
        elif _overlap(zr, pcb_z) or _overlap(zr, pot_z):
            v_bottom = max(v_bottom, rect.bounds[3] + 1.5)
        if _overlap(zr, parts_z):
            part_keepouts.append(enc.geom_to_board(rect.buffer(1.0)))
    lowest_ok = v_fs + fs_r + hw_pot.body_r + 2.0
    if v_top_pots < lowest_ok:  # tiny boxes: never push the knobs into the footswitch
        v_top_pots = min(lowest_ok, Hc / 2 - hw_pot.body_r - 2.5)
        notes.append("The DC socket and the knobs compete for the same space; move the DC socket to a side wall "
                     "or use 9 mm pots.")
    if v_top_board < Hc / 2:
        notes.append(f"The board stops {Hc / 2 - v_top_board:.0f} mm below the top wall so the jacks and DC socket "
                     "fit above it.")
    if o.led == "panel":
        enc.holes.append(PanelHole.of("bezel3", "A", 0.0, v_fs + fs_r + 8.0, "LED"))

    # --- board outline ------------------------------------------------------------------------------------
    outline = fit_outline(enc, v_top=v_top_board, v_bottom=v_bottom, clearance=0.8)
    if len(outline) < 3 or v_top_board - v_bottom < 20.0:
        outline = fit_outline(enc, v_bottom=v_fs + fs_r + 2.0, clearance=0.8)
        notes.append(f"The {spec.name} is too tight for this jack layout: the board now fills the space above the "
                     "footswitch. Review the enclosure checks and move the jacks in the Enclosure tab.")
    p.board = Board(outline=outline, layers=2, mask_color="Black", silk_color="White")
    set_enclosure(p, enc)

    # --- pots ---------------------------------------------------------------------------------------------
    positions = knob_layout(len(o.knobs), enc, o.pot, v_top=v_top_pots)
    for label, (u, v) in zip(o.knobs, positions):
        x, y = enc.face_to_board(u, v)
        c = Component(p.next_ref("RV"), pot_value(label), part("pot16" if o.pot == "pot" else "pot9"), x, y, 0.0,
                      enc.face_side)
        c.show_value = o.silk_values
        p.components.append(c)
        pin_y = max(pad.y for pad in c.footprint.pads)
        p.texts.append(Text(label.upper(), x, y + pin_y + 3.4, 1.3, "F.SilkS"))
        pins = unary_union([pad_geom(c, pad) for pad in c.footprint.pads])
        if not p.board.polygon().buffer(-0.5).contains(pins):
            notes.append(f"The {label} pot's pins fall outside the board: move it, enlarge the board or choose 9 mm pots"
                         f" (16 mm pots need about 26 mm between rows).")

    # --- LED on the board, pointing at the face -------------------------------------------------------------
    board_led = None
    if o.led in ("board3", "board5"):
        v_led = min(v_bottom + 6.0, positions[-1][1] - 14.0 if positions else v_bottom + 6.0)
        lx, ly = enc.face_to_board(0.0, v_led)
        board_led = Component(p.next_ref("D"), "Red", part("led3" if o.led == "board3" else "led5"), lx, ly, 0.0,
                              enc.face_side, {"1": "LED", "2": "LED_A"})
        p.components.append(board_led)

    # --- off-board wiring ------------------------------------------------------------------------------------
    if o.wire_pads:
        from ..library.gen_pedal import wire_pads
        wp = Component(p.next_ref("W"), "Off-board", wire_pads(["9V", "GND", "IN", "OUT", "LED"]), 0, 0, 0, "top",
                       {"9V": "9V", "GND": "GND", "IN": "IN", "OUT": "OUT", "LED": "LED"})
        wp.show_ref = False
        bx0, by0, bx1, by1 = p.board.bounds()
        region = box(bx0, by1 - 9.0, bx1, by1)
        if not pack_components(p, [wp], region, "top"):
            pack_components(p, [wp], None, "top")

    # --- circuit blocks ------------------------------------------------------------------------------------
    elco = _elco_for(enc, p)
    if elco != "elco":
        notes.append(f"Only {enc.free_depth(p):.1f} mm is free under the board in a {spec.name}: using 7 mm tall "
                     "electrolytics (or lay taller ones on their side).")
    blocks: list[BlockPart] = []
    if o.power:
        blocks += power_block(elco)
    if o.vref:
        blocks += vref_block(elco)
    if o.led != "none":
        led_parts = led_block(None)  # the LED itself is placed above (or on the panel)
        if board_led is not None:
            led_parts[0].nets = {"1": "V+", "2": "LED_A"}
        blocks += led_parts
    comps = block_components(p, blocks)
    for c in comps:
        c.show_value = o.silk_values and c.show_value
    region = p.board.polygon()
    if part_keepouts:
        region = region.difference(unary_union(part_keepouts))
    pack_components(p, comps, region, "top")
    unplaced = [c.ref for c in comps if c not in p.components]
    if unplaced:
        notes.append(f"No room for {', '.join(unplaced)}; add them from the Pedal menu once the board is larger.")

    # --- copper pour -----------------------------------------------------------------------------------------
    if o.pour:
        p.zones.append(Zone("B.Cu", "GND", list(p.board.outline), clearance=0.4, min_width=0.3))
        p.zones.append(Zone("F.Cu", "GND", list(p.board.outline), clearance=0.4, min_width=0.3, priority=0))
    return p, notes
