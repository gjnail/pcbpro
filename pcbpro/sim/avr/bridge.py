"""Microcontroller <-> circuit co-simulation.

The CPU runs ahead in short quanta (``SimRunner.advance``): it samples its input pins from the latest analog
solution, executes up to the end of the quantum and records every pin change at its exact cycle. The analog engine
then catches up, landing on each recorded pin change (``next_break``) and switching the pin's driver from there.
"""
from __future__ import annotations

import heapq
import re

from ..devices import Device, Resistor, stamp_emf, stamp_g
from .cpu import AVR
from .hexfile import HexError, parse_hex
from .parts import chip_by_name
from .periph import HIGH, HIZ, LOW, PULLUP, Pins

R_HIGH, R_LOW, R_PULLUP = 25.0, 20.0, 35e3


class McuDevice(Device):
    kind = "mcu"

    def __init__(self, uid: str, ref: str, chip, clock: float, tn: dict, hex_text: str | None,
                 eeprom: bytes | None = None, name: str = ""):
        self.uid, self.ref, self.chip = uid, ref, chip
        self.tn = tn
        self.gpio = [g for g in chip.gpio if g in tn]
        super().__init__([tn["VCC"], tn["GND"]] + [tn[g] for g in self.gpio], uid, name or ref)
        self.vcc, self.gnd = tn["VCC"], tn["GND"]
        self.reset_node = tn.get("RESET")
        self.cpu = AVR(chip, clock)
        self.pins = Pins(self.cpu, chip.gpio)
        self.periph = chip.setup(self.cpu, self.pins, self)
        self.adc = self.periph.get("adc")
        self.usart = self.periph.get("usart")
        if self.adc is not None:
            self.adc.sample = self._sample
        self.idx = [(self.pins.index[g], tn[g]) for g in self.gpio]
        self.drive = {i: HIZ for i, _ in self.idx}
        self.pending: list = []
        self._seq = 0
        self.x = None
        self.t_now = 0.0
        self.powered = False
        self.held = False
        self.anchor_t = 0.0
        self.anchor_cyc = 0
        self.firmware = ""
        self.error = ""
        self.watchers: dict[int, list] = {}
        self.serial_buf = ""
        if eeprom:
            self.cpu.eeprom[:len(eeprom)] = eeprom[:len(self.cpu.eeprom)]
        if hex_text:
            try:
                self.cpu.load(parse_hex(hex_text, max(chip.flash_size, 1 << 17))[:chip.flash_size])
                self.firmware = "loaded"
            except HexError as e:
                self.error = f"firmware: {e}"

    # ------------------------------------------------------------------ circuit side
    def stamp_step(self, A, b, t, h, mode):
        if not self.powered:
            return
        vcc, gnd = self.vcc, self.gnd
        for i, n in self.idx:
            st = self.drive[i]
            if st == HIGH:
                stamp_emf(A, b, vcc, n, 1.0 / R_HIGH, 0.0)
            elif st == LOW:
                stamp_emf(A, b, n, gnd, 1.0 / R_LOW, 0.0)
            elif st == PULLUP:
                stamp_g(A, vcc, n, 1.0 / R_PULLUP)

    def next_break(self, t):
        if not self.pending:
            return None
        te = self.pending[0][0]
        return te if te > t + 1e-12 else t + 1e-9

    def accept(self, x, t, h, mode):
        self.x = x
        self.t_now = t
        while self.pending and self.pending[0][0] <= t + 1e-12:
            te, _, pin, st = heapq.heappop(self.pending)
            self.drive[pin] = st
            for cb in self.watchers.get(pin, ()):
                cb(te, st)

    def currents(self, x):
        cur = [0.0] * len(self.nodes)
        if not self.powered:
            return cur
        for k, (i, n) in enumerate(self.idx):
            st = self.drive[i]
            if st == HIGH:
                c = (x[self.vcc] - x[n]) / R_HIGH
            elif st == LOW:
                c = -(x[n] - x[self.gnd]) / R_LOW
            elif st == PULLUP:
                c = (x[self.vcc] - x[n]) / R_PULLUP
            else:
                continue
            cur[0] += c if st != LOW else 0.0
            cur[1] += -c if st == LOW else 0.0
            cur[2 + k] -= c
        return cur

    def pin_current(self, name: str) -> float:
        """Current sourced by a pin (negative when sinking)."""
        if self.x is None or name not in self.tn or not self.powered:
            return 0.0
        i = self.pins.index[name]
        n = self.tn[name]
        st = self.drive.get(i, HIZ)
        x = self.x
        if st == HIGH:
            return float((x[self.vcc] - x[n]) / R_HIGH)
        if st == LOW:
            return float(-(x[n] - x[self.gnd]) / R_LOW)
        return 0.0

    def _sample(self, name: str) -> float:
        x = self.x
        if x is None:
            return 0.0
        g = float(x[self.gnd])
        if name in ("VCC", "AVCC"):
            n = self.tn.get("AVCC", self.vcc)
            return float(x[n]) - g
        n = self.tn.get(name)
        return float(x[n]) - g if n is not None else 0.0

    # ------------------------------------------------------------------ CPU side
    def _t(self, cyc: int) -> float:
        return self.anchor_t + (cyc - self.anchor_cyc) / self.cpu.clock

    def _all_hiz(self):
        self.pending.clear()
        for i in self.drive:
            self.drive[i] = HIZ

    def watchdog_reset(self, reason: str) -> None:
        self.cpu.reset()
        self.pins.reset()

    def run_to(self, t_end: float) -> None:
        x = self.x
        if x is None:
            return
        vcc = float(x[self.vcc] - x[self.gnd])
        if vcc < 1.8:
            if self.powered:
                self.powered = False
                self._all_hiz()
            return
        if self.reset_node is not None and float(x[self.reset_node] - x[self.gnd]) < 0.3 * vcc:
            if not self.held:
                self.held = True
                self._all_hiz()
                self.cpu.reset()
                self.pins.reset()
                self.pins.events.clear()
            self.powered = True
            return
        if not self.powered or self.held:
            self.powered = True
            self.held = False
            self.cpu.reset()
            self.pins.events.clear()
            self.anchor_t = self.t_now
            self.anchor_cyc = self.cpu.cycles
        g = float(x[self.gnd])
        cyc = self.cpu.cycles
        for i, n in self.idx:
            v = float(x[n]) - g
            lvl = self.pins.level[i]
            new = 1 if v > (0.45 if lvl else 0.55) * vcc else 0
            if new != lvl:
                self.pins.set_input(i, new, cyc)
        if not self.cpu.loaded:
            return
        target = self.anchor_cyc + int((t_end - self.anchor_t) * self.cpu.clock)
        if target > self.cpu.cycles:
            self.cpu.run(target)
        if self.pins.events:
            for c, pin, st in self.pins.events:
                if pin in self.drive:
                    self._seq += 1
                    heapq.heappush(self.pending, (self._t(c), self._seq, pin, st))
            self.pins.events.clear()

    def attach(self, runner) -> None:
        pass

    def serial_in(self, text: str) -> None:
        if self.usart is not None:
            self.usart.receive(text.encode("latin-1", errors="replace"))

    def serial_out(self) -> str:
        if self.usart is None or not self.usart.out:
            return ""
        text = bytes(self.usart.out).decode("latin-1")
        self.usart.out.clear()
        return text

    def status(self) -> str:
        if self.error:
            return self.error
        if not self.cpu.loaded:
            return "no firmware loaded: pins are inputs"
        if not self.powered:
            return "unpowered"
        if self.held:
            return "held in reset"
        state = "sleeping" if self.cpu.sleeping else "running"
        return f"{state} · {self.cpu.clock / 1e6:g} MHz · {self.cpu.cycles / self.cpu.clock:.3f} s of code"

    def observe(self, x):
        return {"p": self.power(x)}


# --------------------------------------------------------------------------- netlist builder

def _crystal_clock(x, pads: list[str]) -> float | None:
    """Frequency of a crystal / resonator wired to the given MCU pads."""
    nets = {x.c.pad_nets.get(p) for p in pads} - {None}
    if not nets:
        return None
    from ..models import resolve
    from ..units import parse_value
    for comp in x.ck.project.components:
        if comp is x.c:
            continue
        if set(comp.pad_nets.values()) & nets:
            r = resolve(comp)
            if r.kind == "crystal":
                return parse_value(comp.value, None) or r.params.get("f")
    return None


def build(x) -> None:
    from ..netlist import _diode, _led
    from ..devices import VoltageSource
    from ..ics import Regulator
    res = x.info.res
    p = res.params
    chip = chip_by_name(p["chip"])
    cfg = ((x.ck.project.sim or {}).get("mcu") or {}).get(x.c.uid, {})
    module = p.get("module")
    tn: dict = {}
    if module:
        vcc = x.T("5V")
        tn["VCC"] = tn["AVCC"] = vcc
        tn["RESET"] = x.T("RESET")
        clock = p.get("clock", 16e6)
        xtal = True
    else:
        vcc = x.T("VCC")
        tn["VCC"] = vcc
        if x.has("AVCC"):
            tn["AVCC"] = x.T("AVCC")
        clock = None
        xtal = False
        if chip.xtal_pins and all(x.has(pn) for pn in chip.xtal_pins):
            pads = [pd for pn in chip.xtal_pins for pd in res.pins[pn]]
            f = _crystal_clock(x, pads)
            if f:
                clock, xtal = f, True
        if clock is None:
            clock = 8e6 if chip.xtal_pins else chip.default_clock
        if x.has(chip.reset_pin):
            tn["RESET"] = x.T(chip.reset_pin)
    gnd = x.T("GND")
    tn["GND"] = gnd
    if x.has("AREF"):
        tn["AREF"] = x.T("AREF")
    for name in chip.gpio:
        if name == chip.reset_pin or (xtal and name in chip.xtal_pins):
            continue
        if x.has(name):
            tn[name] = x.T(name)
    for name in ("ADC6", "ADC7"):
        if x.has(name):
            tn[name] = x.T(name)
    clock = float(cfg.get("clock") or clock)
    dev = McuDevice(x.c.uid, x.c.ref, chip, clock, tn, cfg.get("hex"), name=x.c.ref)
    x.add(dev)
    x.ck.mcus.append(dev)
    res.params["clock"] = clock
    for name in chip.gpio:
        n = tn.get(name)
        if n is None or name == chip.reset_pin:
            continue
        _diode(x, n, vcc, dict(is_=1e-14, n=1.0, rs=10.0, imax=0.04))
        _diode(x, gnd, n, dict(is_=1e-14, n=1.0, rs=10.0, imax=0.04))
    if "RESET" in tn:
        x.add(Resistor(vcc, tn["RESET"], 40e3, name=f"{x.c.ref} reset pull-up"))
    x.add(Resistor(vcc, gnd, chip.supply_ohms * (16e6 / max(clock, 1e6)) ** 0.5, name=f"{x.c.ref} supply"))
    if module:
        _module_extras(x, dev, module, p, vcc, gnd)
    x.info.note = dev.status() if not cfg.get("hex") else f"firmware {cfg.get('name', '')}"


def _module_extras(x, dev, module, p, vcc, gnd):
    """On-board parts of an Arduino module: regulator, LEDs, reset pull-up, USB power."""
    from ..netlist import _diode, _led
    from ..devices import VoltageSource
    from ..ics import Regulator
    vreg = p.get("vreg", 5.0)
    if x.has("VIN"):
        if module == "nano":
            x.add(Regulator(x.T("VIN"), gnd, vcc, vset=vreg, vdo=1.1, ilim=0.8, iq=5e-3, name=f"{x.c.ref} 5V reg"))
        else:
            x.add(Regulator(x.T("VIN"), gnd, vcc, vset=vreg, vdo=0.17, ilim=0.15, iq=0.1e-3,
                            name=f"{x.c.ref} regulator"))
    if module == "nano" and x.has("3V3"):
        x.add(Regulator(vcc, gnd, x.T("3V3"), vset=3.3, vdo=0.3, ilim=0.05, iq=0.1e-3, name=f"{x.c.ref} 3V3"))
    x.add(Resistor(vcc, dev.tn["RESET"], 10e3, name=f"{x.c.ref} reset pull-up"))
    led_n = x.internal("L")
    pb5 = dev.tn.get("PB5")
    if pb5 is not None:
        x.add(Resistor(pb5, led_n, 1e3, name=f"{x.c.ref} LED L resistor"))
        _led(x, led_n, gnd, "orange", "L")
    on_n = x.internal("ON")
    x.add(Resistor(vcc, on_n, 1e3, name=f"{x.c.ref} power LED resistor"))
    _led(x, on_n, gnd, "green", "ON")
    p["led_pos"] = {"L": (3.0, -14.0), "ON": (-3.0, -14.0)}
    if module == "nano":
        usb = x.internal("usb")
        mid = x.internal("vbus")
        src = x.add(VoltageSource(usb, gnd, 5.0, ramp=1e-4, name=f"{x.c.ref} USB"))
        x.add(Resistor(usb, mid, 0.3, name=f"{x.c.ref} USB cable"))
        _diode(x, mid, vcc, dict(is_=3e-6, n=1.1, rs=0.1, imax=0.5))
        x.control("plug", "usb", f"{x.c.ref} USB cable", [src], 1, options=["unplugged", "plugged in"])


# --------------------------------------------------------------------------- addressable LEDs (WS2812)

class WS2812:
    """Decodes the WS2812 one-wire protocol from the exact edge times of the MCU pin driving DIN and passes the
    remaining bits down the chain (DOUT -> DIN)."""

    def __init__(self, n_leds: int):
        self.n = n_leds
        self.colors = [(0, 0, 0)] * n_leds
        self.bits: list[int] = []
        self.rise = None
        self.last_edge = 0.0
        self.shadow: list = []

    def edge(self, t: float, state: int) -> None:
        if state == HIGH:
            if self.last_edge and t - self.last_edge > 50e-6:  # reset: latch
                self._latch()
            self.rise = t
        elif self.rise is not None:
            width = t - self.rise
            self.bits.append(1 if width > 0.6e-6 else 0)
            self.rise = None
            if len(self.bits) >= 24 * self.n:
                self._latch()
        self.last_edge = t

    def _latch(self) -> None:
        bits = self.bits
        out = []
        for i in range(min(self.n, len(bits) // 24)):
            b = bits[24 * i:24 * i + 24]
            val = [int("".join(map(str, b[k:k + 8])), 2) for k in (0, 8, 16)]
            g, r, bl = val
            out.append((r, g, bl))
        for i, c in enumerate(out):
            self.colors[i] = c
        self.bits = []


class VirtualLED:
    """LED whose light comes from decoded data instead of a diode current (WS2812)."""
    nonlinear = False

    def __init__(self, chain: WS2812, index: int):
        self.chain, self.index = chain, index
        self.nodes = [0, 0]
        self.color = "#000000"

    def current(self, v: float) -> float:
        r, g, b = self.chain.colors[self.index]
        m = max(r, g, b)
        return 0.02 * m / 255.0

    @property
    def dyn_color(self) -> str:
        r, g, b = self.chain.colors[self.index]
        m = max(r, g, b, 1)
        return f"#{int(r * 255 / m):02x}{int(g * 255 / m):02x}{int(b * 255 / m):02x}"


def attach_addressable(x) -> None:
    """Register a WS2812 for linking once every part is built (see link_addressable)."""
    x.ck.__dict__.setdefault("ws2812", []).append((x.c, x.info, x.T("DIN"), x.T("DOUT")))


def link_addressable(ck) -> None:
    """Chain WS2812s DIN <- DOUT and attach each chain to the MCU pin that drives its first DIN."""
    items = ck.__dict__.get("ws2812", [])
    if not items:
        return
    by_din = {din: (c, info, din, dout) for c, info, din, dout in items}
    douts = {dout for *_, dout in items}
    starts = [it for it in items if it[2] not in douts]
    for start in starts:
        chain_items = []
        cur = start
        seen = set()
        while cur is not None and id(cur) not in seen:
            seen.add(id(cur))
            chain_items.append(cur)
            cur = by_din.get(cur[3])
        chain = WS2812(len(chain_items))
        for i, (c, info, din, dout) in enumerate(chain_items):
            v = VirtualLED(chain, i)
            info.leds.append((v, "#ffffff", f"{c.ref}"))
        din = start[2]
        for m in ck.mcus:
            for idx, n in m.idx:
                if n == din:
                    m.watchers.setdefault(idx, []).append(chain.edge)
