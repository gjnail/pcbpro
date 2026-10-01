"""AVR part definitions: memories, I/O maps, interrupt vectors, peripherals and package pinouts (from the Microchip
datasheets), plus the Arduino Nano and Pro Mini modules."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from .periph import (ADC, EEPROM, USART, ExtInt, FlagReg, Port, Timer, Watchdog, cfg_8bit, cfg_16bit,
                     cfg_tiny85_t1)


@dataclass
class AvrDef:
    name: str
    flash_size: int
    ram_end: int
    eeprom_size: int
    vector_words: int
    gpio: list[str]
    reset_pin: str
    xtal_pins: tuple
    setup: Callable
    se: tuple  # (address, bit) of the sleep-enable flag
    sm: tuple  # (address, shift, mask) of the sleep mode bits
    deep_modes: tuple  # sleep mode values that stop the timers
    pinmaps: dict
    default_clock: float
    vmax: float = 5.5
    pc22: bool = False
    supply_ohms: float = 500.0
    extra: dict = field(default_factory=dict)

    def sleep_enabled(self, cpu) -> bool:
        a, bit = self.se
        return bool(cpu.data[a] & bit)

    def deep_sleep(self, cpu) -> bool:
        a, shift, mask = self.sm
        return ((cpu.data[a] >> shift) & mask) in self.deep_modes


def _kick_reg(cpu, addr):
    def w(a, v, m=0xFF):
        cpu.data[a] = (cpu.data[a] & ~m | v & m) & 0xFF
        cpu.kick()
    cpu.io_w[addr] = w


# --------------------------------------------------------------------------- ATmega48/88/168/328P

PRE01 = [0, 1, 8, 64, 256, 1024, 0, 0]
PRE2 = [0, 1, 8, 32, 64, 128, 256, 1024]


def setup_mega(cpu, pins, mcu) -> dict:
    for letter, a, n in (("B", 0x23, 8), ("C", 0x26, 7), ("D", 0x29, 8)):
        cpu.add_periph(Port(cpu, pins, letter, a, a + 1, a + 2, n))
    for addr in (0x6E, 0x6F, 0x70, 0x3D, 0x68, 0x69, 0x6B, 0x6C, 0x6D, 0x53):
        _kick_reg(cpu, addr)
    tifr0, tifr1, tifr2 = FlagReg(cpu, 0x35), FlagReg(cpu, 0x36), FlagReg(cpu, 0x37)
    flags8 = {"ovf": 1, "a": 2, "b": 4}
    t0 = Timer(cpu, pins, "T0", 8, {"tccra": 0x44, "tccrb": 0x45, "tcnt": 0x46, "ocra": 0x47, "ocrb": 0x48},
               cfg_8bit(PRE01), tifr0, 0x6E, flags8, {"a": 14, "b": 15, "ovf": 16}, {"a": "PD6", "b": "PD5"})
    t1 = Timer(cpu, pins, "T1", 16, {"tccra": 0x80, "tccrb": 0x81, "tccrc": 0x82, "tcnt": (0x84, 0x85),
                                     "icr": (0x86, 0x87), "ocra": (0x88, 0x89), "ocrb": (0x8A, 0x8B)},
               cfg_16bit(PRE01), tifr1, 0x6F, {"ovf": 1, "a": 2, "b": 4, "capt": 32},
               {"capt": 10, "a": 11, "b": 12, "ovf": 13}, {"a": "PB1", "b": "PB2"})
    t2 = Timer(cpu, pins, "T2", 8, {"tccra": 0xB0, "tccrb": 0xB1, "tcnt": 0xB2, "ocra": 0xB3, "ocrb": 0xB4},
               cfg_8bit(PRE2), tifr2, 0x70, flags8, {"a": 7, "b": 8, "ovf": 9}, {"a": "PB3", "b": "PD3"})
    usart = USART(cpu, pins, {"udr": 0xC6, "ucsra": 0xC0, "ucsrb": 0xC1, "ucsrc": 0xC2, "ubrrl": 0xC4,
                              "ubrrh": 0xC5}, {"rx": 18, "udre": 19, "tx": 20}, "PD1", "PD0")

    def ch(admux):
        m = admux & 0xF
        if m <= 5:
            return f"PC{m}"
        return {6: "ADC6", 7: "ADC7", 8: "TEMP", 14: "VBG", 15: "GND"}.get(m)

    def ref(admux):
        return {0: "AREF", 1: "AVCC", 3: "1V1"}.get(admux >> 6, "AVCC")
    adc = ADC(cpu, {"adcl": 0x78, "adch": 0x79, "admux": 0x7C, "adcsra": 0x7A}, 21, ch, ref)
    eifr, pcifr = FlagReg(cpu, 0x3C), FlagReg(cpu, 0x3B)
    ext = ExtInt(cpu, pins, [("PD2", 1, 1), ("PD3", 2, 2)],
                 [([f"PB{i}" for i in range(8)], 0x6B, 1, 3), ([f"PC{i}" for i in range(7)], 0x6C, 2, 4),
                  ([f"PD{i}" for i in range(8)], 0x6D, 4, 5)], eifr, pcifr,
                 lambda n: (cpu.data[0x69] >> (2 * n)) & 3, 0x3D, 0x68)
    wdt = Watchdog(cpu, 0x60, 6, mcu.watchdog_reset)
    ee = EEPROM(cpu, {"eecr": 0x3F, "eedr": 0x40, "eearl": 0x41, "eearh": 0x42}, 22)
    for p in (t0, t1, t2, usart, adc, wdt, ee, ext):
        cpu.add_periph(p)
    return {"usart": usart, "adc": adc, "timers": [t0, t1, t2]}


MEGA_GPIO = [f"PB{i}" for i in range(8)] + [f"PC{i}" for i in range(7)] + [f"PD{i}" for i in range(8)]
MEGA_DIP28 = {"1": "PC6", "2": "PD0", "3": "PD1", "4": "PD2", "5": "PD3", "6": "PD4", "7": "VCC", "8": "GND",
              "9": "PB6", "10": "PB7", "11": "PD5", "12": "PD6", "13": "PD7", "14": "PB0", "15": "PB1", "16": "PB2",
              "17": "PB3", "18": "PB4", "19": "PB5", "20": "AVCC", "21": "AREF", "22": "GND", "23": "PC0",
              "24": "PC1", "25": "PC2", "26": "PC3", "27": "PC4", "28": "PC5"}
MEGA_QFP32 = {"1": "PD3", "2": "PD4", "3": "GND", "4": "VCC", "5": "GND", "6": "VCC", "7": "PB6", "8": "PB7",
              "9": "PD5", "10": "PD6", "11": "PD7", "12": "PB0", "13": "PB1", "14": "PB2", "15": "PB3", "16": "PB4",
              "17": "PB5", "18": "AVCC", "19": "ADC6", "20": "AREF", "21": "GND", "22": "ADC7", "23": "PC0",
              "24": "PC1", "25": "PC2", "26": "PC3", "27": "PC4", "28": "PC5", "29": "PC6", "30": "PD0", "31": "PD1",
              "32": "PD2", "33": "GND"}


def _mega(name, flash, ram_end, ee, vec):
    return AvrDef(name, flash, ram_end, ee, vec, MEGA_GPIO, "PC6", ("PB6", "PB7"), setup_mega, (0x53, 1),
                  (0x53, 1, 7), (2, 3, 6, 7), {"28": MEGA_DIP28, "32": MEGA_QFP32, "33": MEGA_QFP32}, 16e6)


# --------------------------------------------------------------------------- ATtiny25/45/85 and ATtiny13A

TINY_GPIO = [f"PB{i}" for i in range(6)]
TINY_8 = {"1": "PB5", "2": "PB3", "3": "PB4", "4": "GND", "5": "PB0", "6": "PB1", "7": "PB2", "8": "VCC"}


def setup_tiny85(cpu, pins, mcu) -> dict:
    cpu.add_periph(Port(cpu, pins, "B", 0x36, 0x37, 0x38, 6))
    for addr in (0x59, 0x5B, 0x35, 0x55):
        _kick_reg(cpu, addr)
    tifr = FlagReg(cpu, 0x58)
    t0 = Timer(cpu, pins, "T0", 8, {"tccra": 0x4A, "tccrb": 0x53, "tcnt": 0x52, "ocra": 0x49, "ocrb": 0x48},
               cfg_8bit(PRE01), tifr, 0x59, {"ovf": 2, "a": 16, "b": 8}, {"ovf": 5, "a": 10, "b": 11},
               {"a": "PB0", "b": "PB1"})
    t1 = Timer(cpu, pins, "T1", 8, {"tccr1": 0x50, "gtccr": 0x4C, "tcnt": 0x4F, "ocra": 0x4E, "ocrb": 0x4B,
                                    "ocr1c": 0x4D}, cfg_tiny85_t1, tifr, 0x59, {"ovf": 4, "a": 64, "b": 32},
               {"a": 3, "ovf": 4, "b": 9}, {"a": "PB1", "b": "PB4"})

    def ch(admux):
        return {0: "PB5", 1: "PB2", 2: "PB4", 3: "PB3", 12: "VBG", 13: "GND", 15: "TEMP"}.get(admux & 0xF)

    def ref(admux):
        r = ((admux >> 6) & 3) | ((admux >> 2) & 4)
        return {0: "VCC", 1: "PB0", 2: "1V1", 6: "2V56", 7: "2V56"}.get(r, "VCC")
    adc = ADC(cpu, {"adcl": 0x24, "adch": 0x25, "admux": 0x27, "adcsra": 0x26}, 8, ch, ref)
    gifr = FlagReg(cpu, 0x5A)
    ext = ExtInt(cpu, pins, [("PB2", 0x40, 1)], [(TINY_GPIO, 0x35, 0x20, 2)], gifr, gifr,
                 lambda n: cpu.data[0x55] & 3, 0x5B, None)
    wdt = Watchdog(cpu, 0x41, 12, mcu.watchdog_reset)
    ee = EEPROM(cpu, {"eecr": 0x3C, "eedr": 0x3D, "eearl": 0x3E, "eearh": 0x3F}, 6)
    for p in (t0, t1, adc, wdt, ee, ext):
        cpu.add_periph(p)
    return {"adc": adc, "timers": [t0, t1]}


def setup_tiny13(cpu, pins, mcu) -> dict:
    cpu.add_periph(Port(cpu, pins, "B", 0x36, 0x37, 0x38, 6))
    for addr in (0x59, 0x5B, 0x35, 0x55):
        _kick_reg(cpu, addr)
    tifr = FlagReg(cpu, 0x58)
    t0 = Timer(cpu, pins, "T0", 8, {"tccra": 0x4F, "tccrb": 0x53, "tcnt": 0x52, "ocra": 0x56, "ocrb": 0x49},
               cfg_8bit(PRE01), tifr, 0x59, {"ovf": 2, "a": 4, "b": 8}, {"ovf": 3, "a": 6, "b": 7},
               {"a": "PB0", "b": "PB1"})

    def ch(admux):
        return {0: "PB5", 1: "PB2", 2: "PB4", 3: "PB3"}[admux & 3]

    adc = ADC(cpu, {"adcl": 0x24, "adch": 0x25, "admux": 0x27, "adcsra": 0x26}, 9, ch,
              lambda admux: "1V1" if admux & 0x40 else "VCC")
    gifr = FlagReg(cpu, 0x5A)
    ext = ExtInt(cpu, pins, [("PB1", 0x40, 1)], [(TINY_GPIO, 0x35, 0x20, 2)], gifr, gifr,
                 lambda n: cpu.data[0x55] & 3, 0x5B, None)
    wdt = Watchdog(cpu, 0x41, 8, mcu.watchdog_reset)
    ee = EEPROM(cpu, {"eecr": 0x3C, "eedr": 0x3D, "eearl": 0x3E}, 4)
    for p in (t0, adc, wdt, ee, ext):
        cpu.add_periph(p)
    return {"adc": adc, "timers": [t0]}


def _tiny(name, flash, ram_end, ee, setup, clock):
    return AvrDef(name, flash, ram_end, ee, 1, TINY_GPIO, "PB5", (), setup, (0x55, 0x20), (0x55, 3, 3), (2,),
                  {"8": TINY_8}, clock, supply_ohms=1000.0)


CHIPS = {
    "ATMEGA328P": _mega("ATmega328P", 32768, 0x8FF, 1024, 2),
    "ATMEGA328": _mega("ATmega328P", 32768, 0x8FF, 1024, 2),
    "ATMEGA168": _mega("ATmega168", 16384, 0x4FF, 512, 2),
    "ATMEGA88": _mega("ATmega88", 8192, 0x4FF, 512, 1),
    "ATMEGA48": _mega("ATmega48", 4096, 0x2FF, 256, 1),
    "ATTINY85": _tiny("ATtiny85", 8192, 0x25F, 512, setup_tiny85, 8e6),
    "ATTINY45": _tiny("ATtiny45", 4096, 0x15F, 256, setup_tiny85, 8e6),
    "ATTINY25": _tiny("ATtiny25", 2048, 0xDF, 128, setup_tiny85, 8e6),
    "ATTINY13": _tiny("ATtiny13A", 1024, 0x9F, 64, setup_tiny13, 9.6e6),
}
_ORDER = sorted(CHIPS, key=len, reverse=True)

NANO = {"1": "PD1", "2": "PD0", "3": "RESET", "4": "GND", "5": "PD2", "6": "PD3", "7": "PD4", "8": "PD5", "9": "PD6",
        "10": "PD7", "11": "PB0", "12": "PB1", "13": "PB2", "14": "PB3", "15": "PB4", "16": "PB5", "17": "3V3",
        "18": "AREF", "19": "PC0", "20": "PC1", "21": "PC2", "22": "PC3", "23": "PC4", "24": "PC5", "25": "ADC6",
        "26": "ADC7", "27": "5V", "28": "RESET", "29": "GND", "30": "VIN"}
PRO_MINI = {"1": "PD1", "2": "PD0", "3": "RESET", "4": "GND", "5": "PD2", "6": "PD3", "7": "PD4", "8": "PD5",
            "9": "PD6", "10": "PD7", "11": "PB0", "12": "PB1", "13": "PB2", "14": "PB3", "15": "PB4", "16": "PB5",
            "17": "PC0", "18": "PC1", "19": "PC2", "20": "PC3", "21": "5V", "22": "RESET", "23": "GND", "24": "VIN"}


def chip_for(text: str) -> AvrDef | None:
    t = re.sub(r"[\s_-]", "", (text or "").upper())
    for k in _ORDER:
        if t.startswith(k):
            return CHIPS[k]
    return None


def _pins_from(pm: dict) -> dict:
    out: dict[str, list[str]] = {}
    for pad, fn in pm.items():
        out.setdefault(fn, []).append(pad)
    return out


def lookup(text: str, comp):
    """Resolution for an AVR chip on the board (None when not an AVR we emulate)."""
    from ..models import Resolution, _numbered
    chip = chip_for(text)
    if chip is None:
        return None
    n = str(len(_numbered(comp.footprint)))
    pm = chip.pinmaps.get(n)
    if pm is None:
        return Resolution("unsupported", chip.name, note=f"no {chip.name} pinout for a {n}-pin package")
    return Resolution("mcu", chip.name, {"chip": chip.name, "clock": chip.default_clock}, _pins_from(pm), "table")


def module(comp):
    from ..models import Resolution
    n = comp.footprint.name
    t = (comp.value + " " + comp.mpn).upper()
    if n.startswith("Module_Arduino_Nano"):
        return Resolution("mcu", "Arduino Nano (ATmega328P)", {"chip": "ATmega328P", "module": "nano",
                                                               "clock": 16e6, "vreg": 5.0}, _pins_from(NANO), "table")
    if n.startswith("Module_Arduino_Pro_Mini"):
        low = "3.3" in t or "3V3" in t or "8MHZ" in t
        return Resolution("mcu", f"Arduino Pro Mini {'3.3 V' if low else '5 V'} (ATmega328P)",
                          {"chip": "ATmega328P", "module": "promini", "clock": 8e6 if low else 16e6,
                           "vreg": 3.3 if low else 5.0}, _pins_from(PRO_MINI), "table", verify=True)
    return None


def chip_by_name(name: str) -> AvrDef:
    return chip_for(name) or CHIPS["ATMEGA328P"]
