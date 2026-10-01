"""AVR peripherals, computed lazily from the CPU cycle counter.

Each peripheral implements reset(), update(cycle) (bring its state up to that cycle, setting flags and recording
pin changes at their exact cycles) and next_event() (the next cycle at which something observable happens).
Pin drive states: 0 = low, 1 = high, 2 = input with pull-up, 3 = high impedance.
"""
from __future__ import annotations

from .cpu import BIG

LOW, HIGH, PULLUP, HIZ = 0, 1, 2, 3


class FlagReg:
    """Interrupt flag register: bits are set by hardware and cleared by writing a one."""

    def __init__(self, cpu, addr: int):
        self.cpu = cpu
        self.v = 0
        self.readers: list = []  # peripherals to update before a read
        cpu.io_r[addr] = self._read
        cpu.io_w[addr] = self._write

    def _read(self, a):
        for p in self.readers:
            p.update(self.cpu.cycles)
        return self.v

    def _write(self, a, v, m=0xFF):
        self.v &= ~(v & m) & 0xFF
        self.cpu.kick()

    def set(self, bit: int) -> None:
        if not self.v & bit:
            self.v |= bit
            self.cpu.kick()

    def reset(self):
        self.v = 0


# --------------------------------------------------------------------------- pins

class Pins:
    def __init__(self, cpu, names: list[str]):
        self.cpu = cpu
        self.names = names
        self.index = {n: i for i, n in enumerate(names)}
        n = len(names)
        self.out = [HIZ] * n
        self.level = [0] * n
        self.override: dict[int, int] = {}
        self.force_out: set = set()
        self.ports: dict[str, Port] = {}
        self.events: list = []  # (cycle, pin, state)
        self.on_change: list = []  # callbacks(pin, level, cycle)

    def reset(self):
        for i in range(len(self.out)):
            if self.out[i] != HIZ:
                self.out[i] = HIZ
                self.events.append((self.cpu.cycles, i, HIZ))
        self.override.clear()
        self.force_out.clear()

    def state_of(self, pin: int) -> int:
        name = self.names[pin]
        port = self.ports.get(name[1])
        bit = int(name[2:])
        ddr = (port.ddr >> bit) & 1 if port else 0
        prt = (port.port >> bit) & 1 if port else 0
        if pin in self.force_out or (ddr and pin in self.override):
            return self.override.get(pin, prt)
        if ddr:
            return prt
        return PULLUP if prt else HIZ

    def recompute(self, pin: int, cyc: int) -> None:
        st = self.state_of(pin)
        if st != self.out[pin]:
            self.out[pin] = st
            self.events.append((cyc, pin, st))

    def set_override(self, pin: int, level: int, cyc: int, force: bool = False) -> None:
        if pin is None:
            return
        self.override[pin] = level
        if force:
            self.force_out.add(pin)
        self.recompute(pin, cyc)

    def clear_override(self, pin: int, cyc: int) -> None:
        if pin is None:
            return
        self.override.pop(pin, None)
        self.force_out.discard(pin)
        self.recompute(pin, cyc)

    def set_input(self, pin: int, level: int, cyc: int) -> None:
        if self.level[pin] != level:
            self.level[pin] = level
            for cb in self.on_change:
                cb(pin, level, cyc)

    def read_bit(self, pin: int) -> int:
        st = self.out[pin]
        if st in (LOW, HIGH):
            return st
        return self.level[pin]


class Port:
    def __init__(self, cpu, pins: Pins, letter: str, a_pin: int, a_ddr: int, a_port: int, nbits: int = 8):
        self.cpu, self.pins, self.letter, self.nbits = cpu, pins, letter, nbits
        self.ddr = 0
        self.port = 0
        self.ids = [pins.index.get(f"P{letter}{b}") for b in range(8)]
        pins.ports[letter] = self
        cpu.io_r[a_pin] = self._r_pin
        cpu.io_w[a_pin] = self._w_pin
        cpu.io_r[a_ddr] = lambda a: self.ddr
        cpu.io_w[a_ddr] = self._w_ddr
        cpu.io_r[a_port] = lambda a: self.port
        cpu.io_w[a_port] = self._w_port

    def reset(self):
        self.ddr = 0
        self.port = 0

    def _changed(self, mask: int) -> None:
        cyc = self.cpu.cycles
        for b in range(8):
            if mask >> b & 1 and self.ids[b] is not None:
                self.pins.recompute(self.ids[b], cyc)

    def _r_pin(self, a):
        v = 0
        for b in range(self.nbits):
            pid = self.ids[b]
            if pid is not None and self.pins.read_bit(pid):
                v |= 1 << b
        return v

    def _w_pin(self, a, v, m=0xFF):  # writing a one to PINx toggles PORTx
        t = v & m
        if t:
            self.port ^= t
            self._changed(t)

    def _w_ddr(self, a, v, m=0xFF):
        new = (self.ddr & ~m | v & m) & 0xFF
        ch = new ^ self.ddr
        self.ddr = new
        if ch:
            self._changed(ch)

    def _w_port(self, a, v, m=0xFF):
        new = (self.port & ~m | v & m) & 0xFF
        ch = new ^ self.port
        self.port = new
        if ch:
            self._changed(ch)

    def update(self, cyc):
        pass

    def next_event(self):
        return BIG


# --------------------------------------------------------------------------- timers

NORMAL, CTC, FAST, PC = "normal", "ctc", "fast", "pc"


class Timer:
    """8- or 16-bit timer/counter. ``cfg(timer)`` decodes its mode registers into (kind, top, prescale, comA,
    comB, icr_top). Registers live in ``self.r``; ``regs`` maps register names to addresses ((lo, hi) for 16-bit)."""

    def __init__(self, cpu, pins: Pins, name: str, bits: int, regs: dict, cfg, tifr: FlagReg, timsk: int,
                 bits_flags: dict, vectors: dict, oc_pins: dict):
        self.cpu, self.pins, self.name, self.bits = cpu, pins, name, bits
        self.max = (1 << bits) - 1
        self.cfg = cfg
        self.tifr, self.timsk = tifr, timsk
        self.fb = bits_flags  # {"ovf": bit, "a": bit, "b": bit, "capt": bit}
        self.oc_pins = {k: pins.index.get(v) if v else None for k, v in oc_pins.items()}
        self.r: dict[str, int] = {}
        self.regs = regs
        self.temp = 0
        tifr.readers.append(self)
        for name_, addr in regs.items():
            if isinstance(addr, tuple):
                lo, hi = addr
                cpu.io_r[lo] = (lambda a, n=name_: self._r16(n, False))
                cpu.io_r[hi] = (lambda a, n=name_: self._r16(n, True))
                cpu.io_w[lo] = (lambda a, v, m=0xFF, n=name_: self._w16(n, v, False))
                cpu.io_w[hi] = (lambda a, v, m=0xFF, n=name_: self._w16(n, v, True))
            else:
                cpu.io_r[addr] = (lambda a, n=name_: self._r8(n))
                cpu.io_w[addr] = (lambda a, v, m=0xFF, n=name_: self._w8(n, v, m))
        for key, vec in vectors.items():
            bit = self.fb[key]
            cpu.add_irq(vec, (lambda b=bit: (self.tifr.v & b) and (cpu.data[self.timsk] & b)),
                        (lambda b=bit: setattr(self.tifr, "v", self.tifr.v & ~b)))
        self.reset()

    def reset(self):
        for n in self.regs:
            self.r[n] = 0
        self.pos = 0
        self.t_cyc = self.cpu.cycles
        self.oc = {"a": 0, "b": 0}
        self.kind, self.top, self.p, self.com = NORMAL, self.max, 0, {"a": 0, "b": 0}
        self.icr_top = False
        self._configure(self.cpu.cycles)

    # ------------------------------------------------------------------ registers
    def _r8(self, n):
        if n == "tcnt":
            self.update(self.cpu.cycles)
            return self.count() & 0xFF
        return self.r[n]

    def _w8(self, n, v, m):
        cyc = self.cpu.cycles
        self.update(cyc)
        if n == "tcnt":
            self._set_count(v & 0xFF)
        else:
            self.r[n] = (self.r[n] & ~m | v & m) & 0xFF
        self._configure(cyc)
        self.cpu.kick()

    def _r16(self, n, hi):
        if hi:
            return self.temp
        if n == "tcnt":
            self.update(self.cpu.cycles)
            v = self.count()
        else:
            v = self.r[n]
        self.temp = (v >> 8) & 0xFF
        return v & 0xFF

    def _w16(self, n, v, hi):
        if hi:
            self.temp = v & 0xFF
            return
        cyc = self.cpu.cycles
        self.update(cyc)
        val = (self.temp << 8) | (v & 0xFF)
        if n == "tcnt":
            self._set_count(val)
        else:
            self.r[n] = val
        self._configure(cyc)
        self.cpu.kick()

    # ------------------------------------------------------------------ counting
    def _length(self) -> int:
        return self.top + 1 if self.kind != PC else max(2 * self.top, 1)

    def count(self) -> int:
        if self.kind == PC and self.pos > self.top:
            return self._length() - self.pos
        return self.pos

    def _set_count(self, c: int) -> None:
        c = min(c, self.max)
        if self.kind == PC and self.pos > self.top:
            self.pos = self._length() - min(c, self.top)
        else:
            self.pos = c

    def _configure(self, cyc: int) -> None:
        kind, top, p, coma, comb, icr_top = self.cfg(self)
        top = max(int(top), 1)
        if (kind, top) != (self.kind, self.top):
            c = self.count()
            self.kind, self.top = kind, top
            self.pos = min(c, top) if kind != PC else min(c, top)
        self.icr_top = icr_top
        if p != self.p:
            self.t_cyc = cyc
            self.p = p
        for ch, com in (("a", coma), ("b", comb)):
            pin = self.oc_pins.get(ch)
            if com != self.com[ch]:
                self.com[ch] = com
                if com:
                    if self.kind in (FAST, PC):
                        self.oc[ch] = self._pwm_level(ch)
                    self.pins.set_override(pin, self.oc[ch], cyc)
                else:
                    self.pins.clear_override(pin, cyc)
            elif com and self.kind in (FAST, PC) and self._constant(ch) is not None:
                self._set_oc(ch, self._constant(ch), cyc)

    def _ocr(self, ch: str) -> int:
        return self.r.get("ocr" + ch, 0)

    def _constant(self, ch):
        """PWM output stuck at a rail (OCR at BOTTOM or TOP)."""
        ocr = self._ocr(ch)
        com = self.com[ch]
        if self.kind == PC:
            if ocr >= self.top:
                return 1 if com == 2 else 0
            if ocr == 0:
                return 0 if com == 2 else 1
        if self.kind == FAST and ocr >= self.top:
            return 1 if com == 2 else 0
        return None

    def _pwm_level(self, ch):
        const = self._constant(ch)
        if const is not None:
            return const
        c = self.count()
        on = c < self._ocr(ch)
        if self.kind == PC:
            on = c < self._ocr(ch)
        return int(on) if self.com[ch] == 2 else int(not on)

    def _set_oc(self, ch, level, cyc):
        if self.oc[ch] != level:
            self.oc[ch] = level
            if self.com[ch]:
                self.pins.set_override(self.oc_pins.get(ch), level, cyc)

    def _events(self):
        """(position, tag) pairs in one counting period."""
        L = self._length()
        ev = [(0, "bot")]
        if self.kind == PC:
            ev.append((self.top, "top"))
            for ch in ("a", "b"):
                o = self._ocr(ch)
                if 0 < o < self.top:
                    ev.append((o, ch + "u"))
                    ev.append((L - o, ch + "d"))
                elif o == self.top:
                    ev.append((self.top, ch + "u"))
        else:
            for ch in ("a", "b"):
                o = self._ocr(ch)
                if o <= self.top:
                    ev.append((o, ch))
            if self.icr_top:
                ev.append((self.top, "icr"))
        return ev

    def _next(self, relevant_only=False):
        L = self._length()
        best, tags = None, []
        for pos, tag in self._events():
            if relevant_only and not self._relevant(tag):
                continue
            d = ((pos - self.pos - 1) % L) + 1
            if best is None or d < best:
                best, tags = d, [tag]
            elif d == best:
                tags.append(tag)
        return best, tags

    def _relevant(self, tag: str) -> bool:
        ch = tag[0]
        if tag in ("bot", "top"):
            if tag == "bot" and not (self.tifr.v & self.fb["ovf"]):
                return self.kind != CTC or self.top == self.max
            return self.kind == FAST and any(self.com[c] and self._constant(c) is None for c in ("a", "b"))
        if tag == "icr":
            return "capt" in self.fb and not (self.tifr.v & self.fb["capt"])
        bit = self.fb.get(ch, 0)
        if bit and not (self.tifr.v & bit):
            return True
        return bool(self.com.get(ch)) and (self.kind in (NORMAL, CTC) or self._constant(ch) is None)

    def _apply(self, tags, cyc):
        for tag in tags:
            if tag == "bot":
                if self.kind != CTC or self.top == self.max:
                    self.tifr.set(self.fb["ovf"])
                if self.kind == FAST:
                    for ch in ("a", "b"):
                        if self.com[ch] in (2, 3) and self._constant(ch) is None:
                            self._set_oc(ch, 1 if self.com[ch] == 2 else 0, cyc)
                if self.kind == CTC and self.top == self.max:
                    pass
            elif tag == "top":
                continue
            elif tag == "icr":
                if "capt" in self.fb:
                    self.tifr.set(self.fb["capt"])
            else:
                ch = tag[0]
                self.tifr.set(self.fb[ch])
                com = self.com[ch]
                if not com:
                    continue
                if self.kind in (NORMAL, CTC):
                    lvl = {1: 1 - self.oc[ch], 2: 0, 3: 1}[com]
                    self._set_oc(ch, lvl, cyc)
                elif self.kind == FAST:
                    if self._constant(ch) is None and com in (2, 3):
                        self._set_oc(ch, 0 if com == 2 else 1, cyc)
                else:  # phase correct
                    if self._constant(ch) is None and com in (2, 3):
                        up = tag.endswith("u")
                        self._set_oc(ch, (0 if up else 1) if com == 2 else (1 if up else 0), cyc)

    def update(self, cyc: int) -> None:
        if self.p <= 0:
            self.t_cyc = cyc
            return
        avail = (cyc - self.t_cyc) // self.p
        L = self._length()
        while avail > 0:
            d, tags = self._next()
            if d is None or d > avail:
                self.pos = (self.pos + avail) % L
                self.t_cyc += avail * self.p
                return
            self.pos = (self.pos + d) % L
            self.t_cyc += d * self.p
            avail -= d
            self._apply(tags, self.t_cyc)

    def next_event(self) -> int:
        if self.p <= 0:
            return BIG
        d, _ = self._next(relevant_only=True)
        if d is None:
            return BIG
        return self.t_cyc + d * self.p


def cfg_8bit(prescalers):
    """Mode decoder for the ATmega / ATtiny 8-bit timers (TCCRxA / TCCRxB)."""
    def cfg(t):
        a, b = t.r.get("tccra", 0), t.r.get("tccrb", 0)
        wgm = (a & 3) | ((b >> 1) & 4)
        kind, top = {0: (NORMAL, 0xFF), 1: (PC, 0xFF), 2: (CTC, t.r.get("ocra", 0)), 3: (FAST, 0xFF),
                     5: (PC, t.r.get("ocra", 0)), 7: (FAST, t.r.get("ocra", 0))}.get(wgm, (NORMAL, 0xFF))
        p = prescalers[b & 7]
        coma, comb = (a >> 6) & 3, (a >> 4) & 3
        if kind == FAST and coma == 1:
            coma = 1 if wgm == 7 else 0
        if kind == FAST and comb == 1:
            comb = 0
        if kind == PC and coma == 1:
            coma = 1 if wgm == 5 else 0
        return kind, top, p, coma, comb, False
    return cfg


def cfg_16bit(prescalers):
    def cfg(t):
        a, b = t.r.get("tccra", 0), t.r.get("tccrb", 0)
        wgm = (a & 3) | ((b >> 1) & 0xC)
        ocra, icr = t.r.get("ocra", 0), t.r.get("icr", 0)
        table = {0: (NORMAL, 0xFFFF, False), 1: (PC, 0xFF, False), 2: (PC, 0x1FF, False), 3: (PC, 0x3FF, False),
                 4: (CTC, ocra, False), 5: (FAST, 0xFF, False), 6: (FAST, 0x1FF, False), 7: (FAST, 0x3FF, False),
                 8: (PC, icr, True), 9: (PC, ocra, False), 10: (PC, icr, True), 11: (PC, ocra, False),
                 12: (CTC, icr, True), 14: (FAST, icr, True), 15: (FAST, ocra, False)}
        kind, top, icr_top = table.get(wgm, (NORMAL, 0xFFFF, False))
        p = prescalers[b & 7]
        coma, comb = (a >> 6) & 3, (a >> 4) & 3
        if kind in (FAST, PC) and coma == 1:
            coma = 1 if wgm in (9, 11, 15) else 0
        if kind in (FAST, PC) and comb == 1:
            comb = 0
        return kind, top, p, coma, comb, icr_top
    return cfg


def cfg_tiny85_t1(t):
    """ATtiny85 Timer1: TCCR1 (CTC1, PWM1A, COM1A, CS1) + GTCCR (PWM1B, COM1B); TOP = OCR1C in CTC / PWM."""
    tccr1, gtccr = t.r.get("tccr1", 0), t.r.get("gtccr", 0)
    cs = tccr1 & 0xF
    p = 0 if cs == 0 else (1 << (cs - 1))
    pwm = (tccr1 & 0x40) or (gtccr & 0x40)
    ctc = tccr1 & 0x80
    top = t.r.get("ocr1c", 0xFF) if (ctc or pwm) else 0xFF
    kind = FAST if pwm else (CTC if ctc else NORMAL)
    coma = (tccr1 >> 4) & 3
    comb = (gtccr >> 4) & 3
    if kind == FAST:
        coma = 2 if coma in (1, 2) else coma
        comb = 2 if comb in (1, 2) else comb
    return kind, top, p, coma, comb, False


# --------------------------------------------------------------------------- USART

class USART:
    def __init__(self, cpu, pins: Pins, a: dict, vectors: dict, tx_pin: str, rx_pin: str):
        self.cpu, self.pins = cpu, pins
        self.a = a
        self.tx_pin = pins.index.get(tx_pin)
        self.rx_pin = pins.index.get(rx_pin)
        self.out = []
        self.rx_queue: list[int] = []
        cpu.io_r[a["udr"]] = self._r_udr
        cpu.io_w[a["udr"]] = self._w_udr
        cpu.io_r[a["ucsra"]] = self._r_a
        cpu.io_w[a["ucsra"]] = self._w_a
        cpu.io_r[a["ucsrb"]] = lambda x: self.b
        cpu.io_w[a["ucsrb"]] = self._w_b
        for k in ("ucsrc", "ubrrl", "ubrrh"):
            cpu.io_r[a[k]] = (lambda x, k=k: self.r[k])
            cpu.io_w[a[k]] = (lambda x, v, m=0xFF, k=k: self._w_reg(k, v))
        cpu.add_irq(vectors["rx"], lambda: (self.flags & 0x80) and (self.b & 0x80), lambda: None)
        cpu.add_irq(vectors["udre"], lambda: (self.flags & 0x20) and (self.b & 0x20), lambda: None)
        cpu.add_irq(vectors["tx"], lambda: (self.flags & 0x40) and (self.b & 0x40),
                    lambda: setattr(self, "flags", self.flags & ~0x40))
        self.reset()

    def reset(self):
        self.flags = 0x20  # UDRE
        self.u2x = 0
        self.b = 0
        self.r = {"ucsrc": 0x06, "ubrrl": 0, "ubrrh": 0}
        self.tx_shift = None
        self.tx_buf = None
        self.tx_end = BIG
        self.rx_fifo: list[int] = []
        self.rx_end = BIG

    def bit_cycles(self) -> int:
        ubrr = ((self.r["ubrrh"] & 0xF) << 8) | self.r["ubrrl"]
        return (8 if self.u2x else 16) * (ubrr + 1)

    def baud(self) -> float:
        return self.cpu.clock / self.bit_cycles()

    def _w_reg(self, k, v):
        self.r[k] = v & 0xFF

    def _r_a(self, x):
        self.update(self.cpu.cycles)
        return self.flags | self.u2x << 1

    def _w_a(self, x, v, m=0xFF):
        if v & m & 0x40:
            self.flags &= ~0x40
        self.u2x = (v >> 1) & 1
        self.cpu.kick()

    def _w_b(self, x, v, m=0xFF):
        old = self.b
        self.b = (self.b & ~m | v & m) & 0xFF
        cyc = self.cpu.cycles
        if (self.b ^ old) & 0x08:
            if self.b & 0x08:
                self.pins.set_override(self.tx_pin, 1, cyc, force=True)
            else:
                self.pins.clear_override(self.tx_pin, cyc)
        if self.b & 0x10 and self.rx_queue and self.rx_end == BIG:
            self.rx_end = cyc + 10 * self.bit_cycles()
        self.cpu.kick()

    def _r_udr(self, x):
        self.update(self.cpu.cycles)
        v = self.rx_fifo.pop(0) if self.rx_fifo else 0
        if not self.rx_fifo:
            self.flags &= ~0x80
        return v

    def _w_udr(self, x, v, m=0xFF):
        cyc = self.cpu.cycles
        self.update(cyc)
        if not self.b & 0x08:
            return
        if self.tx_shift is None:
            self._start_tx(v & 0xFF, cyc)
        else:
            self.tx_buf = v & 0xFF
            self.flags &= ~0x20
        self.cpu.kick()

    def _start_tx(self, byte: int, cyc: int) -> None:
        bc = self.bit_cycles()
        self.tx_shift = byte
        self.tx_end = cyc + 10 * bc
        self.flags |= 0x20
        if self.tx_pin is not None:
            level = 1
            bits = [0] + [(byte >> i) & 1 for i in range(8)] + [1]
            for i, b in enumerate(bits):
                if b != level:
                    self.pins.set_override(self.tx_pin, b, cyc + i * bc, force=True)
                    level = b

    def receive(self, data: bytes) -> None:
        self.rx_queue.extend(data)
        if self.b & 0x10 and self.rx_end == BIG:
            self.rx_end = self.cpu.cycles + 10 * self.bit_cycles()
        self.cpu.kick()

    def update(self, cyc: int) -> None:
        while self.tx_end <= cyc:
            self.out.append(self.tx_shift)
            end = self.tx_end
            self.tx_shift = None
            self.tx_end = BIG
            if self.tx_buf is not None:
                b, self.tx_buf = self.tx_buf, None
                self._start_tx(b, end)
            else:
                self.flags |= 0x40
        while self.rx_end <= cyc:
            if self.rx_queue:
                if len(self.rx_fifo) < 2:
                    self.rx_fifo.append(self.rx_queue.pop(0))
                else:
                    self.rx_queue.pop(0)  # overrun
                self.flags |= 0x80
            self.rx_end = (self.rx_end + 10 * self.bit_cycles()) if self.rx_queue else BIG

    def next_event(self) -> int:
        return min(self.tx_end, self.rx_end)


# --------------------------------------------------------------------------- ADC

class ADC:
    """Successive-approximation ADC. ``channel(mux)`` -> pin name / 'VBG' / 'GND' / 'TEMP';
    ``ref(admux)`` -> 'AVCC' / 'AREF' / '1V1' / '2V56'."""

    def __init__(self, cpu, a: dict, vector: int, channel, ref):
        self.cpu, self.a = cpu, a
        self.channel, self.ref = channel, ref
        self.sample = None  # set by the bridge: name -> volts
        cpu.io_r[a["adcl"]] = lambda x: self.result_bytes()[0]
        cpu.io_r[a["adch"]] = lambda x: self.result_bytes()[1]
        cpu.io_r[a["admux"]] = lambda x: self.admux
        cpu.io_w[a["admux"]] = lambda x, v, m=0xFF: setattr(self, "admux", (self.admux & ~m | v & m) & 0xFF)
        cpu.io_r[a["adcsra"]] = self._r_sra
        cpu.io_w[a["adcsra"]] = self._w_sra
        cpu.add_irq(vector, lambda: (self.sra & 0x10) and (self.sra & 0x08),
                    lambda: setattr(self, "sra", self.sra & ~0x10))
        self.reset()

    def reset(self):
        self.admux = 0
        self.sra = 0
        self.result = 0
        self.end = BIG
        self.first = True

    def result_bytes(self):
        r = self.result
        if self.admux & 0x20:  # ADLAR
            r <<= 6
        return r & 0xFF, (r >> 8) & 0xFF

    def _div(self):
        return max(2, 1 << (self.sra & 7))

    def _r_sra(self, x):
        self.update(self.cpu.cycles)
        return self.sra

    def _w_sra(self, x, v, m=0xFF):
        cyc = self.cpu.cycles
        self.update(cyc)
        v = (self.sra & ~m | v & m) & 0xFF
        if v & m & 0x10:  # writing one clears ADIF
            v &= ~0x10
        else:
            v = (v & ~0x10) | (self.sra & 0x10)
        start = (v & 0x40) and not (self.sra & 0x40)
        self.sra = v
        if not v & 0x80:
            self.sra &= ~0x40
            self.end = BIG
            self.first = True
        elif start:
            self.end = cyc + (25 if self.first else 13) * self._div()
            self.first = False
        self.cpu.kick()

    def convert(self) -> int:
        if self.sample is None:
            return 0
        ch = self.channel(self.admux)
        ref = self.ref(self.admux)
        vref = {"1V1": 1.1, "2V56": 2.56}.get(ref) or self.sample(ref) or 1e-9
        if ch == "VBG":
            v = 1.1
        elif ch in ("GND", None):
            v = 0.0
        elif ch == "TEMP":
            v = 0.314
        else:
            v = self.sample(ch)
        return int(min(1023, max(0, v / max(vref, 1e-9) * 1024)))

    def update(self, cyc: int) -> None:
        while self.end <= cyc:
            self.result = self.convert()
            self.sra |= 0x10
            if self.sra & 0x20:  # auto trigger (free running)
                self.end += 13 * self._div()
            else:
                self.sra &= ~0x40
                self.end = BIG
            self.cpu.kick()

    def next_event(self) -> int:
        return self.end


# --------------------------------------------------------------------------- external / pin-change interrupts

class ExtInt:
    """INTn pins (low level / any change / falling / rising, from ``isc(n)``) and pin-change groups."""

    def __init__(self, cpu, pins: Pins, ints: list, pcint_groups: list, int_flags: FlagReg, pc_flags: FlagReg,
                 isc, mask_addr: int, pcicr_addr: int | None):
        self.cpu, self.pins = cpu, pins
        self.ints = [(pins.index.get(p), bit, vec) for p, bit, vec in ints]
        self.groups = [([pins.index.get(p) for p in grp], msk, bit, vec) for grp, msk, bit, vec in pcint_groups]
        self.iflags, self.pflags = int_flags, pc_flags
        self.isc = isc
        self.mask_addr = mask_addr
        self.pcicr_addr = pcicr_addr
        pins.on_change.append(self._changed)
        for n, (pin, bit, vec) in enumerate(self.ints):
            cpu.add_irq(vec, (lambda n=n, pin=pin, bit=bit: self._int_pending(n, pin, bit)),
                        (lambda n=n, bit=bit: self._int_ack(n, bit)))
        for grp, msk, bit, vec in self.groups:
            en = (lambda b=bit: (cpu.data[self.pcicr_addr] & b) if self.pcicr_addr is not None else
                  (cpu.data[self.mask_addr] & b))
            cpu.add_irq(vec, (lambda b=bit, en=en: (self.pflags.v & b) and en()),
                        (lambda b=bit: setattr(self.pflags, "v", self.pflags.v & ~b)))

    def _int_pending(self, n, pin, bit):
        if not self.cpu.data[self.mask_addr] & bit:
            return False
        if self.isc(n) == 0:  # low level
            return pin is not None and self.pins.level[pin] == 0
        return self.iflags.v & bit

    def _int_ack(self, n, bit):
        if self.isc(n) != 0:
            self.iflags.v &= ~bit

    def _changed(self, pin, level, cyc):
        for n, (p, bit, vec) in enumerate(self.ints):
            if p == pin:
                mode = self.isc(n)
                if mode == 1 or (mode == 2 and not level) or (mode == 3 and level):
                    self.iflags.set(bit)
                elif mode == 0:
                    self.cpu.kick()
        for grp, msk, bit, vec in self.groups:
            if pin in grp:
                idx = grp.index(pin)
                if self.cpu.data[msk] >> idx & 1:
                    self.pflags.set(bit)

    def reset(self):
        pass

    def update(self, cyc):
        pass

    def next_event(self):
        return BIG


# --------------------------------------------------------------------------- watchdog and EEPROM

class Watchdog:
    def __init__(self, cpu, addr: int, vector: int, on_reset):
        self.cpu, self.addr, self.on_reset = cpu, addr, on_reset
        cpu.io_r[addr] = lambda a: self.r
        cpu.io_w[addr] = self._w
        cpu.on_wdr = self.kick_dog
        cpu.add_irq(vector, lambda: (self.r & 0x80) and (self.r & 0x40), self._ack)
        self.reset()

    def reset(self):
        self.r = 0
        self.start = self.cpu.cycles
        self.fired_reset = False

    def _ack(self):
        self.r &= ~0x80
        if self.r & 0x08:  # interrupt-and-reset mode: next time out resets
            self.r &= ~0x40

    def _w(self, a, v, m=0xFF):
        v = (self.r & ~m | v & m) & 0xFF
        if v & 0x80:
            v &= ~0x80
        else:
            v |= self.r & 0x80
        self.r = v & ~0x10
        self.start = self.cpu.cycles
        self.cpu.kick()

    def kick_dog(self):
        self.start = self.cpu.cycles

    def period(self) -> int:
        wdp = (self.r & 7) | ((self.r >> 2) & 8)
        return int(self.cpu.clock * 0.016 * (1 << min(wdp, 9)))

    def update(self, cyc):
        if not self.r & 0x48:
            return
        while cyc >= self.start + self.period():
            self.start += self.period()
            if self.r & 0x40:
                self.r |= 0x80
                self.cpu.kick()
            elif self.r & 0x08:
                self.on_reset("watchdog")
                return

    def next_event(self):
        if not self.r & 0x48:
            return BIG
        return self.start + self.period()


class EEPROM:
    def __init__(self, cpu, a: dict, vector: int):
        self.cpu, self.a = cpu, a
        cpu.io_r[a["eecr"]] = lambda x: self.cr
        cpu.io_w[a["eecr"]] = self._w_cr
        cpu.io_r[a["eedr"]] = lambda x: self.dr
        cpu.io_w[a["eedr"]] = lambda x, v, m=0xFF: setattr(self, "dr", v & 0xFF)
        cpu.io_r[a["eearl"]] = lambda x: self.ar & 0xFF
        cpu.io_w[a["eearl"]] = lambda x, v, m=0xFF: setattr(self, "ar", (self.ar & 0xFF00) | (v & 0xFF))
        if a.get("eearh"):
            cpu.io_r[a["eearh"]] = lambda x: self.ar >> 8
            cpu.io_w[a["eearh"]] = lambda x, v, m=0xFF: setattr(self, "ar", (self.ar & 0xFF) | ((v & 0xFF) << 8))
        cpu.add_irq(vector, lambda: (self.cr & 0x08) and not (self.cr & 0x02), lambda: None)
        self.reset()

    def reset(self):
        self.cr = 0
        self.dr = 0
        self.ar = 0
        self.mpe_until = -1
        self.done = BIG

    def _w_cr(self, x, v, m=0xFF):
        cyc = self.cpu.cycles
        v = (self.cr & ~m | v & m) & 0xFF
        ee = self.cpu.eeprom
        if v & 0x04 and not self.cr & 0x04:
            self.mpe_until = cyc + 4
        if v & 0x01:  # EERE
            self.dr = ee[self.ar % len(ee)] if len(ee) else 0xFF
            v &= ~0x01
        if v & 0x02 and not self.cr & 0x02:
            if cyc <= self.mpe_until and len(ee):
                ee[self.ar % len(ee)] = self.dr
                self.done = cyc + int(self.cpu.clock * 0.0034)
            else:
                v &= ~0x02
        self.cr = v
        self.cpu.kick()

    def update(self, cyc):
        if cyc >= self.mpe_until:
            self.cr &= ~0x04
        if self.done <= cyc:
            self.cr &= ~0x02
            self.done = BIG
            self.cpu.kick()

    def next_event(self):
        return self.done
