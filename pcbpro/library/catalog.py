"""Catalogue of popular real parts (manufacturer part numbers) mapped to library footprints.

Each line: MPN | manufacturer | library footprint name | category | ref prefix | description.
For anything not listed here, use Import from LCSC (any of 1M+ parts by C-number) or a KiCad library.
"""
from __future__ import annotations

from ..model.footprints import LibPart

_PARTS = """
ATmega328P-AU|Microchip|TQFP-32 7x7 P0.8|Microcontrollers|U|8-bit AVR MCU, 32 KB flash (Arduino Uno chip)
ATmega328P-PU|Microchip|DIP-28 (300 mil)|Microcontrollers|U|8-bit AVR MCU, 32 KB flash, DIP
ATmega328PB-AU|Microchip|TQFP-32 7x7 P0.8|Microcontrollers|U|8-bit AVR MCU with extra peripherals
ATmega32U4-AU|Microchip|TQFP-44 10x10 P0.8|Microcontrollers|U|8-bit AVR MCU with native USB (Leonardo)
ATmega2560-16AU|Microchip|LQFP-100 14x14 P0.5|Microcontrollers|U|8-bit AVR MCU, 256 KB flash (Mega 2560)
ATmega8A-AU|Microchip|TQFP-32 7x7 P0.8|Microcontrollers|U|8-bit AVR MCU, 8 KB flash
ATtiny85-20PU|Microchip|DIP-8 (300 mil)|Microcontrollers|U|8-bit AVR MCU, 8 KB flash, DIP-8
ATtiny85-20SU|Microchip|SOIC-8 5.3 mm (208 mil)|Microcontrollers|U|8-bit AVR MCU, 8 KB flash, SOIC-8 208 mil
ATtiny13A-SSU|Microchip|SOIC-8|Microcontrollers|U|8-bit AVR MCU, 1 KB flash
ATtiny44A-SSU|Microchip|SOIC-14|Microcontrollers|U|8-bit AVR MCU, 4 KB flash
ATtiny1616-SFR|Microchip|SOIC-20 wide (7.5 mm)|Microcontrollers|U|tinyAVR 1-series MCU, 16 KB flash
ATtiny402-SSN|Microchip|SOIC-8|Microcontrollers|U|tinyAVR 0-series MCU, 4 KB flash
ATSAMD21G18A-AU|Microchip|LQFP-48 7x7 P0.5|Microcontrollers|U|ARM Cortex-M0+ MCU, 256 KB flash (Arduino Zero)
ATSAMD21E18A-AU|Microchip|TQFP-32 7x7 P0.8|Microcontrollers|U|ARM Cortex-M0+ MCU, 256 KB flash
ATSAMD51J19A-AU|Microchip|LQFP-64 10x10 P0.5|Microcontrollers|U|ARM Cortex-M4F MCU, 512 KB flash
PIC16F877A-I/P|Microchip|DIP-40 (600 mil)|Microcontrollers|U|8-bit PIC MCU, DIP-40
PIC16F628A-I/P|Microchip|DIP-18 (300 mil)|Microcontrollers|U|8-bit PIC MCU, DIP-18
PIC12F675-I/P|Microchip|DIP-8 (300 mil)|Microcontrollers|U|8-bit PIC MCU, DIP-8
PIC18F4550-I/P|Microchip|DIP-40 (600 mil)|Microcontrollers|U|8-bit PIC MCU with USB
MSP430G2553IN20|Texas Instruments|DIP-20 (300 mil)|Microcontrollers|U|16-bit ultra-low-power MCU (LaunchPad)
STM32F103C8T6|STMicroelectronics|LQFP-48 7x7 P0.5|Microcontrollers|U|ARM Cortex-M3 MCU, 64 KB flash (Blue Pill)
STM32F103RCT6|STMicroelectronics|LQFP-64 10x10 P0.5|Microcontrollers|U|ARM Cortex-M3 MCU, 256 KB flash
STM32F030F4P6|STMicroelectronics|TSSOP-20|Microcontrollers|U|ARM Cortex-M0 MCU, 16 KB flash
STM32F042F6P6|STMicroelectronics|TSSOP-20|Microcontrollers|U|ARM Cortex-M0 MCU with crystal-less USB
STM32G030F6P6|STMicroelectronics|TSSOP-20|Microcontrollers|U|ARM Cortex-M0+ MCU, 32 KB flash
STM32G431CBU6|STMicroelectronics|QFN-48 7x7 P0.5|Microcontrollers|U|ARM Cortex-M4F MCU, 128 KB flash (UFQFPN-48)
STM32F401CCU6|STMicroelectronics|QFN-48 7x7 P0.5|Microcontrollers|U|ARM Cortex-M4F MCU, 256 KB flash (Black Pill)
STM32F411CEU6|STMicroelectronics|QFN-48 7x7 P0.5|Microcontrollers|U|ARM Cortex-M4F MCU, 512 KB flash (Black Pill)
STM32F405RGT6|STMicroelectronics|LQFP-64 10x10 P0.5|Microcontrollers|U|ARM Cortex-M4F MCU, 1 MB flash
STM32F407VGT6|STMicroelectronics|LQFP-100 14x14 P0.5|Microcontrollers|U|ARM Cortex-M4F MCU, 1 MB flash, Ethernet
STM32H743VIT6|STMicroelectronics|LQFP-100 14x14 P0.5|Microcontrollers|U|ARM Cortex-M7 MCU, 480 MHz, 2 MB flash
STM32L432KCU6|STMicroelectronics|QFN-32 5x5 P0.5|Microcontrollers|U|ARM Cortex-M4 ultra-low-power MCU (UFQFPN-32)
GD32F103C8T6|GigaDevice|LQFP-48 7x7 P0.5|Microcontrollers|U|ARM Cortex-M3 MCU (STM32F103 compatible)
CH32V003F4P6|WCH|TSSOP-20|Microcontrollers|U|RISC-V MCU, 16 KB flash, very low cost
CH32V003J4M6|WCH|SOIC-8|Microcontrollers|U|RISC-V MCU in SOP-8
CH552G|WCH|SOIC-16|Microcontrollers|U|8051 MCU with USB
ESP32-C3|Espressif|QFN-32 5x5 P0.5|Wireless SoCs|U|RISC-V Wi-Fi + BLE SoC (verify exposed pad size)
ESP8266EX|Espressif|QFN-32 5x5 P0.5|Wireless SoCs|U|Wi-Fi SoC (verify exposed pad size)
nRF52832-QFAA|Nordic Semiconductor|QFN-48 6x6 P0.4|Wireless SoCs|U|Bluetooth LE SoC, ARM Cortex-M4F
nRF24L01P|Nordic Semiconductor|QFN-20 4x4 P0.5|Wireless SoCs|U|2.4 GHz transceiver
CC1101RGPR|Texas Instruments|QFN-20 4x4 P0.5|Wireless SoCs|U|Sub-GHz transceiver
ESP32-WROOM-32E|Espressif|ESP32-WROOM-32 module|Modules|U|ESP32 Wi-Fi + Bluetooth module, PCB antenna
ESP32-WROOM-32UE|Espressif|ESP32-WROOM-32 module|Modules|U|ESP32 module with U.FL antenna connector
ESP-12F|Ai-Thinker|ESP-12F (ESP8266) module|Modules|U|ESP8266 Wi-Fi module
CH340G|WCH|SOIC-16|Interface|U|USB to UART bridge (needs 12 MHz crystal)
CH340C|WCH|SOIC-16|Interface|U|USB to UART bridge, internal oscillator
CH340N|WCH|SOIC-8|Interface|U|USB to UART bridge, SOP-8
CH340E|WCH|MSOP-10|Interface|U|USB to UART bridge, MSOP-10
CP2102N-A02-GQFN28|Silicon Labs|QFN-28 5x5 P0.5|Interface|U|USB to UART bridge
FT232RL|FTDI|SSOP-28|Interface|U|USB to UART bridge
FT231XS|FTDI|SSOP-20|Interface|U|USB to UART bridge
MAX232CPE|Texas Instruments|DIP-16 (300 mil)|Interface|U|Dual RS-232 driver/receiver
MAX232DR|Texas Instruments|SOIC-16|Interface|U|Dual RS-232 driver/receiver
MAX3232ESE|Maxim|SOIC-16|Interface|U|3 V RS-232 transceiver
MAX485ESA|Maxim|SOIC-8|Interface|U|RS-485 / RS-422 transceiver
SP3485EN|MaxLinear|SOIC-8|Interface|U|3.3 V RS-485 transceiver
SN65HVD230DR|Texas Instruments|SOIC-8|Interface|U|3.3 V CAN transceiver
TJA1050T|NXP|SOIC-8|Interface|U|High-speed CAN transceiver
MCP2551-I/SN|Microchip|SOIC-8|Interface|U|High-speed CAN transceiver
MCP2515-I/SO|Microchip|SOIC-18 wide (7.5 mm)|Interface|U|Stand-alone CAN controller with SPI
MCP23017-E/SO|Microchip|SOIC-28 wide (7.5 mm)|Interface|U|16-bit I2C I/O expander
MCP23017-E/SP|Microchip|DIP-28 (300 mil)|Interface|U|16-bit I2C I/O expander, DIP
PCF8574T|NXP|SOIC-16 wide (7.5 mm)|Interface|U|8-bit I2C I/O expander
PCA9685PW|NXP|TSSOP-28|Interface|U|16-channel 12-bit PWM / LED driver, I2C
TCA9548APWR|Texas Instruments|TSSOP-24|Interface|U|8-channel I2C multiplexer
TXS0108EPWR|Texas Instruments|TSSOP-20|Interface|U|8-bit bidirectional level translator
W5500|WIZnet|LQFP-48 7x7 P0.5|Interface|U|Hardwired TCP/IP Ethernet controller
ENC28J60-I/SO|Microchip|SOIC-28 wide (7.5 mm)|Interface|U|SPI Ethernet controller
LAN8720A-CP|Microchip|QFN-24 4x4 P0.5|Interface|U|10/100 Ethernet PHY (RMII)
USBLC6-2SC6|STMicroelectronics|SOT-23-6|Protection|U|USB ESD protection
74HC595D|Nexperia|SOIC-16|Logic|U|8-bit shift register with output latches
74HC595N|Texas Instruments|DIP-16 (300 mil)|Logic|U|8-bit shift register, DIP
74HC595PW|Nexperia|TSSOP-16|Logic|U|8-bit shift register, TSSOP
74HC165D|Nexperia|SOIC-16|Logic|U|8-bit parallel-in shift register
74HC04D|Nexperia|SOIC-14|Logic|U|Hex inverter
74HC00D|Nexperia|SOIC-14|Logic|U|Quad 2-input NAND
74HC08D|Nexperia|SOIC-14|Logic|U|Quad 2-input AND
74HC14D|Nexperia|SOIC-14|Logic|U|Hex Schmitt-trigger inverter
74HC32D|Nexperia|SOIC-14|Logic|U|Quad 2-input OR
74HC138D|Nexperia|SOIC-16|Logic|U|3-to-8 line decoder
74HC245D|Nexperia|SOIC-20 wide (7.5 mm)|Logic|U|Octal bus transceiver
74HC4051D|Nexperia|SOIC-16|Logic|U|8-channel analog multiplexer
74HC4067D|Nexperia|SOIC-24 wide (7.5 mm)|Logic|U|16-channel analog multiplexer
74LVC1G14GW|Nexperia|SC-70-5 (SOT-353)|Logic|U|Single Schmitt-trigger inverter
74LVC1G08GW|Nexperia|SC-70-5 (SOT-353)|Logic|U|Single 2-input AND
SN74LVC1T45DCKR|Texas Instruments|SC-70-6 (SOT-363)|Logic|U|Single-bit level translator
CD4017BE|Texas Instruments|DIP-16 (300 mil)|Logic|U|Decade counter / divider
CD4051BM|Texas Instruments|SOIC-16|Logic|U|8-channel analog multiplexer
CD4060BE|Texas Instruments|DIP-16 (300 mil)|Logic|U|14-stage ripple counter with oscillator
NE555P|Texas Instruments|DIP-8 (300 mil)|Timers|U|555 timer, DIP
NE555DR|Texas Instruments|SOIC-8|Timers|U|555 timer, SOIC
TLC555CDR|Texas Instruments|SOIC-8|Timers|U|CMOS 555 timer
NE556N|Texas Instruments|DIP-14 (300 mil)|Timers|U|Dual 555 timer
LM358DR|Texas Instruments|SOIC-8|Amplifiers|U|Dual op-amp
LM358P|Texas Instruments|DIP-8 (300 mil)|Amplifiers|U|Dual op-amp, DIP
LM324DR|Texas Instruments|SOIC-14|Amplifiers|U|Quad op-amp
LM324N|Texas Instruments|DIP-14 (300 mil)|Amplifiers|U|Quad op-amp, DIP
TL072CP|Texas Instruments|DIP-8 (300 mil)|Amplifiers|U|Dual JFET-input op-amp (audio)
TL072CDR|Texas Instruments|SOIC-8|Amplifiers|U|Dual JFET-input op-amp
TL074CDR|Texas Instruments|SOIC-14|Amplifiers|U|Quad JFET-input op-amp
NE5532P|Texas Instruments|DIP-8 (300 mil)|Amplifiers|U|Dual low-noise audio op-amp
NE5532DR|Texas Instruments|SOIC-8|Amplifiers|U|Dual low-noise audio op-amp
OPA2134PA|Texas Instruments|DIP-8 (300 mil)|Amplifiers|U|High-performance audio op-amp
OPA2134UA|Texas Instruments|SOIC-8|Amplifiers|U|High-performance audio op-amp
MCP6002-I/SN|Microchip|SOIC-8|Amplifiers|U|Dual rail-to-rail op-amp
MCP6001T-I/OT|Microchip|SOT-23-5|Amplifiers|U|Single rail-to-rail op-amp
LMV321IDBVR|Texas Instruments|SOT-23-5|Amplifiers|U|Single low-voltage op-amp
LM393DR|Texas Instruments|SOIC-8|Amplifiers|U|Dual comparator
LM339DR|Texas Instruments|SOIC-14|Amplifiers|U|Quad comparator
LM386N-1|Texas Instruments|DIP-8 (300 mil)|Audio|U|Low-voltage audio power amplifier
LM386MX-1|Texas Instruments|SOIC-8|Audio|U|Low-voltage audio power amplifier
PAM8403|Diodes Inc.|SOIC-16|Audio|U|3 W stereo class-D amplifier
MAX98357AETE+T|Analog Devices|QFN-16 3x3 P0.5|Audio|U|I2S class-D amplifier (verify exposed pad)
PCM5102APWR|Texas Instruments|TSSOP-20|Audio|U|Stereo I2S audio DAC
WM8960CGEFL|Cirrus Logic|QFN-32 5x5 P0.5|Audio|U|Stereo codec with class-D speaker driver
INA219AIDR|Texas Instruments|SOIC-8|Sensors|U|I2C current / power monitor
INA226AIDGSR|Texas Instruments|MSOP-10|Sensors|U|I2C current / power monitor, 16-bit
ADS1115IDGSR|Texas Instruments|MSOP-10|Data converters|U|16-bit 4-channel I2C ADC
MCP3008-I/SL|Microchip|SOIC-16|Data converters|U|10-bit 8-channel SPI ADC
MCP3008-I/P|Microchip|DIP-16 (300 mil)|Data converters|U|10-bit 8-channel SPI ADC, DIP
MCP4725A0T-E/CH|Microchip|SOT-23-6|Data converters|U|12-bit I2C DAC
HX711|Avia Semiconductor|SOIC-16|Data converters|U|24-bit ADC for load cells
ACS712ELCTR-05B-T|Allegro|SOIC-8|Sensors|U|Hall-effect current sensor, +/-5 A
MAX6675ISA+|Maxim|SOIC-8|Sensors|U|K-type thermocouple to digital
MAX31855KASA+|Maxim|SOIC-8|Sensors|U|K-type thermocouple to digital, cold junction
MPU-6050|TDK InvenSense|QFN-24 4x4 P0.5|Sensors|U|6-axis accelerometer + gyroscope (verify exposed pad)
MPU-9250|TDK InvenSense|QFN-24 3x3 P0.4|Sensors|U|9-axis motion sensor (verify exposed pad)
DS18B20|Analog Devices|TO-92 inline|Sensors|U|1-Wire digital temperature sensor
LM35DZ|Texas Instruments|TO-92 inline|Sensors|U|Analog temperature sensor, 10 mV/C
TMP36GT9Z|Analog Devices|TO-92 inline|Sensors|U|Analog temperature sensor
LM4040DIM3-2.5|Texas Instruments|SOT-23|Voltage references|U|2.5 V shunt reference
TL431AIDBZR|Texas Instruments|SOT-23|Voltage references|U|Adjustable shunt regulator
TL431ACLP|Texas Instruments|TO-92 inline|Voltage references|U|Adjustable shunt regulator, TO-92
W25Q32JVSSIQ|Winbond|SOIC-8 5.3 mm (208 mil)|Memory|U|32 Mbit SPI NOR flash
W25Q64JVSSIQ|Winbond|SOIC-8 5.3 mm (208 mil)|Memory|U|64 Mbit SPI NOR flash
W25Q128JVSIQ|Winbond|SOIC-8 5.3 mm (208 mil)|Memory|U|128 Mbit SPI NOR flash
AT24C02C-SSHM-T|Microchip|SOIC-8|Memory|U|2 Kbit I2C EEPROM
24LC256-I/SN|Microchip|SOIC-8|Memory|U|256 Kbit I2C EEPROM
24LC256-I/P|Microchip|DIP-8 (300 mil)|Memory|U|256 Kbit I2C EEPROM, DIP
23LC1024-I/SN|Microchip|SOIC-8|Memory|U|1 Mbit SPI SRAM
FM24CL64B-G|Infineon|SOIC-8|Memory|U|64 Kbit I2C F-RAM
DS3231SN#|Analog Devices|SOIC-16 wide (7.5 mm)|Real-time clocks|U|Extremely accurate I2C RTC with TCXO
DS3231MZ+|Analog Devices|SOIC-8|Real-time clocks|U|Accurate I2C RTC with MEMS resonator
DS1307Z+|Analog Devices|SOIC-8|Real-time clocks|U|I2C real-time clock
DS1307+|Analog Devices|DIP-8 (300 mil)|Real-time clocks|U|I2C real-time clock, DIP
PCF8563T|NXP|SOIC-8|Real-time clocks|U|Low-power I2C RTC
MAX7219CNG|Analog Devices|DIP-24 (300 mil)|Display drivers|U|8-digit LED display driver
MAX7219CWG|Analog Devices|SOIC-24 wide (7.5 mm)|Display drivers|U|8-digit LED display driver, SOIC
TM1637|Titan Micro|SOIC-20 wide (7.5 mm)|Display drivers|U|LED display driver with key scan (verify package)
ULN2003AD|Texas Instruments|SOIC-16|Drivers|U|7-channel Darlington array
ULN2003AN|Texas Instruments|DIP-16 (300 mil)|Drivers|U|7-channel Darlington array, DIP
ULN2803A|Texas Instruments|DIP-18 (300 mil)|Drivers|U|8-channel Darlington array
L293D|STMicroelectronics|DIP-16 (300 mil)|Motor drivers|U|Quad half-H driver
DRV8833PWPR|Texas Instruments|HTSSOP-16 (exposed pad)|Motor drivers|U|Dual H-bridge motor driver
DRV8825PWPR|Texas Instruments|HTSSOP-28 (exposed pad)|Motor drivers|U|Stepper motor driver
DRV8871DDAR|Texas Instruments|SOIC-8 with exposed pad|Motor drivers|U|3.6 A brushed DC motor driver
A4988SETTR-T|Allegro|QFN-28 5x5 P0.5|Motor drivers|U|Stepper motor driver (verify exposed pad)
TMC2209-LA|Trinamic|QFN-28 5x5 P0.5|Motor drivers|U|Silent stepper motor driver (verify exposed pad)
AMS1117-3.3|Advanced Monolithic Systems|SOT-223 regulator|Power|U|1 A LDO regulator, 3.3 V
AMS1117-5.0|Advanced Monolithic Systems|SOT-223 regulator|Power|U|1 A LDO regulator, 5 V
LM1117IMP-3.3|Texas Instruments|SOT-223 regulator|Power|U|800 mA LDO regulator, 3.3 V
LD1117S33TR|STMicroelectronics|SOT-223 regulator|Power|U|800 mA LDO regulator, 3.3 V
AP2112K-3.3TRG1|Diodes Inc.|SOT-23-5|Power|U|600 mA LDO regulator, 3.3 V
XC6206P332MR|Torex|SOT-23|Power|U|200 mA LDO regulator, 3.3 V
MCP1700T-3302E/TT|Microchip|SOT-23|Power|U|250 mA low-quiescent LDO, 3.3 V
HT7333-A|Holtek|SOT-89-3|Power|U|250 mA low-quiescent LDO, 3.3 V
L7805CV|STMicroelectronics|TO-220-3 vertical|Power|U|1.5 A linear regulator, 5 V
L7812CV|STMicroelectronics|TO-220-3 vertical|Power|U|1.5 A linear regulator, 12 V
L7905CV|STMicroelectronics|TO-220-3 vertical|Power|U|Negative linear regulator, -5 V
LM317T|Texas Instruments|TO-220-3 vertical|Power|U|1.5 A adjustable linear regulator
LM317DCYR|Texas Instruments|SOT-223 regulator|Power|U|Adjustable linear regulator, SOT-223
LM2596S-5.0|Texas Instruments|TO-263-5 (D2PAK)|Power|U|3 A step-down (buck) regulator, 5 V
LM2596S-ADJ|Texas Instruments|TO-263-5 (D2PAK)|Power|U|3 A step-down (buck) regulator, adjustable
LM2576S-ADJ|Texas Instruments|TO-263-5 (D2PAK)|Power|U|3 A step-down (buck) regulator
XL6009E1|XLSEMI|TO-263-5 (D2PAK)|Power|U|4 A step-up (boost) converter
MP1584EN-LF-Z|Monolithic Power|SOIC-8 with exposed pad|Power|U|3 A step-down converter
MT3608|Aerosemi|SOT-23-6|Power|U|2 A step-up (boost) converter
SX1308|Suosemi|SOT-23-6|Power|U|2 A step-up converter
TPS563200DDCR|Texas Instruments|SOT-23-6|Power|U|3 A synchronous buck converter
TPS54331DR|Texas Instruments|SOIC-8|Power|U|3 A step-down converter
TPS5430DDAR|Texas Instruments|SOIC-8 with exposed pad|Power|U|3 A step-down converter
TLV62569DBVR|Texas Instruments|SOT-23-5|Power|U|2 A synchronous buck converter
AP63203WU-7|Diodes Inc.|SOT-23-6|Power|U|2 A synchronous buck converter, 3.3 V
MC34063ADR|Texas Instruments|SOIC-8|Power|U|Buck / boost / inverting DC-DC controller
TP4056|NanJing Top Power|SOIC-8 with exposed pad|Battery management|U|1 A Li-ion charger
MCP73831T-2ACI/OT|Microchip|SOT-23-5|Battery management|U|500 mA Li-ion / Li-Po charger
LTC4054ES5-4.2|Analog Devices|SOT-23-5|Battery management|U|800 mA Li-ion charger
BQ24075RGTR|Texas Instruments|QFN-16 3x3 P0.5|Battery management|U|Li-ion charger with power path (verify exposed pad)
DW01A|Fortune Semiconductor|SOT-23-6|Battery management|U|1-cell Li-ion protection IC
FS8205A|Fortune Semiconductor|TSSOP-8|Battery management|Q|Dual N-MOSFET for battery protection
IP5306|Injoinic|SOIC-8 with exposed pad|Battery management|U|Power bank SoC (charger + boost)
2N7002|Nexperia|SOT-23|MOSFETs|Q|N-MOSFET 60 V 300 mA
BSS138|onsemi|SOT-23|MOSFETs|Q|N-MOSFET 50 V 220 mA (level shifting)
AO3400A|Alpha & Omega|SOT-23|MOSFETs|Q|N-MOSFET 30 V 5.7 A, logic level
AO3401A|Alpha & Omega|SOT-23|MOSFETs|Q|P-MOSFET -30 V -4 A
SI2302CDS|Vishay|SOT-23|MOSFETs|Q|N-MOSFET 20 V 2.6 A
IRLML6344TRPBF|Infineon|SOT-23|MOSFETs|Q|N-MOSFET 30 V 5 A, logic level
DMG2305UX-7|Diodes Inc.|SOT-23|MOSFETs|Q|P-MOSFET -20 V -4.2 A
AO4407A|Alpha & Omega|SOIC-8|MOSFETs|Q|P-MOSFET -30 V -12 A
AO4406A|Alpha & Omega|SOIC-8|MOSFETs|Q|N-MOSFET 30 V 13 A
IRF7404TRPBF|Infineon|SOIC-8|MOSFETs|Q|P-MOSFET -20 V -6.7 A
CSD17578Q5A|Texas Instruments|PowerPAK SO-8 5x6 (DFN5x6)|MOSFETs|Q|N-MOSFET 30 V, 5x6 mm SON
BSC014N04LS|Infineon|PowerPAK SO-8 5x6 (DFN5x6)|MOSFETs|Q|N-MOSFET 40 V 1.4 mOhm, SuperSO8
IRLZ44NPBF|Infineon|TO-220-3 vertical|MOSFETs|Q|N-MOSFET 55 V 47 A, logic level
IRF540NPBF|Infineon|TO-220-3 vertical|MOSFETs|Q|N-MOSFET 100 V 33 A
IRF3205PBF|Infineon|TO-220-3 vertical|MOSFETs|Q|N-MOSFET 55 V 110 A
IRF9540NPBF|Infineon|TO-220-3 vertical|MOSFETs|Q|P-MOSFET -100 V -23 A
IRFZ44NPBF|Infineon|TO-220-3 vertical|MOSFETs|Q|N-MOSFET 55 V 49 A
IRLR024NTRPBF|Infineon|TO-252 (DPAK)|MOSFETs|Q|N-MOSFET 55 V 17 A, DPAK
IRF3205STRLPBF|Infineon|TO-263-3 (D2PAK)|MOSFETs|Q|N-MOSFET 55 V 110 A, D2PAK
2N7000|onsemi|TO-92 inline|MOSFETs|Q|N-MOSFET 60 V 200 mA, TO-92
BS170|onsemi|TO-92 inline|MOSFETs|Q|N-MOSFET 60 V 500 mA, TO-92
MMBT3904|onsemi|SOT-23|BJTs|Q|NPN 40 V 200 mA
MMBT3906|onsemi|SOT-23|BJTs|Q|PNP -40 V -200 mA
MMBT2222A|onsemi|SOT-23|BJTs|Q|NPN 40 V 600 mA
BC847B|Nexperia|SOT-23|BJTs|Q|NPN 45 V 100 mA
BC857B|Nexperia|SOT-23|BJTs|Q|PNP -45 V -100 mA
S8050|Jiangsu Changjing|SOT-23|BJTs|Q|NPN 25 V 500 mA
S8550|Jiangsu Changjing|SOT-23|BJTs|Q|PNP -25 V -500 mA
2N3904|onsemi|TO-92 inline|BJTs|Q|NPN 40 V 200 mA, TO-92
2N3906|onsemi|TO-92 inline|BJTs|Q|PNP -40 V -200 mA, TO-92
PN2222A|onsemi|TO-92 inline|BJTs|Q|NPN 40 V 1 A, TO-92
BC547B|onsemi|TO-92 inline|BJTs|Q|NPN 45 V 100 mA, TO-92
BC557B|onsemi|TO-92 inline|BJTs|Q|PNP -45 V -100 mA, TO-92
TIP120|onsemi|TO-220-3 vertical|BJTs|Q|NPN Darlington 60 V 5 A
TIP122|onsemi|TO-220-3 vertical|BJTs|Q|NPN Darlington 100 V 5 A
TIP31C|onsemi|TO-220-3 vertical|BJTs|Q|NPN 100 V 3 A
TIP42C|onsemi|TO-220-3 vertical|BJTs|Q|PNP -100 V -6 A
BD139|STMicroelectronics|TO-126|BJTs|Q|NPN 80 V 1.5 A
BD140|STMicroelectronics|TO-126|BJTs|Q|PNP -80 V -1.5 A
1N4148|onsemi|Diode DO-35|Diodes|D|Small-signal switching diode 100 V
1N4148W-7-F|Diodes Inc.|Diode SOD-123|Diodes|D|Small-signal switching diode, SOD-123
1N4148WS|Diodes Inc.|Diode SOD-323|Diodes|D|Small-signal switching diode, SOD-323
1N4001|onsemi|Diode DO-41|Diodes|D|1 A 50 V rectifier
1N4007|onsemi|Diode DO-41|Diodes|D|1 A 1000 V rectifier
1N5819|onsemi|Diode DO-41|Diodes|D|1 A 40 V Schottky
1N5822|onsemi|Diode DO-201AD|Diodes|D|3 A 40 V Schottky
1N5408|onsemi|Diode DO-201AD|Diodes|D|3 A 1000 V rectifier
SS14|onsemi|Diode SMA|Diodes|D|1 A 40 V Schottky, SMA
SS34|onsemi|Diode SMA|Diodes|D|3 A 40 V Schottky, SMA
M7|Various|Diode SMA|Diodes|D|1 A 1000 V rectifier (1N4007 SMD)
US1M|onsemi|Diode SMA|Diodes|D|1 A 1000 V ultrafast rectifier
B5819W|Diodes Inc.|Diode SOD-123|Diodes|D|1 A 40 V Schottky, SOD-123
BAT54|Nexperia|SOT-23|Diodes|D|Schottky diode 30 V, SOT-23
BAT54S|Nexperia|SOT-23|Diodes|D|Dual series Schottky, SOT-23
BAV99|Nexperia|SOT-23|Diodes|D|Dual series switching diode
BZX84C3V3|Nexperia|SOT-23|Diodes|D|3.3 V Zener, SOT-23
BZT52C5V1|Diodes Inc.|Diode SOD-123|Diodes|D|5.1 V Zener, SOD-123
1N4733A|onsemi|Diode DO-41|Diodes|D|5.1 V 1 W Zener
SMAJ5.0A|Littelfuse|Diode SMA|Protection|D|5 V TVS diode 400 W
SMBJ5.0A|Littelfuse|Diode SMB|Protection|D|5 V TVS diode 600 W
SMBJ24A|Littelfuse|Diode SMB|Protection|D|24 V TVS diode 600 W
SMCJ24A|Littelfuse|Diode SMC|Protection|D|24 V TVS diode 1500 W
P6KE6.8A|Littelfuse|Diode DO-15|Protection|D|6.8 V TVS diode 600 W
ESD5Z5.0T1G|onsemi|Diode SOD-523|Protection|D|5 V ESD protection diode
PC817C|Sharp|Optocoupler DIP-4|Optocouplers|U|Transistor-output optocoupler
PC817C-SMD|Sharp|Optocoupler SMD-4 (wide)|Optocouplers|U|Transistor-output optocoupler, SMD
TLP291|Toshiba|Optocoupler SOP-4|Optocouplers|U|Transistor-output optocoupler, SOP-4
4N25|Vishay|Optocoupler DIP-6|Optocouplers|U|Transistor-output optocoupler with base
MOC3021|onsemi|Optocoupler DIP-6|Optocouplers|U|Random-phase triac driver
6N137|Broadcom|DIP-8 (300 mil)|Optocouplers|U|High-speed 10 Mbit/s optocoupler
WS2812B|Worldsemi|WS2812B 5050 addressable|LEDs|D|Addressable RGB LED (NeoPixel)
SK6812MINI-E|OPSCO|SK6812MINI 3535 addressable|LEDs|D|Addressable RGB LED 3535
"""

# footprint overrides for parts whose land pattern differs from the generic library entry
_SPECIAL = {
    "RP2040": ("Raspberry Pi", "Microcontrollers", "U", "Dual ARM Cortex-M0+ MCU (QFN-56 7x7, 3.2 mm exposed pad)",
               lambda: __import__("pcbpro.model.footprints", fromlist=["qfn"]).qfn(56, 7.0, 0.4, 3.2)),
}


def catalog_parts(by_name: dict) -> list[LibPart]:
    """Build catalogue LibParts. `by_name` maps library part names to LibParts (for footprint factories)."""
    out = []
    for line in _PARTS.strip().splitlines():
        mpn, mfr, fp_name, cat, prefix, desc = [s.strip() for s in line.split("|")]
        base = by_name.get(fp_name)
        if base is None:
            continue
        out.append(LibPart(f"Parts catalog/{cat}", mpn, prefix, mpn, base.factory,
                           f"{desc} {base.keywords} {fp_name}".lower(), mpn=mpn, manufacturer=mfr,
                           description=f"{desc}. Footprint: {fp_name}.", source="catalog"))
    for mpn, (mfr, cat, prefix, desc, factory) in _SPECIAL.items():
        out.append(LibPart(f"Parts catalog/{cat}", mpn, prefix, mpn, factory, desc.lower(), mpn=mpn, manufacturer=mfr,
                           description=desc, source="catalog"))
    return out


def unresolved(by_name: dict) -> list[str]:
    """Catalogue lines whose footprint name is missing from the library (used by tests)."""
    bad = []
    for line in _PARTS.strip().splitlines():
        fp_name = line.split("|")[2].strip()
        if fp_name not in by_name:
            bad.append(line)
    return bad
