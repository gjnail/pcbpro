"""Tiny AVR assembler for the emulator tests (instruction encoders + labels)."""


class Asm:
    def __init__(self):
        self.words: list = []
        self.labels: dict = {}

    @property
    def pc(self):
        return len(self.words)

    def label(self, name):
        self.labels[name] = self.pc

    def org(self, word_addr):
        while self.pc < word_addr:
            self.words.append(0)

    def w(self, *ws):
        self.words.extend(ws)

    # ---- encoders
    def _rr(self, base, d, r):
        self.w(base | ((r & 0x10) << 5) | (d << 4) | (r & 0xF))

    def _ri(self, base, d, K):
        self.w(base | ((K & 0xF0) << 4) | ((d - 16) << 4) | (K & 0xF))

    def ldi(self, d, K): self._ri(0xE000, d, K & 0xFF)
    def cpi(self, d, K): self._ri(0x3000, d, K & 0xFF)
    def subi(self, d, K): self._ri(0x5000, d, K & 0xFF)
    def sbci(self, d, K): self._ri(0x4000, d, K & 0xFF)
    def ori(self, d, K): self._ri(0x6000, d, K & 0xFF)
    def andi(self, d, K): self._ri(0x7000, d, K & 0xFF)
    def add(self, d, r): self._rr(0x0C00, d, r)
    def adc(self, d, r): self._rr(0x1C00, d, r)
    def sub(self, d, r): self._rr(0x1800, d, r)
    def sbc(self, d, r): self._rr(0x0800, d, r)
    def and_(self, d, r): self._rr(0x2000, d, r)
    def or_(self, d, r): self._rr(0x2800, d, r)
    def eor(self, d, r): self._rr(0x2400, d, r)
    def mov(self, d, r): self._rr(0x2C00, d, r)
    def cp(self, d, r): self._rr(0x1400, d, r)
    def cpc(self, d, r): self._rr(0x0400, d, r)
    def mul(self, d, r): self._rr(0x9C00, d, r)
    def inc(self, d): self.w(0x9403 | (d << 4))
    def dec(self, d): self.w(0x940A | (d << 4))
    def com(self, d): self.w(0x9400 | (d << 4))
    def neg(self, d): self.w(0x9401 | (d << 4))
    def lsr(self, d): self.w(0x9406 | (d << 4))
    def ror(self, d): self.w(0x9407 | (d << 4))
    def asr(self, d): self.w(0x9405 | (d << 4))
    def swap(self, d): self.w(0x9402 | (d << 4))
    def push(self, r): self.w(0x920F | (r << 4))
    def pop(self, d): self.w(0x900F | (d << 4))
    def movw(self, d, r): self.w(0x0100 | ((d // 2) << 4) | (r // 2))
    def adiw(self, d, K): self.w(0x9600 | ((K & 0x30) << 2) | (((d - 24) // 2) << 4) | (K & 0xF))
    def sbiw(self, d, K): self.w(0x9700 | ((K & 0x30) << 2) | (((d - 24) // 2) << 4) | (K & 0xF))
    def out(self, A, r): self.w(0xB800 | ((A & 0x30) << 5) | (r << 4) | (A & 0xF))
    def in_(self, d, A): self.w(0xB000 | ((A & 0x30) << 5) | (d << 4) | (A & 0xF))
    def sts(self, k, r): self.w(0x9200 | (r << 4), k)
    def lds(self, d, k): self.w(0x9000 | (d << 4), k)
    def lpm_zp(self, d): self.w(0x9005 | (d << 4))
    def st_xp(self, r): self.w(0x920D | (r << 4))
    def ld_xp(self, d): self.w(0x900D | (d << 4))
    def sbi(self, A, b): self.w(0x9A00 | (A << 3) | b)
    def cbi(self, A, b): self.w(0x9800 | (A << 3) | b)
    def sbis(self, A, b): self.w(0x9B00 | (A << 3) | b)
    def sbic(self, A, b): self.w(0x9900 | (A << 3) | b)
    def sbrs(self, r, b): self.w(0xFE00 | (r << 4) | b)
    def sbrc(self, r, b): self.w(0xFC00 | (r << 4) | b)
    def sei(self): self.w(0x9478)
    def cli(self): self.w(0x94F8)
    def ret(self): self.w(0x9508)
    def reti(self): self.w(0x9518)
    def sleep(self): self.w(0x9588)
    def nop(self): self.w(0x0000)

    def jmp(self, label): self.w(("jmp", label), 0)
    def call(self, label): self.w(("call", label), 0)
    def rjmp(self, label): self.w(("rjmp", label))
    def rcall(self, label): self.w(("rcall", label))
    def brne(self, label): self.w(("br", label, 0xF401))
    def breq(self, label): self.w(("br", label, 0xF001))
    def brcc(self, label): self.w(("br", label, 0xF400))
    def brcs(self, label): self.w(("br", label, 0xF000))

    def assemble(self) -> bytes:
        out = []
        for i, w in enumerate(self.words):
            if isinstance(w, tuple):
                kind, label = w[0], w[1]
                tgt = self.labels[label]
                if kind == "jmp":
                    w = 0x940C | ((tgt >> 16) & 1) | (((tgt >> 17) & 0x1F) << 4)
                    self.words[i + 1] = tgt & 0xFFFF
                elif kind == "call":
                    w = 0x940E
                    self.words[i + 1] = tgt & 0xFFFF
                elif kind in ("rjmp", "rcall"):
                    k = (tgt - i - 1) & 0xFFF
                    w = (0xC000 if kind == "rjmp" else 0xD000) | k
                else:
                    k = (tgt - i - 1) & 0x7F
                    w = w[2] | (k << 3)
            out.append(w)
        data = bytearray()
        for w in out:
            data += bytes([w & 0xFF, (w >> 8) & 0xFF])
        return bytes(data)
