# Microcontrollers and firmware

AVR microcontrollers on the board run your **real compiled firmware**, cycle by cycle, wired into the circuit simulation. The LED your sketch blinks blinks on the board, a button on the board reaches `digitalRead`, `analogRead` reads the pot's real voltage, and `Serial.print` shows up in a serial monitor.

## Supported chips

| Chip | Flash | Notes |
|---|---|---|
| ATmega328P | 32 KB | The Arduino Uno and Nano chip |
| ATmega168, ATmega88, ATmega48 | 16, 8, 4 KB | Same family, smaller memories |
| ATtiny85, ATtiny45, ATtiny25 | 8, 4, 2 KB | 8-pin, internal 8 MHz clock by default |
| ATtiny13A | 1 KB | 9.6 MHz internal clock |
| Arduino Nano | | An ATmega328P module, with the Nano's pin labels |
| Arduino Pro Mini (5 V and 3.3 V) | | An ATmega328P module at 16 or 8 MHz |

The chip is recognised from the part's value, MPN or footprint (the parts catalogue's ATmega328P, or the module footprints in the Library). Memories, I/O maps, interrupt vectors, peripherals and package pinouts come from the Microchip datasheets.

## Loading firmware

1. Build your firmware to an Intel HEX file. In the Arduino IDE, **Sketch › Export compiled binary** writes one next to the sketch; with avr-gcc, `avr-objcopy -O ihex firmware.elf firmware.hex`.
2. Select the chip on the board and use **Simulate › Load firmware (.hex) for a microcontroller…**, or click **Load .hex…** next to the chip in the Simulation panel.
3. Press **Run** (F5).

When you rebuild, PCBPro sees the file change and reloads it (restarting the simulation if it's running), so the edit-compile-run loop needs no clicks in PCBPro. The firmware itself is saved in the project along with its path, so a project you send someone runs as it did for you.

The clock is set next to the chip in the Simulation panel (1, 8, 9.6, 12, 16 or 20 MHz, or any value you type), as the fuses and the crystal would set it on the real board. Pick the clock your firmware was compiled for (`F_CPU`).

## What the emulator covers

- **The CPU.** The full AVRe+ instruction set used by the ATmega and ATtiny parts, with exact cycle counts.
- **GPIO.** Ports, pull-ups, and the toggle-by-writing-PIN trick. Each pin drives the circuit as a real output stage, and reads the circuit's voltage against the input thresholds.
- **Timers and PWM.** Timers 0, 1 and 2 (or the ATtiny's), with their modes, prescalers, compare outputs and PWM, so `analogWrite` dims an LED.
- **The USART.** `Serial` in both directions, through the serial monitor.
- **The ADC.** `analogRead` converts the pin's real voltage from the circuit against the reference.
- **Interrupts.** External and pin-change interrupts, timer and USART interrupts.
- **The watchdog** and **the EEPROM**.
- **Sleep.** `SLEEP` fast-forwards to the next event, so firmware that sleeps runs faster than real time.

Peripherals are computed lazily from the cycle counter: the CPU only stops to service one at the cycle of its next event (a timer match, a UART byte, an ADC result).

## WS2812 / NeoPixel LEDs

WS2812B and SK6812 LEDs on the board are decoded from the data pin's real timing, chain by chain, so the LEDs show the colours your firmware sends, on the canvas and in the 3D view.

## The serial monitor

**Simulate › Serial monitor…** (or **Serial monitor** in the panel) shows everything the chip sends, and has a line to send text back, with the line ending of your choice (newline, none, or CR+LF), like the Arduino IDE's.

## How the co-simulation works

The CPU runs ahead of the circuit in short quanta. It samples its input pins from the latest analog solution, executes up to the end of the quantum, and records every pin change at its exact cycle. The analog engine then catches up, landing exactly on each recorded pin change and switching the pin's driver from there. That keeps the timing exact without solving the circuit at every clock cycle.

## Speed

A busy 16 MHz AVR plus its circuit runs at about a third of real time on a typical PC; firmware that sleeps or waits in `delay()` runs faster. The Simulation panel shows the live speed. Timing inside the simulation is always exact: `delay(500)` is 500 ms of circuit time.

## Not covered

SPI and I2C (TWI) peripherals, other microcontroller families (ESP32, RP2040, STM32 and so on) and I2C or SPI devices on the board aren't simulated; they're shown hatched with their pins left open. The bootloader isn't needed: the `.hex` is loaded straight into flash.
