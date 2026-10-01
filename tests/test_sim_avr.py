"""AVR emulator: instruction set and flags, interrupts, timers, USART and ADC, co-simulated with the circuit."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from avr_asm import Asm  # noqa: E402

from pcbpro.model.board import Component, Project  # noqa: E402
from pcbpro.model.footprints import find_part  # noqa: E402
from pcbpro.sim.avr.cpu import AVR  # noqa: E402
from pcbpro.sim.avr.hexfile import parse_hex, to_hex  # noqa: E402
from pcbpro.sim.avr.parts import CHIPS  # noqa: E402
from pcbpro.sim.avr.periph import Pins  # noqa: E402

# ATmega328P registers (data-space addresses) and I/O addresses for IN/OUT
PINB, DDRB, PORTB, DDRD, PORTD = 0x03, 0x04, 0x05, 0x0A, 0x0B  # I/O space
SPL, SPH = 0x3D, 0x3E
TCCR0B, TIMSK0 = 0x25, 0x6E
UCSR0A, UCSR0B, UBRR0L, UDR0 = 0xC0, 0xC1, 0xC4, 0xC6
ADMUX, ADCSRA, ADCL, ADCH = 0x7C, 0x7A, 0x78, 0x79


class _Mcu:
    def watchdog_reset(self, reason):
        pass


def _cpu(image: bytes, chip="ATMEGA328P", clock=16e6):
    dev = CHIPS[chip]
    cpu = AVR(dev, clock)
    pins = Pins(cpu, dev.gpio)
    per = dev.setup(cpu, pins, _Mcu())
    cpu.load(image)
    cpu.reset()
    return cpu, pins, per


def _stack(a: Asm):
    a.ldi(16, 0xFF)
    a.out(SPL, 16)
    a.ldi(16, 0x08)
    a.out(SPH, 16)


def test_hex_roundtrip():
    img = bytes(range(40))
    assert parse_hex(to_hex(img))[:40] == img


def test_alu_flags_branches_stack_and_mul():
    a = Asm()
    _stack(a)
    a.ldi(16, 200)
    a.ldi(17, 100)
    a.add(16, 17)          # 300 -> 44, carry
    a.in_(20, 0x3F)        # SREG -> r20
    a.ldi(18, 0x80)
    a.ldi(19, 0x01)
    a.sub(18, 19)          # 0x7F, overflow (V) set
    a.in_(21, 0x3F)
    a.ldi(22, 0x0F)
    a.inc(22)              # 0x10, half-carry untouched, Z clear
    a.ldi(24, 0xFF)
    a.ldi(25, 0x00)
    a.adiw(24, 1)          # 0x0100
    a.ldi(26, 12)
    a.ldi(27, 11)
    a.mul(26, 27)          # 132 in r1:r0
    a.ldi(28, 5)
    a.ldi(29, 0)
    a.label("loop")        # r29 += r28 five times via a counted loop
    a.add(29, 28)
    a.dec(28)
    a.brne("loop")
    a.ldi(30, 0x55)
    a.push(30)
    a.ldi(30, 0)
    a.pop(31)
    a.rcall("sub")
    a.label("end")
    a.rjmp("end")
    a.label("sub")
    a.ldi(23, 0xAA)
    a.ret()
    cpu, _, _ = _cpu(a.assemble())
    cpu.run(400)
    d = cpu.data
    assert d[16] == 44 and d[20] & 1  # carry
    assert d[18] == 0x7F and d[21] & 8  # overflow
    assert d[22] == 0x10
    assert d[24] == 0 and d[25] == 1
    assert d[0] == 132 and d[1] == 0
    assert d[29] == 15
    assert d[31] == 0x55
    assert d[23] == 0xAA


def _board(image: bytes, extra=(), clock=16e6, chip_part="DIP-28 (300 mil)", mpn="ATmega328P-PU"):
    """5 V header + ATmega328P (DIP-28) + whatever ``extra`` components."""
    p = Project("avr")
    u1 = Component("U1", "ATmega328P", find_part(chip_part).make(), mpn=mpn,
                   pad_nets={"7": "VCC", "20": "VCC", "8": "GND", "22": "GND", "1": "RST", "19": "PB5", "23": "A0",
                             "3": "TXD"})
    j1 = Component("J1", "5V", find_part("Pin header 1x2 P2.54").make(), pad_nets={"1": "VCC", "2": "GND"})
    rr = Component("R9", "10k", find_part("Resistor 0805").make(), pad_nets={"1": "VCC", "2": "RST"})
    p.components += [u1, j1, rr, *extra]
    p.sim["mcu"] = {u1.uid: {"hex": to_hex(image), "clock": clock}}
    return p, u1


def _runner(p):
    from pcbpro.sim.session import SimRunner
    return SimRunner(p, "design", "power", speed=1.0)


def _advance(r, seconds):
    r.advance(seconds, budget=600.0)
    assert not r.error, r.error


def test_timer0_overflow_interrupt_blinks_led():
    a = Asm()
    a.jmp("main")
    a.org(16 * 2)  # TIMER0_OVF vector
    a.jmp("isr")
    a.label("main")
    _stack(a)
    a.sbi(DDRB, 5)
    a.ldi(16, 5)           # clk/1024
    a.out(TCCR0B, 16)
    a.ldi(16, 1)
    a.sts(TIMSK0, 16)      # TOIE0
    a.sei()
    a.label("idle")
    a.rjmp("idle")
    a.label("isr")
    a.sbi(PINB, 5)         # toggle PB5
    a.reti()
    led = Component("D1", "Red", find_part("LED 0805").make(), pad_nets={"2": "LA", "1": "GND"})
    res = Component("R1", "330", find_part("Resistor 0805").make(), pad_nets={"1": "PB5", "2": "LA"})
    p, u1 = _board(a.assemble(), [led, res])
    r = _runner(p)
    times = []
    last = [None]
    mcu = r.ck.mcus[0]
    pb5 = mcu.pins.index["PB5"]

    def watch(t, st):
        if st != last[0]:
            times.append(t)
            last[0] = st
    mcu.watchers.setdefault(pb5, []).append(watch)
    _advance(r, 0.12)
    gaps = np.diff(times[1:])
    assert len(gaps) >= 4
    assert np.allclose(gaps, 256 * 1024 / 16e6, rtol=1e-3)
    led_dev = next(i for i in r.ck.parts.values() if i.ref == "D1").leds[0][0]
    peak = max(led_dev.current(float(r.sim.x[led_dev.nodes[0]] - r.sim.x[led_dev.nodes[1]])) for _ in [0])
    assert peak >= 0  # LED exists in the circuit


def test_usart_hello():
    a = Asm()
    a.jmp("main")
    a.label("text")
    a.w(ord("H") | ord("e") << 8, ord("l") | ord("l") << 8, ord("o") | 0 << 8)
    a.label("main")
    _stack(a)
    a.ldi(16, 103)
    a.sts(UBRR0L, 16)      # 9600 baud at 16 MHz
    a.ldi(16, 0x08)
    a.sts(UCSR0B, 16)      # TXEN
    a.ldi(30, 4)           # Z = byte address of "text" (word 2)
    a.ldi(31, 0)
    a.label("next")
    a.lpm_zp(17)
    a.cpi(17, 0)
    a.breq("done")
    a.label("wait")
    a.lds(18, UCSR0A)
    a.sbrs(18, 5)          # UDRE
    a.rjmp("wait")
    a.sts(UDR0, 17)
    a.rjmp("next")
    a.label("done")
    a.rjmp("done")
    p, u1 = _board(a.assemble())
    r = _runner(p)
    _advance(r, 0.01)
    snap = r.snapshot()
    assert snap["serial"][u1.uid] == "Hello"


def test_adc_reads_a_divider():
    a = Asm()
    _stack(a)
    a.ldi(16, 0xFF)
    a.out(DDRD, 16)
    a.ldi(16, 0x40)
    a.sts(ADMUX, 16)       # AVCC reference, channel 0 (PC0)
    a.label("again")
    a.ldi(16, 0xC7)
    a.sts(ADCSRA, 16)      # enable + start, clk/128
    a.label("busy")
    a.lds(17, ADCSRA)
    a.sbrc(17, 6)
    a.rjmp("busy")
    a.lds(18, ADCL)
    a.lds(19, ADCH)
    a.sts(0x100, 18)
    a.sts(0x101, 19)
    a.rjmp("again")
    r1 = Component("R1", "10k", find_part("Resistor 0805").make(), pad_nets={"1": "VCC", "2": "A0"})
    r2 = Component("R2", "10k", find_part("Resistor 0805").make(), pad_nets={"1": "A0", "2": "GND"})
    p, u1 = _board(a.assemble(), [r1, r2])
    r = _runner(p)
    _advance(r, 0.005)
    cpu = r.ck.mcus[0].cpu
    val = cpu.data[0x100] | cpu.data[0x101] << 8
    assert 500 <= val <= 524


FIXTURE = Path(__file__).parent / "fixtures" / "blink_328p.hex"


@pytest.mark.skipif(not FIXTURE.exists(), reason="no compiled Arduino Blink .hex in tests/fixtures")
def test_real_arduino_blink():
    led = Component("D1", "Red", find_part("LED 0805").make(), pad_nets={"2": "LA", "1": "GND"})
    res = Component("R1", "330", find_part("Resistor 0805").make(), pad_nets={"1": "PB5", "2": "LA"})
    p, u1 = _board(b"", [led, res])
    p.sim["mcu"][u1.uid]["hex"] = FIXTURE.read_text()
    r = _runner(p)
    mcu = r.ck.mcus[0]
    times = []
    mcu.watchers.setdefault(mcu.pins.index["PB5"], []).append(lambda t, st: times.append(t))
    _advance(r, 2.5)
    assert len(times) >= 2
    assert np.allclose(np.diff(times[:3]), 1.0, rtol=0.01)


def test_arduino_nano_module_led_l_blinks_from_usb_power():
    a = Asm()
    a.jmp("main")
    a.org(16 * 2)
    a.jmp("isr")
    a.label("main")
    _stack(a)
    a.sbi(DDRB, 5)
    a.ldi(16, 5)
    a.out(TCCR0B, 16)
    a.ldi(16, 1)
    a.sts(TIMSK0, 16)
    a.sei()
    a.label("idle")
    a.rjmp("idle")
    a.label("isr")
    a.sbi(PINB, 5)
    a.reti()
    p = Project("nano")
    nano = Component("A1", "Arduino_Nano", find_part("Arduino Nano").make())
    p.components.append(nano)
    p.sim["mcu"] = {nano.uid: {"hex": to_hex(a.assemble())}}
    from pcbpro.sim.models import resolve
    res = resolve(nano)
    assert res.kind == "mcu" and res.params["module"] == "nano"
    r = _runner(p)
    info = next(iter(r.ck.parts.values()))
    assert {lab for _, _, lab in info.leds} == {"L", "ON"}
    levels = []
    for _ in range(12):
        _advance(r, 0.005)
        snap = r.snapshot()
        levels.append(dict(zip([lab for _, _, lab, _ in r.leds], snap["led"])))
    on = [lv["ON"] for lv in levels[1:]]
    ell = [lv["L"] for lv in levels[1:]]
    assert min(on) > 1e-3  # power LED lit from USB
    assert max(ell) > 1e-3 and min(ell) < 1e-4  # L blinks
