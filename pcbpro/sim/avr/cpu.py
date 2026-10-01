"""AVR CPU core: the AVRe+ instruction set used by ATmega and ATtiny parts.

Flash words are decoded once into (handler, a, b) tuples; handlers are closures over the data memory and return
the instruction's cycle count. ALU flags come from precomputed tables. Peripherals are updated lazily: the CPU only
stops to service them at the cycle of their next event (timer match, UART byte, ADC result), which also is where
interrupts are dispatched. SLEEP fast-forwards to the next event.
"""
from __future__ import annotations

import numpy as np

BIG = 1 << 62


def _tables():
    a = np.arange(256, dtype=np.int32)[:, None]
    b = np.arange(256, dtype=np.int32)[None, :]
    out = {}
    for c in (0, 1):
        r = a + b + c
        R = r & 0xFF
        v = ((a ^ R) & (b ^ R) & 0x80) != 0
        n = (R & 0x80) != 0
        f = ((r > 0xFF) * 1 | (R == 0) * 2 | n * 4 | v * 8 | (n ^ v) * 16 | (((a & 15) + (b & 15) + c) > 15) * 32)
        out[("add", c)] = bytes(f.astype(np.uint8).ravel())
        r = a - b - c
        R = r & 0xFF
        v = ((a ^ b) & (a ^ R) & 0x80) != 0
        n = (R & 0x80) != 0
        f = ((r < 0) * 1 | (R == 0) * 2 | n * 4 | v * 8 | (n ^ v) * 16 | (((a & 15) - (b & 15) - c) < 0) * 32)
        out[("sub", c)] = bytes(f.astype(np.uint8).ravel())
    R = np.arange(256)
    n = (R & 0x80) != 0
    out["logic"] = bytes(((R == 0) * 2 | n * 4 | n * 16).astype(np.uint8))
    return out


_TABLES = None


def tables():
    global _TABLES
    if _TABLES is None:
        _TABLES = _tables()
    return _TABLES


def _s(v: int, bits: int) -> int:
    return v - (1 << bits) if v & (1 << (bits - 1)) else v


class AVR:
    """One AVR core. ``dev`` is a part description (avr/parts.py)."""

    def __init__(self, dev, clock: float):
        self.dev = dev
        self.clock = float(clock)
        self.data = bytearray(dev.ram_end + 1)
        self.flash = bytearray(b"\xff" * dev.flash_size)
        self.eeprom = bytearray(b"\xff" * dev.eeprom_size)
        self.io_r = [None] * 0x100
        self.io_w = [None] * 0x100
        self.pc = 0
        self.sreg = 0
        self.sp = dev.ram_end
        self.cycles = 0
        self.next_event = 0
        self.sleeping = False
        self.ie_delay = 0
        self.periph: list = []
        self.irqs: list = []  # (vector, pending(), ack())
        self.unknown = 0
        self.loaded = False
        self.on_wdr = None
        self.vec_size = dev.vector_words
        self.io_r[0x5F] = lambda a: self.sreg
        self.io_w[0x5F] = self._w_sreg
        self.io_r[0x5D] = lambda a: self.sp & 0xFF
        self.io_r[0x5E] = lambda a: (self.sp >> 8) & 0xFF
        self.io_w[0x5D] = lambda a, v, m=0xFF: setattr(self, "sp", (self.sp & 0xFF00) | (v & 0xFF))
        self.io_w[0x5E] = lambda a, v, m=0xFF: setattr(self, "sp", (self.sp & 0x00FF) | ((v & 0xFF) << 8))
        self._h = self._handlers()
        self.ops: list = []
        self.size: list = []

    def _w_sreg(self, a, v, m=0xFF):
        self.sreg = (self.sreg & ~m | v & m) & 0xFF
        self.next_event = 0

    # ------------------------------------------------------------------ setup
    def add_periph(self, p) -> None:
        self.periph.append(p)

    def add_irq(self, vector: int, pending, ack) -> None:
        self.irqs.append((vector, pending, ack))
        self.irqs.sort(key=lambda t: t[0])

    def load(self, image: bytes) -> None:
        n = min(len(image), len(self.flash))
        self.flash[:n] = image[:n]
        self._decode_all()
        self.loaded = any(b != 0xFF for b in image[:n])

    def reset(self) -> None:
        d = self.data
        d[:] = bytes(len(d))
        self.pc = 0
        self.sreg = 0
        self.sp = self.dev.ram_end
        self.sleeping = False
        self.ie_delay = 0
        for p in self.periph:
            p.reset()
        self.next_event = 0

    def kick(self) -> None:
        """Something changed that may raise an interrupt or reschedule events: service before the next
        instruction."""
        self.next_event = 0

    # ------------------------------------------------------------------ data space
    def rd(self, addr: int) -> int:
        if addr < 0x100:
            h = self.io_r[addr]
            if h is not None:
                return h(addr) & 0xFF
        if addr < len(self.data):
            return self.data[addr]
        return 0

    def wr(self, addr: int, v: int, mask: int = 0xFF) -> None:
        v &= 0xFF
        if addr < 0x100:
            h = self.io_w[addr]
            if h is not None:
                h(addr, v, mask)
                return
        if addr < len(self.data):
            if mask != 0xFF:
                v = (self.data[addr] & ~mask | v & mask) & 0xFF
            self.data[addr] = v

    def push(self, v: int) -> None:
        if 0 <= self.sp < len(self.data):
            self.data[self.sp] = v & 0xFF
        self.sp = (self.sp - 1) & 0xFFFF

    def pop(self) -> int:
        self.sp = (self.sp + 1) & 0xFFFF
        return self.data[self.sp] if self.sp < len(self.data) else 0

    def push_pc(self, pc: int) -> None:
        self.push(pc & 0xFF)
        self.push((pc >> 8) & 0xFF)
        if self.dev.pc22:
            self.push((pc >> 16) & 0xFF)

    def pop_pc(self) -> int:
        hi = self.pop() << 16 if self.dev.pc22 else 0
        return hi | (self.pop() << 8) | self.pop()

    # ------------------------------------------------------------------ execution
    def run(self, target: int) -> None:
        """Execute until the cycle counter reaches ``target``."""
        ops = self.ops
        if not ops:
            self.cycles = max(self.cycles, target)
            return
        nops = len(ops)
        while self.cycles < target:
            self._service(target)
            if self.sleeping or self.cycles >= target:
                continue
            while self.cycles < self.next_event:
                pc = self.pc
                if pc >= nops:
                    self.pc = pc % nops
                    continue
                op = ops[pc]
                self.cycles += op[0](op[1], op[2])

    def _service(self, target: int) -> None:
        cyc = self.cycles
        for p in self.periph:
            p.update(cyc)
        took = False
        delayed = bool(self.ie_delay)  # one more instruction runs after SEI / RETI before an interrupt
        if delayed:
            self.ie_delay = 0
        elif self.sreg & 0x80:
            for vec, pending, ack in self.irqs:
                if pending():
                    ack()
                    wake = self.sleeping
                    self.sleeping = False
                    self.push_pc(self.pc)
                    self.sreg &= 0x7F
                    self.pc = vec * self.vec_size
                    self.cycles += 4 + (4 if wake else 0)
                    took = True
                    break
        nxt = target
        for p in self.periph:
            e = p.next_event()
            if e < nxt:
                nxt = e
        if self.sleeping and not took:
            self.cycles = max(self.cycles, nxt)
            self.next_event = self.cycles
            return
        self.next_event = self.cycles + 1 if delayed else nxt
        if self.next_event <= self.cycles:
            self.next_event = self.cycles + 1

    def _decode_all(self) -> None:
        f = self.flash
        nw = len(f) // 2
        words = [f[2 * i] | (f[2 * i + 1] << 8) for i in range(nw)]
        ops = []
        size = []
        for i in range(nw):
            w = words[i]
            w2 = words[i + 1] if i + 1 < nw else 0xFFFF
            op, a, b, s = self.decode(w, w2)
            ops.append((op, a, b))
            size.append(s)
        size.append(1)
        self.ops = ops
        self.size = size

    # ------------------------------------------------------------------ instruction set
    def decode(self, w: int, w2: int):
        """Returns (handler, a, b, words)."""
        h = self._h
        hi4 = w >> 12
        d5 = (w >> 4) & 0x1F
        r5 = (w & 0xF) | ((w >> 5) & 0x10)
        d4 = 16 + ((w >> 4) & 0xF)
        K8 = ((w >> 4) & 0xF0) | (w & 0xF)
        if w == 0:
            return h["nop"], 0, 0, 1
        if hi4 == 0:
            top = (w >> 8) & 0xF
            if top == 1:
                return h["movw"], ((w >> 4) & 0xF) * 2, (w & 0xF) * 2, 1
            if top == 2:
                return h["muls"], d4, 16 + (w & 0xF), 1
            if top == 0:
                return h["nop_unknown"], w, 0, 1
            if top == 3:
                d3, r3 = 16 + ((w >> 4) & 7), 16 + (w & 7)
                k = ((w >> 6) & 2) | ((w >> 3) & 1)
                return h[("mulsu", "fmul", "fmuls", "fmulsu")[k]], d3, r3, 1
            sub = (w >> 10) & 3
            return h[(None, "cpc", "sbc", "add")[sub]], d5, r5, 1
        if hi4 == 1:
            return h[("cpse", "cp", "sub", "adc")[(w >> 10) & 3]], d5, r5, 1
        if hi4 == 2:
            return h[("and", "eor", "or", "mov")[(w >> 10) & 3]], d5, r5, 1
        if hi4 == 3:
            return h["cpi"], d4, K8, 1
        if hi4 == 4:
            return h["sbci"], d4, K8, 1
        if hi4 == 5:
            return h["subi"], d4, K8, 1
        if hi4 == 6:
            return h["ori"], d4, K8, 1
        if hi4 == 7:
            return h["andi"], d4, K8, 1
        if hi4 in (8, 10):  # LDD / STD with displacement
            q = (w & 7) | ((w >> 7) & 0x18) | ((w >> 8) & 0x20)
            ptr = 28 if w & 8 else 30
            if w & 0x200:
                return h["std"], (d5, ptr), q, 1
            return h["ldd"], (d5, ptr), q, 1
        if hi4 == 9:
            return self._decode9(w, w2, d5, r5)
        if hi4 == 11:
            A = (w & 0xF) | ((w >> 5) & 0x30)
            return (h["out"] if w & 0x800 else h["in"]), d5, A + 0x20, 1
        if hi4 == 12:
            return h["rjmp"], _s(w & 0xFFF, 12), 0, 1
        if hi4 == 13:
            return h["rcall"], _s(w & 0xFFF, 12), 0, 1
        if hi4 == 14:
            return h["ldi"], d4, K8, 1
        # hi4 == 15
        sub = (w >> 9) & 7
        if sub < 4:
            k = _s((w >> 3) & 0x7F, 7)
            return (h["brbc"] if w & 0x400 else h["brbs"]), w & 7, k, 1
        b = w & 7
        return h[("bld", "bst", "sbrc", "sbrs")[sub - 4]], d5, b, 1

    def _decode9(self, w, w2, d5, r5):
        h = self._h
        sub = (w >> 9) & 7
        low = w & 0xF
        if sub in (0, 1):  # loads / stores / push / pop
            store = sub == 1
            if low == 0:
                return (h["sts"] if store else h["lds"]), d5, w2, 2
            table = {1: (30, 1), 2: (30, 2), 9: (28, 1), 10: (28, 2), 12: (26, 0), 13: (26, 1), 14: (26, 2)}
            if low in table:
                return (h["st"] if store else h["ld"]), d5, table[low], 1
            if low == 15:
                return (h["push"] if store else h["pop"]), d5, 0, 1
            if not store and low in (4, 5, 6, 7):
                return h["lpm"], d5, low & 1, 1
            return h["nop_unknown"], w, 0, 1
        if sub == 2:  # one-operand ALU, flag ops, jumps
            if low in (0, 1, 2, 3, 5, 6, 7, 10):
                return h[{0: "com", 1: "neg", 2: "swap", 3: "inc", 5: "asr", 6: "lsr", 7: "ror", 10: "dec"}[low]], \
                    d5, 0, 1
            if (w & 0xFF0F) == 0x9408:
                return h["bset"], (w >> 4) & 7, 0, 1
            if (w & 0xFF8F) == 0x9488:
                return h["bclr"], (w >> 4) & 7, 0, 1
            if w == 0x9508:
                return h["ret"], 0, 0, 1
            if w == 0x9518:
                return h["reti"], 0, 0, 1
            if w == 0x9588:
                return h["sleep"], 0, 0, 1
            if w == 0x9598:
                return h["nop"], 0, 0, 1  # BREAK
            if w == 0x95A8:
                return h["wdr"], 0, 0, 1
            if w in (0x95C8, 0x95D8):
                return h["lpm"], 0, 0, 1
            if w in (0x95E8, 0x95F8):
                return h["nop"], 0, 0, 1  # SPM
            if w in (0x9409, 0x9419):
                return h["ijmp"], 0, 0, 1
            if w in (0x9509, 0x9519):
                return h["icall"], 0, 0, 1
            if (w & 0xFE0E) == 0x940C:
                k = (((w >> 3) & 0x3E) | (w & 1)) << 16 | w2
                return h["jmp"], k, 0, 2
            if (w & 0xFE0E) == 0x940E:
                k = (((w >> 3) & 0x3E) | (w & 1)) << 16 | w2
                return h["call"], k, 0, 2
            if low == 0xA and (w & 0xFE0F) == 0x940A:
                return h["dec"], d5, 0, 1
            return h["nop_unknown"], w, 0, 1
        if sub == 3:  # ADIW / SBIW
            d = 24 + ((w >> 4) & 3) * 2
            K = (w & 0xF) | ((w >> 2) & 0x30)
            return (h["sbiw"] if w & 0x100 else h["adiw"]), d, K, 1
        if sub in (4, 5):  # CBI SBIC SBI SBIS
            A = ((w >> 3) & 0x1F) + 0x20
            b = w & 7
            return h[("cbi", "sbic", "sbi", "sbis")[(w >> 8) & 3]], A, b, 1
        # sub 6, 7: MUL
        return h["mul"], d5, r5, 1

    def _handlers(self) -> dict:
        cpu = self
        D = self.data
        T = tables()
        ADD0, ADD1, SUB0, SUB1, LOG = T[("add", 0)], T[("add", 1)], T[("sub", 0)], T[("sub", 1)], T["logic"]
        rd, wr = self.rd, self.wr
        flash = self.flash

        def nop(a, b):
            cpu.pc += 1
            return 1

        def nop_unknown(a, b):
            cpu.unknown += 1
            cpu.pc += 1
            return 1

        def movw(d, r):
            D[d] = D[r]
            D[d + 1] = D[r + 1]
            cpu.pc += 1
            return 1

        def add(d, r):
            x, y = D[d], D[r]
            cpu.sreg = (cpu.sreg & 0xC0) | ADD0[(x << 8) | y]
            D[d] = (x + y) & 0xFF
            cpu.pc += 1
            return 1

        def adc(d, r):
            x, y = D[d], D[r]
            c = cpu.sreg & 1
            cpu.sreg = (cpu.sreg & 0xC0) | (ADD1 if c else ADD0)[(x << 8) | y]
            D[d] = (x + y + c) & 0xFF
            cpu.pc += 1
            return 1

        def sub(d, r):
            x, y = D[d], D[r]
            cpu.sreg = (cpu.sreg & 0xC0) | SUB0[(x << 8) | y]
            D[d] = (x - y) & 0xFF
            cpu.pc += 1
            return 1

        def _sbc(x, y):
            s = cpu.sreg
            c = s & 1
            f = (SUB1 if c else SUB0)[(x << 8) | y]
            R = (x - y - c) & 0xFF
            if R == 0:
                f = (f & 0xFD) | (s & 2)
            cpu.sreg = (s & 0xC0) | f
            return R

        def sbc(d, r):
            D[d] = _sbc(D[d], D[r])
            cpu.pc += 1
            return 1

        def cp(d, r):
            cpu.sreg = (cpu.sreg & 0xC0) | SUB0[(D[d] << 8) | D[r]]
            cpu.pc += 1
            return 1

        def cpc(d, r):
            _sbc(D[d], D[r])
            cpu.pc += 1
            return 1

        def cpse(d, r):
            if D[d] == D[r]:
                s = cpu.size[cpu.pc + 1]
                cpu.pc += 1 + s
                return 1 + s
            cpu.pc += 1
            return 1

        def and_(d, r):
            R = D[d] & D[r]
            D[d] = R
            cpu.sreg = (cpu.sreg & 0xE1) | LOG[R]
            cpu.pc += 1
            return 1

        def or_(d, r):
            R = D[d] | D[r]
            D[d] = R
            cpu.sreg = (cpu.sreg & 0xE1) | LOG[R]
            cpu.pc += 1
            return 1

        def eor(d, r):
            R = D[d] ^ D[r]
            D[d] = R
            cpu.sreg = (cpu.sreg & 0xE1) | LOG[R]
            cpu.pc += 1
            return 1

        def mov(d, r):
            D[d] = D[r]
            cpu.pc += 1
            return 1

        def cpi(d, K):
            cpu.sreg = (cpu.sreg & 0xC0) | SUB0[(D[d] << 8) | K]
            cpu.pc += 1
            return 1

        def sbci(d, K):
            D[d] = _sbc(D[d], K)
            cpu.pc += 1
            return 1

        def subi(d, K):
            x = D[d]
            cpu.sreg = (cpu.sreg & 0xC0) | SUB0[(x << 8) | K]
            D[d] = (x - K) & 0xFF
            cpu.pc += 1
            return 1

        def ori(d, K):
            R = D[d] | K
            D[d] = R
            cpu.sreg = (cpu.sreg & 0xE1) | LOG[R]
            cpu.pc += 1
            return 1

        def andi(d, K):
            R = D[d] & K
            D[d] = R
            cpu.sreg = (cpu.sreg & 0xE1) | LOG[R]
            cpu.pc += 1
            return 1

        def ldi(d, K):
            D[d] = K
            cpu.pc += 1
            return 1

        def ldd(dp, q):
            d, p = dp
            D[d] = rd(((D[p] | (D[p + 1] << 8)) + q) & 0xFFFF)
            cpu.pc += 1
            return 2

        def std(dp, q):
            r, p = dp
            wr(((D[p] | (D[p + 1] << 8)) + q) & 0xFFFF, D[r])
            cpu.pc += 1
            return 2

        def lds(d, k):
            D[d] = rd(k)
            cpu.pc += 2
            return 2

        def sts(r, k):
            wr(k, D[r])
            cpu.pc += 2
            return 2

        def ld(d, pm):
            p, m = pm
            a = D[p] | (D[p + 1] << 8)
            if m == 2:
                a = (a - 1) & 0xFFFF
            v = rd(a)
            if m == 1:
                a = (a + 1) & 0xFFFF
            if m:
                D[p] = a & 0xFF
                D[p + 1] = a >> 8
            D[d] = v
            cpu.pc += 1
            return 2

        def st(r, pm):
            p, m = pm
            v = D[r]
            a = D[p] | (D[p + 1] << 8)
            if m == 2:
                a = (a - 1) & 0xFFFF
            wr(a, v)
            if m == 1:
                a = (a + 1) & 0xFFFF
            if m:
                D[p] = a & 0xFF
                D[p + 1] = a >> 8
            cpu.pc += 1
            return 2

        def push(r, b):
            cpu.push(D[r])
            cpu.pc += 1
            return 2

        def pop(d, b):
            D[d] = cpu.pop()
            cpu.pc += 1
            return 2

        def lpm(d, inc):
            z = D[30] | (D[31] << 8)
            D[d] = flash[z] if z < len(flash) else 0xFF
            if inc:
                z = (z + 1) & 0xFFFF
                D[30] = z & 0xFF
                D[31] = z >> 8
            cpu.pc += 1
            return 3

        def com(d, b):
            R = 0xFF - D[d]
            D[d] = R
            cpu.sreg = (cpu.sreg & 0xE0) | LOG[R] | 1
            cpu.pc += 1
            return 1

        def neg(d, b):
            x = D[d]
            cpu.sreg = (cpu.sreg & 0xC0) | SUB0[x]
            D[d] = (-x) & 0xFF
            cpu.pc += 1
            return 1

        def swap(d, b):
            x = D[d]
            D[d] = ((x << 4) | (x >> 4)) & 0xFF
            cpu.pc += 1
            return 1

        def inc(d, b):
            R = (D[d] + 1) & 0xFF
            D[d] = R
            f = LOG[R]
            if R == 0x80:
                f = (f | 8) ^ 16
            cpu.sreg = (cpu.sreg & 0xE1) | f
            cpu.pc += 1
            return 1

        def dec(d, b):
            R = (D[d] - 1) & 0xFF
            D[d] = R
            f = LOG[R]
            if R == 0x7F:
                f = (f | 8) ^ 16
            cpu.sreg = (cpu.sreg & 0xE1) | f
            cpu.pc += 1
            return 1

        def _shift_flags(R, c):
            n = (R >> 7) & 1
            v = n ^ c
            return c | (2 if R == 0 else 0) | (n << 2) | (v << 3) | ((n ^ v) << 4)

        def asr(d, b):
            x = D[d]
            R = (x >> 1) | (x & 0x80)
            D[d] = R
            cpu.sreg = (cpu.sreg & 0xE0) | _shift_flags(R, x & 1)
            cpu.pc += 1
            return 1

        def lsr(d, b):
            x = D[d]
            R = x >> 1
            D[d] = R
            cpu.sreg = (cpu.sreg & 0xE0) | _shift_flags(R, x & 1)
            cpu.pc += 1
            return 1

        def ror(d, b):
            x = D[d]
            R = (x >> 1) | ((cpu.sreg & 1) << 7)
            D[d] = R
            cpu.sreg = (cpu.sreg & 0xE0) | _shift_flags(R, x & 1)
            cpu.pc += 1
            return 1

        def bset(s, b):
            cpu.sreg |= 1 << s
            if s == 7:
                cpu.ie_delay = 1
                cpu.next_event = 0
            cpu.pc += 1
            return 1

        def bclr(s, b):
            cpu.sreg &= ~(1 << s) & 0xFF
            cpu.pc += 1
            return 1

        def ret(a, b):
            cpu.pc = cpu.pop_pc()
            return 5 if cpu.dev.pc22 else 4

        def reti(a, b):
            cpu.pc = cpu.pop_pc()
            cpu.sreg |= 0x80
            cpu.ie_delay = 1
            cpu.next_event = 0
            return 5 if cpu.dev.pc22 else 4

        def sleep(a, b):
            cpu.pc += 1
            if cpu.dev.sleep_enabled(cpu):
                cpu.sleeping = True
                cpu.next_event = 0
            return 1

        def wdr(a, b):
            if cpu.on_wdr is not None:
                cpu.on_wdr()
            cpu.pc += 1
            return 1

        def ijmp(a, b):
            cpu.pc = D[30] | (D[31] << 8)
            return 2

        def icall(a, b):
            cpu.push_pc(cpu.pc + 1)
            cpu.pc = D[30] | (D[31] << 8)
            return 3

        def jmp(k, b):
            cpu.pc = k
            return 3

        def call(k, b):
            cpu.push_pc(cpu.pc + 2)
            cpu.pc = k
            return 4

        def rjmp(k, b):
            cpu.pc += 1 + k
            return 2

        def rcall(k, b):
            cpu.push_pc(cpu.pc + 1)
            cpu.pc += 1 + k
            return 3

        def adiw(d, K):
            v = D[d] | (D[d + 1] << 8)
            R = (v + K) & 0xFFFF
            D[d] = R & 0xFF
            D[d + 1] = R >> 8
            h7, r15 = v >> 15, R >> 15
            vf = (1 - h7) & r15
            c = (1 - r15) & h7
            cpu.sreg = (cpu.sreg & 0xE0) | c | (2 if R == 0 else 0) | (r15 << 2) | (vf << 3) | ((r15 ^ vf) << 4)
            cpu.pc += 1
            return 2

        def sbiw(d, K):
            v = D[d] | (D[d + 1] << 8)
            R = (v - K) & 0xFFFF
            D[d] = R & 0xFF
            D[d + 1] = R >> 8
            h7, r15 = v >> 15, R >> 15
            vf = h7 & (1 - r15)
            c = r15 & (1 - h7)
            cpu.sreg = (cpu.sreg & 0xE0) | c | (2 if R == 0 else 0) | (r15 << 2) | (vf << 3) | ((r15 ^ vf) << 4)
            cpu.pc += 1
            return 2

        def cbi(A, b):
            wr(A, 0, 1 << b)
            cpu.pc += 1
            return 2

        def sbi(A, b):
            wr(A, 1 << b, 1 << b)
            cpu.pc += 1
            return 2

        def sbic(A, b):
            if not (rd(A) >> b) & 1:
                s = cpu.size[cpu.pc + 1]
                cpu.pc += 1 + s
                return 1 + s
            cpu.pc += 1
            return 1

        def sbis(A, b):
            if (rd(A) >> b) & 1:
                s = cpu.size[cpu.pc + 1]
                cpu.pc += 1 + s
                return 1 + s
            cpu.pc += 1
            return 1

        def sbrc(r, b):
            if not (D[r] >> b) & 1:
                s = cpu.size[cpu.pc + 1]
                cpu.pc += 1 + s
                return 1 + s
            cpu.pc += 1
            return 1

        def sbrs(r, b):
            if (D[r] >> b) & 1:
                s = cpu.size[cpu.pc + 1]
                cpu.pc += 1 + s
                return 1 + s
            cpu.pc += 1
            return 1

        def bst(d, b):
            cpu.sreg = (cpu.sreg & 0xBF) | (((D[d] >> b) & 1) << 6)
            cpu.pc += 1
            return 1

        def bld(d, b):
            if cpu.sreg & 0x40:
                D[d] |= 1 << b
            else:
                D[d] &= ~(1 << b) & 0xFF
            cpu.pc += 1
            return 1

        def brbs(s, k):
            if (cpu.sreg >> s) & 1:
                cpu.pc += 1 + k
                return 2
            cpu.pc += 1
            return 1

        def brbc(s, k):
            if not (cpu.sreg >> s) & 1:
                cpu.pc += 1 + k
                return 2
            cpu.pc += 1
            return 1

        def in_(d, A):
            D[d] = rd(A)
            cpu.pc += 1
            return 1

        def out(r, A):
            wr(A, D[r])
            cpu.pc += 1
            return 1

        def _mul_result(p, c):
            p &= 0xFFFF
            D[0] = p & 0xFF
            D[1] = p >> 8
            cpu.sreg = (cpu.sreg & 0xFC) | c | (2 if p == 0 else 0)

        def mul(d, r):
            p = D[d] * D[r]
            _mul_result(p, (p >> 15) & 1)
            cpu.pc += 1
            return 2

        def muls(d, r):
            p = _s(D[d], 8) * _s(D[r], 8)
            _mul_result(p, (p >> 15) & 1 if p >= 0 else 1)
            cpu.pc += 1
            return 2

        def mulsu(d, r):
            p = _s(D[d], 8) * D[r]
            _mul_result(p, 1 if p < 0 else (p >> 15) & 1)
            cpu.pc += 1
            return 2

        def fmul(d, r):
            p = D[d] * D[r]
            _mul_result(p << 1, (p >> 15) & 1)
            cpu.pc += 1
            return 2

        def fmuls(d, r):
            p = _s(D[d], 8) * _s(D[r], 8)
            _mul_result(p << 1, ((p & 0xFFFF) >> 15) & 1)
            cpu.pc += 1
            return 2

        def fmulsu(d, r):
            p = _s(D[d], 8) * D[r]
            _mul_result(p << 1, ((p & 0xFFFF) >> 15) & 1)
            cpu.pc += 1
            return 2

        return {"nop": nop, "nop_unknown": nop_unknown, "movw": movw, "add": add, "adc": adc, "sub": sub, "sbc": sbc,
                "cp": cp, "cpc": cpc, "cpse": cpse, "and": and_, "or": or_, "eor": eor, "mov": mov, "cpi": cpi,
                "sbci": sbci, "subi": subi, "ori": ori, "andi": andi, "ldi": ldi, "ldd": ldd, "std": std,
                "lds": lds, "sts": sts, "ld": ld, "st": st, "push": push, "pop": pop, "lpm": lpm, "com": com,
                "neg": neg, "swap": swap, "inc": inc, "dec": dec, "asr": asr, "lsr": lsr, "ror": ror, "bset": bset,
                "bclr": bclr, "ret": ret, "reti": reti, "sleep": sleep, "wdr": wdr, "ijmp": ijmp, "icall": icall, "jmp": jmp,
                "call": call, "rjmp": rjmp, "rcall": rcall, "adiw": adiw, "sbiw": sbiw, "cbi": cbi, "sbi": sbi,
                "sbic": sbic, "sbis": sbis, "sbrc": sbrc, "sbrs": sbrs, "bst": bst, "bld": bld, "brbs": brbs,
                "brbc": brbc, "in": in_, "out": out, "mul": mul, "muls": muls, "mulsu": mulsu, "fmul": fmul,
                "fmuls": fmuls, "fmulsu": fmulsu}
