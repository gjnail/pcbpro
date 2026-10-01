"""Cross-check built-in footprints against reference footprints (the official KiCad library).

The KiCad library footprints are built from manufacturer datasheets, so comparing land patterns pad
by pad is an automated "check against the datasheet". Footprints are aligned (rotation in 90 degree
steps + translation, pads matched by position) and compared for pad position, size, drill and
numbering.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from ..model.board import Footprint, Pad
from ..model.geometry import rotate_point

# built-in library part name -> KiCad "library:footprint" reference
REFERENCES = {
    # passives
    "Resistor 0402": "Resistor_SMD:R_0402_1005Metric", "Resistor 0603": "Resistor_SMD:R_0603_1608Metric",
    "Resistor 0805": "Resistor_SMD:R_0805_2012Metric", "Resistor 1206": "Resistor_SMD:R_1206_3216Metric",
    "Resistor 2512": "Resistor_SMD:R_2512_6332Metric", "Capacitor 0402": "Capacitor_SMD:C_0402_1005Metric",
    "Capacitor 0805": "Capacitor_SMD:C_0805_2012Metric", "Capacitor 1210": "Capacitor_SMD:C_1210_3225Metric",
    "Tantalum case A (3216-18)": "Capacitor_Tantalum_SMD:CP_EIA-3216-18_Kemet-A",
    "Tantalum case B (3528-21)": "Capacitor_Tantalum_SMD:CP_EIA-3528-21_Kemet-B",
    "Tantalum case C (6032-28)": "Capacitor_Tantalum_SMD:CP_EIA-6032-28_Kemet-C",
    "Tantalum case D (7343-31)": "Capacitor_Tantalum_SMD:CP_EIA-7343-31_Kemet-D",
    "Electrolytic SMD 6.3x5.4": "Capacitor_SMD:CP_Elec_6.3x5.4", "Electrolytic SMD 8x10": "Capacitor_SMD:CP_Elec_8x10",
    "Electrolytic D5 P2 H11": "Capacitor_THT:CP_Radial_D5.0mm_P2.00mm",
    "Electrolytic D8 P3.5 H11.5": "Capacitor_THT:CP_Radial_D8.0mm_P3.50mm",
    "Resistor axial 1/4 W P10.16": "Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal",
    "Diode DO-41": "Diode_THT:D_DO-41_SOD81_P10.16mm_Horizontal",
    "Diode DO-35": "Diode_THT:D_DO-35_SOD27_P7.62mm_Horizontal",
    "Trimmer 3296W multi-turn": "Potentiometer_THT:Potentiometer_Bourns_3296W_Vertical",
    "Fuse holder 5x20 mm (clips)": "Fuse:Fuseholder_Clip-5x20mm_Littelfuse_111_Inline_P20.00x5.00mm_D1.05mm_Horizontal",
    # semiconductors
    "Diode SOD-123": "Diode_SMD:D_SOD-123", "Diode SOD-323": "Diode_SMD:D_SOD-323", "Diode SMA": "Diode_SMD:D_SMA",
    "Diode SMB": "Diode_SMD:D_SMB", "Diode SMC": "Diode_SMD:D_SMC",
    "SOT-23": "Package_TO_SOT_SMD:SOT-23", "SOT-23-5": "Package_TO_SOT_SMD:SOT-23-5",
    "SOT-23-6": "Package_TO_SOT_SMD:SOT-23-6", "SOT-223": "Package_TO_SOT_SMD:SOT-223-3_TabPin2",
    "SOT-89-3": "Package_TO_SOT_SMD:SOT-89-3", "SOT-89-5": "Package_TO_SOT_SMD:SOT-89-5",
    "SOT-323 (SC-70)": "Package_TO_SOT_SMD:SOT-323_SC-70", "SC-70-6 (SOT-363)": "Package_TO_SOT_SMD:SOT-363_SC-70-6",
    "SC-70-5 (SOT-353)": "Package_TO_SOT_SMD:SOT-353_SC-70-5", "SOT-523": "Package_TO_SOT_SMD:SOT-523",
    "SOT-563": "Package_TO_SOT_SMD:SOT-563", "SOT-23-8": "Package_TO_SOT_SMD:SOT-23-8",
    "TO-263-2 (D2PAK)": "Package_TO_SOT_SMD:TO-263-2",
    "TO-252 (DPAK)": "Package_TO_SOT_SMD:TO-252-2", "TO-263-3 (D2PAK)": "Package_TO_SOT_SMD:TO-263-3_TabPin2",
    "TO-263-5 (D2PAK)": "Package_TO_SOT_SMD:TO-263-5_TabPin3", "TO-263-7 (D2PAK)": "Package_TO_SOT_SMD:TO-263-7_TabPin4",
    "PowerPAK SO-8 5x6 (DFN5x6)": "Package_SO:PowerPAK_SO-8_Single",
    "PowerPAK 1212-8 3.3x3.3": "Package_SO:Vishay_PowerPAK_1212-8_Single",
    "TO-92 inline": "Package_TO_SOT_THT:TO-92_Inline", "TO-220-3 vertical": "Package_TO_SOT_THT:TO-220-3_Vertical",
    "TO-247-3": "Package_TO_SOT_THT:TO-247-3_Vertical", "TO-126": "Package_TO_SOT_THT:TO-126-3_Vertical",
    # ICs
    "SOIC-8": "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm", "SOIC-14": "Package_SO:SOIC-14_3.9x8.7mm_P1.27mm",
    "SOIC-16": "Package_SO:SOIC-16_3.9x9.9mm_P1.27mm", "SOIC-16 wide (7.5 mm)": "Package_SO:SOIC-16W_7.5x10.3mm_P1.27mm",
    "SOIC-28 wide (7.5 mm)": "Package_SO:SOIC-28W_7.5x17.9mm_P1.27mm",
    "SOIC-8 5.3 mm (208 mil)": "Package_SO:SOIC-8_5.3x5.3mm_P1.27mm",
    "TSSOP-14": "Package_SO:TSSOP-14_4.4x5mm_P0.65mm", "TSSOP-20": "Package_SO:TSSOP-20_4.4x6.5mm_P0.65mm",
    "SSOP-28": "Package_SO:SSOP-28_5.3x10.2mm_P0.65mm", "MSOP-8": "Package_SO:MSOP-8_3x3mm_P0.65mm",
    "MSOP-10": "Package_SO:MSOP-10_3x3mm_P0.5mm", "QSOP-16": "Package_SO:QSOP-16_3.9x4.9mm_P0.635mm",
    "TQFP-32 7x7 P0.8": "Package_QFP:TQFP-32_7x7mm_P0.8mm", "TQFP-44 10x10 P0.8": "Package_QFP:TQFP-44_10x10mm_P0.8mm",
    "LQFP-48 7x7 P0.5": "Package_QFP:LQFP-48_7x7mm_P0.5mm", "LQFP-64 10x10 P0.5": "Package_QFP:LQFP-64_10x10mm_P0.5mm",
    "LQFP-100 14x14 P0.5": "Package_QFP:LQFP-100_14x14mm_P0.5mm",
    "QFN-16 3x3 P0.5": "Package_DFN_QFN:QFN-16-1EP_3x3mm_P0.5mm_EP1.7x1.7mm",
    "QFN-20 4x4 P0.5": "Package_DFN_QFN:QFN-20-1EP_4x4mm_P0.5mm_EP2.6x2.6mm",
    "QFN-24 4x4 P0.5": "Package_DFN_QFN:QFN-24-1EP_4x4mm_P0.5mm_EP2.6x2.6mm",
    "QFN-32 5x5 P0.5": "Package_DFN_QFN:QFN-32-1EP_5x5mm_P0.5mm_EP3.45x3.45mm",
    "QFN-48 7x7 P0.5": "Package_DFN_QFN:QFN-48-1EP_7x7mm_P0.5mm_EP5.15x5.15mm",
    "DIP-8 (300 mil)": "Package_DIP:DIP-8_W7.62mm", "DIP-28 (300 mil)": "Package_DIP:DIP-28_W7.62mm",
    "DIP-40 (600 mil)": "Package_DIP:DIP-40_W15.24mm", "PLCC-44": "Package_LCC:PLCC-44",
    # connectors
    "Pin header 1x4 P2.54": "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical",
    "Pin header 2x5 P2.54": "Connector_PinHeader_2.54mm:PinHeader_2x05_P2.54mm_Vertical",
    "JST PH 4-pin": "Connector_JST:JST_PH_B4B-PH-K_1x04_P2.00mm_Vertical",
    "JST XH 4-pin": "Connector_JST:JST_XH_B4B-XH-A_1x04_P2.50mm_Vertical",
    "JST ZH 4-pin": "Connector_JST:JST_ZH_B4B-ZR_1x04_P1.50mm_Vertical",
    "JST EH 4-pin": "Connector_JST:JST_EH_B4B-EH-A_1x04_P2.50mm_Vertical",
    "JST VH 4-pin": "Connector_JST:JST_VH_B4P-VH_1x04_P3.96mm_Vertical",
    "Molex PicoBlade 4-pin": "Connector_Molex:Molex_PicoBlade_53047-0410_1x04_P1.25mm_Vertical",
    "Molex Mini-Fit 2x4": "Connector_Molex:Molex_Mini-Fit_Jr_5566-08A_2x04_P4.20mm_Vertical",
    "Pin socket 1x4 P2.54": "Connector_PinSocket_2.54mm:PinSocket_1x04_P2.54mm_Vertical",
    "USB-A receptacle THT": "Connector_USB:USB_A_Molex_67643_Horizontal",
    "JST SH 4-pin SMD": "Connector_JST:JST_SH_SM04B-SRSS-TB_1x04-1MP_P1.00mm_Horizontal",
    "JST GH 4-pin SMD": "Connector_JST:JST_GH_SM04B-GHS-TB_1x04-1MP_P1.25mm_Horizontal",
    "JST PH SMD 4-pin SMD": "Connector_JST:JST_PH_S4B-PH-SM4-TB_1x04-1MP_P2.00mm_Horizontal",
    "Molex KK-254 4-pin": "Connector_Molex:Molex_KK-254_AE-6410-04A_1x04_P2.54mm_Vertical",
    "Screw terminal 2-pin P5.08": "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal",
    "IDC box header 2x5": "Connector_IDC:IDC-Header_2x05_P2.54mm_Vertical",
    "USB-C receptacle 16P (USB 2.0)": "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12",
    "USB-C receptacle 6P (power only)": "Connector_USB:USB_C_Receptacle_GCT_USB4125-xx-x_6P_TopMnt_Horizontal",
    "USB Micro-B receptacle": "Connector_USB:USB_Micro-B_Molex_47346-0001",
    "USB Mini-B receptacle": "Connector_USB:USB_Mini-B_Lumberg_2486_01_Horizontal",
    "USB-B receptacle THT": "Connector_USB:USB_B_OST_USB-B1HSxx_Horizontal",
    "DC barrel jack 5.5x2.1": "Connector_BarrelJack:BarrelJack_CUI_PJ-102AH_Horizontal",
    "RJ45 8P8C shielded": "Connector_RJ:RJ45_Amphenol_54602-x08_Horizontal",
    "SMA edge mount": "Connector_Coaxial:SMA_Samtec_SMA-J-P-H-ST-EM1_EdgeMount",
    "U.FL / IPEX receptacle": "Connector_Coaxial:U.FL_Hirose_U.FL-R-SMT-1_Vertical",
    "3.5 mm audio jack SMD": "Connector_Audio:Jack_3.5mm_PJ320D_Horizontal",
    "microSD socket": "Connector_Card:microSD_HC_Hirose_DM3AT-SF-PEJM5",
    "D-Sub 9 female": "Connector_Dsub:DSUB-9_Socket_Horizontal_P2.77x2.84mm_EdgePinOffset7.70mm_Housed_MountingHolesOffset9.12mm",
    "D-Sub 9 male": "Connector_Dsub:DSUB-9_Pins_Horizontal_P2.77x2.84mm_EdgePinOffset7.70mm_Housed_MountingHolesOffset9.12mm",
    "FFC/FPC 20-pin P0.5": "Connector_FFC-FPC:Hirose_FH12-20S-0.5SH_1x20-1MP_P0.50mm_Horizontal",
    "CR2032 holder THT": "Battery:BatteryHolder_Keystone_106_1x20mm",
    "18650 holder": "Battery:BatteryHolder_Keystone_1042_1x18650",
    "2 x AA holder": "Battery:BatteryHolder_Keystone_2462_2xAA",
    # electromechanical & misc
    "Tactile switch 6x6 THT": "Button_Switch_THT:SW_PUSH_6mm",
    "Tactile switch 12x12 THT": "Button_Switch_THT:SW_PUSH-12mm",
    "Tactile switch SMD 6x6": "Button_Switch_SMD:SW_SPST_PTS645Sx43SMTR92",
    "Tactile switch SMD 5.2x5.2": "Button_Switch_SMD:SW_SPST_TL3342",
    "DIP switch 4-position THT": "Button_Switch_THT:SW_DIP_SPSTx04_Slide_9.78x12.34mm_W7.62mm_P2.54mm",
    "Rotary encoder EC11 with switch": "Rotary_Encoder:RotaryEncoder_Alps_EC11E-Switch_Vertical_H20mm",
    "Slide switch SPDT SMD": "Button_Switch_SMD:SW_SPDT_Shouhan_MSK12C02",
    "Relay SPDT Songle SRD (10 A)": "Relay_THT:Relay_SPDT_SANYOU_SRD_Series_Form_C",
    "Relay SPDT Omron G5V-1 (signal)": "Relay_THT:Relay_SPDT_Omron_G5V-1",
    "Buzzer D12 P7.6": "Buzzer_Beeper:Buzzer_12x9.5RM7.6",
    "Crystal HC-49/US (low profile)": "Crystal:Crystal_HC49-4H_Vertical",
    "Crystal / oscillator SMD 3.2x2.5 (4 pads)": "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm",
    "Crystal / oscillator SMD 2x1.6 (4 pads)": "Crystal:Crystal_SMD_2016-4Pin_2.0x1.6mm",
    "Crystal / oscillator SMD 2.5x2 (4 pads)": "Crystal:Crystal_SMD_2520-4Pin_2.5x2.0mm",
    "Crystal / oscillator SMD 5x3.2 (4 pads)": "Crystal:Crystal_SMD_5032-4Pin_5.0x3.2mm",
    "Crystal / oscillator SMD 7x5 (4 pads)": "Crystal:Crystal_SMD_7050-4Pin_7.0x5.0mm",
    "Crystal SMD 5x3.2 (2 pads)": "Crystal:Crystal_SMD_5032-2Pin_5.0x3.2mm",
    "LED PLCC-2 2835": "LED_SMD:LED_PLCC_2835",
    "SK6812MINI 3535 addressable": "LED_SMD:LED_SK6812MINI_PLCC4_3.5x3.5mm_P1.75mm",
    "WS2812B-2020 addressable": "LED_SMD:LED_WS2812B-2020_PLCC4_2.0x2.0mm",
    "RGB LED 5050 (6-pin)": "LED_SMD:LED_RGB_5050-6",
    "Fuse TR5 radial": "Fuse:Fuseholder_TR5_Littelfuse_No560_No460",
    "LED PLCC-2 5730": "LED_SMD:LED_Yuji_5730",
    "7-segment display 1 digit": "Display_7Segment:7SegmentLED_LTS6760_LTS6780",
    "7-segment display 4 digit": "Display_7Segment:CA56-12EWA",
    "Slide switch SPDT THT": "Button_Switch_THT:SW_Slide_SPDT_Straight_CK_OS102011MS2Q",
    "Potentiometer RV09 vertical": "Potentiometer_THT:Potentiometer_Bourns_PTV09A-1_Single_Vertical",
    "3.5 mm audio jack THT": "Connector_Audio:Jack_3.5mm_CUI_SJ1-3523N_Horizontal",
    "Micro SIM socket": "Connector_Card:microSIM_JAE_SF53S006VCBR2000",
    "CR2032 holder SMD": "Battery:BatteryHolder_Keystone_3034_1x20mm",
    "LED 5 mm THT": "LED_THT:LED_D5.0mm", "LED 3 mm THT": "LED_THT:LED_D3.0mm",
    "WS2812B 5050 addressable": "LED_SMD:LED_WS2812B_PLCC4_5.0x5.0mm_P3.2mm",
    "ESP32-WROOM-32 module": "RF_Module:ESP32-WROOM-32",
    "ESP-12F (ESP8266) module": "RF_Module:ESP-12E",
    "Arduino Nano": "Module:Arduino_Nano",
    "Raspberry Pi Pico": "Module:RaspberryPi_Pico_Common_THT",
    "Mounting hole M3": "MountingHole:MountingHole_3.2mm_M3",
    "Mounting hole M3 plated": "MountingHole:MountingHole_3.2mm_M3_Pad",
    "Mounting hole M2 plated": "MountingHole:MountingHole_2.2mm_M2_Pad",
    "Mounting hole M2.5 plated": "MountingHole:MountingHole_2.7mm_M2.5_Pad",
    "Mounting hole M4 plated": "MountingHole:MountingHole_4.3mm_M4_Pad",
    # guitar-pedal parts (library/gen_pedal.py)
    "Alpha 9 mm pot (PCB vertical)": "Potentiometer_THT:Potentiometer_Alpha_RD901F-40-00D_Single_Vertical",
    '1/4" jack stereo, Neutrik NMJ6HCD2': "Connector_Audio:Jack_6.35mm_Neutrik_NMJ6HCD2_Horizontal",
    "DC jack 2.1 mm, centre-negative (PCB)": "Connector_BarrelJack:BarrelJack_Horizontal",
    # guitar / bass amp parts (library/gen_amp.py); the Belton socket patterns come from Belton's catalogue
    "Noval B9A socket, straight pins (ceramic PCB)": "Valve:Valve_ECC-83-1",
    "Snap-in electrolytic D22 x 30 mm": "Capacitor_THT:CP_Radial_D22.0mm_P10.00mm_SnapIn",
    "Snap-in electrolytic D25 x 40 mm": "Capacitor_THT:CP_Radial_D25.0mm_P10.00mm_SnapIn",
    "Snap-in electrolytic D30 x 40 mm": "Capacitor_THT:CP_Radial_D30.0mm_P10.00mm_SnapIn",
    "Snap-in electrolytic D35 x 50 mm": "Capacitor_THT:CP_Radial_D35.0mm_P10.00mm_SnapIn",
    "Axial electrolytic L18 D8 P25": "Capacitor_THT:CP_Axial_L18.0mm_D8.0mm_P25.00mm_Horizontal",
    "Axial electrolytic L25 D10 P30": "Capacitor_THT:CP_Axial_L25.0mm_D10.0mm_P30.00mm_Horizontal",
    "Axial electrolytic L30 D12.5 P35": "Capacitor_THT:CP_Axial_L30.0mm_D12.5mm_P35.00mm_Horizontal",
    "Axial electrolytic L38 D18 P44": "Capacitor_THT:CP_Axial_L38.0mm_D18.0mm_P44.00mm_Horizontal",
    "Axial electrolytic L26.5 D20 P33": "Capacitor_THT:CP_Axial_L26.5mm_D20.0mm_P33.00mm_Horizontal",
    "Axial film L12 D6.5 P15": "Capacitor_THT:C_Axial_L12.0mm_D6.5mm_P15.00mm_Horizontal",
    "Axial film L17 D7 P20": "Capacitor_THT:C_Axial_L17.0mm_D7.0mm_P20.00mm_Horizontal",
    "Axial film L19 D7.5 P25": "Capacitor_THT:C_Axial_L19.0mm_D7.5mm_P25.00mm_Horizontal",
    "Axial film L22 D9.5 P27.5": "Capacitor_THT:C_Axial_L22.0mm_D9.5mm_P27.50mm_Horizontal",
    "Power resistor 4 W cement L20 (lying)": "Resistor_THT:R_Axial_Power_L20.0mm_W6.4mm_P25.40mm",
    "Power resistor 7 W cement L25 (lying)": "Resistor_THT:R_Axial_Power_L25.0mm_W9.0mm_P30.48mm",
    "Power resistor 9 W cement L38 (lying)": "Resistor_THT:R_Axial_Power_L38.0mm_W9.0mm_P45.72mm",
    "Power resistor 15 W cement L48 (lying)": "Resistor_THT:R_Axial_Power_L48.0mm_W12.5mm_P55.88mm",
    "Power resistor 4 W cement L20 (standing)": "Resistor_THT:R_Axial_Power_L20.0mm_W6.4mm_P5.08mm_Vertical",
    "Power resistor 7 W cement L25 (standing)": "Resistor_THT:R_Axial_Power_L25.0mm_W9.0mm_P7.62mm_Vertical",
    "Bridge rectifier KBU (inline)": "Diode_THT:Diode_Bridge_Vishay_KBU",
    "Bridge rectifier GBU (inline, slim)": "Diode_THT:Diode_Bridge_Vishay_GBU",
    "Bridge rectifier DIP-4": "Diode_THT:Diode_Bridge_DIP-4_W7.62mm_P5.08mm",
    "Bridge rectifier KBPC6 (square)": "Diode_THT:Diode_Bridge_Vishay_KBPC6",
    "Bridge rectifier round 9 mm (W04G)": "Diode_THT:Diode_Bridge_Round_D9.0mm",
    "TO-3 power transistor": "Package_TO_SOT_THT:TO-3",
    "LM3886 (TO-220-11)": "Package_TO_SOT_THT:TO-220-11_P3.4x5.08mm_StaggerOdd_Lead4.58mm_Vertical",
    "TDA7293 / TDA7294 (Multiwatt-15)": "Package_TO_SOT_THT:TO-220-15_P2.54x5.08mm_StaggerOdd_Lead4.58mm_Vertical",
    "LM1875 / TDA2050 (Pentawatt)": "Package_TO_SOT_THT:TO-220-5_P3.4x3.7mm_StaggerOdd_Lead3.8mm_Vertical",
    "TPA3116D2 class-D (HTSSOP-32, top pad)": "Package_SO:Texas_DAD0032A_HTSSOP-32_6.1x11mm_P0.65mm_TopEP3.71x3.81mm",
    "XLR female Neutrik NC3FAH (PCB)": "Connector_Audio:Jack_XLR_Neutrik_NC3FAH_Horizontal",
    "XLR male Neutrik NC3MAAH (PCB, DI out)": "Connector_Audio:Jack_XLR_Neutrik_NC3MAAH_Horizontal",
    'XLR / 1/4" combo Neutrik NCJ6FA-H': "Connector_Audio:Jack_XLR-6.35mm_Neutrik_NCJ6FA-H_Horizontal",
    "speakON NL4MD-H-3 (PCB)": "Connector_Audio:Jack_speakON_Neutrik_NL4MDXX-H-3_Horizontal",
    '1/4" jack Neutrik NRJ6HF (threaded)': "Connector_Audio:Jack_6.35mm_Neutrik_NRJ6HF_Horizontal",
    "Relay Omron G5LE-1 (SPDT)": "Relay_THT:Relay_SPDT_Omron-G5LE-1",
    "Relay Omron G2RL-2 (DPDT)": "Relay_THT:Relay_DPDT_Omron_G2RL-2",
    "Pot 16 mm right-angle (Alps RK163)": "Potentiometer_THT:Potentiometer_Alps_RK163_Single_Horizontal",
    "Slide pot 45 mm (Bourns PTA4543)": "Potentiometer_THT:Potentiometer_Bourns_PTA4543_Single_Slide",
}


@dataclass
class PadDelta:
    ref: Pad
    mine: Pad | None
    pos_err: float
    size_err: float
    drill_err: float
    number_ok: bool


@dataclass
class CompareResult:
    name: str
    reference: str
    rotation: float = 0.0
    deltas: list = field(default_factory=list)
    extra: list = field(default_factory=list)  # pads in mine with no counterpart

    @property
    def matched(self):
        return [d for d in self.deltas if d.mine is not None]

    @property
    def missing(self):
        return [d for d in self.deltas if d.mine is None]

    @property
    def max_pos(self) -> float:
        return max((d.pos_err for d in self.matched), default=0.0)

    @property
    def max_size(self) -> float:
        return max((d.size_err for d in self.matched), default=0.0)

    @property
    def max_drill(self) -> float:
        return max((d.drill_err for d in self.matched), default=0.0)

    @property
    def numbering_errors(self) -> int:
        return sum(1 for d in self.matched if not d.number_ok)

    def ok(self, pos_tol=0.1, size_tol=0.3, drill_tol=0.15) -> bool:
        return (not self.missing and not self.extra and self.max_pos <= pos_tol and self.max_size <= size_tol
                and self.max_drill <= drill_tol and self.numbering_errors == 0)

    def summary(self) -> str:
        return (f"{'OK  ' if self.ok() else 'DIFF'} {self.name:42s} pads {len(self.matched)}/{len(self.deltas)}"
                f" extra {len(self.extra)} pos {self.max_pos:.3f} size {self.max_size:.3f} drill {self.max_drill:.3f}"
                f" numbering {self.numbering_errors}  [rot {self.rotation:g}]")


def _copper_pads(fp: Footprint) -> list[Pad]:
    return [p for p in fp.pads if p.kind != "npth" or p.drill > 0]


def _pad_dims(p: Pad, extra_rot: float) -> tuple[float, float]:
    r = (p.rotation + extra_rot) % 180
    w, h = (p.w, p.h) if abs(r - 90) > 45 else (p.h, p.w)
    return w, h


def _numbers_match(a: str, b: str) -> bool:
    if a == b:
        return True
    # KiCad leaves mechanical pads (mounting lugs, shields) unnumbered; ours are named MP / SH / MH
    if not b and a.upper() in ("MP", "SH", "MH"):
        return True
    # combined pins such as "A1B12" vs separate "A1"/"B12" pads
    return bool(a and b and (a in b or b in a))


# Pads deliberately modelled differently from the reference; both variants follow the datasheet.
KNOWN_VARIANTS = {
    "ESP32-WROOM-32 module": ({"39"}, "ground pad 39 is a single 4.2 mm pad; the reference splits it into a paste "
                                      "window array with thermal vias"),
}


def compare(mine: Footprint, ref: Footprint, name: str = "", ref_name: str = "", ignore: set | None = None) -> CompareResult:
    ignore = ignore or set()
    mp = [p for p in _copper_pads(mine) if p.number not in ignore]
    rp = [p for p in _copper_pads(ref) if p.number not in ignore]
    best = None
    for rot in (0.0, 90.0, 180.0, 270.0):
        pts = [rotate_point(p.x, p.y, rot) for p in mp]
        # translation from the bounding-box centres, refined by nearest-neighbour matching
        if not pts or not rp:
            continue
        mx = (min(x for x, _ in pts) + max(x for x, _ in pts)) / 2
        my = (min(y for _, y in pts) + max(y for _, y in pts)) / 2
        rx = (min(p.x for p in rp) + max(p.x for p in rp)) / 2
        ry = (min(p.y for p in rp) + max(p.y for p in rp)) / 2
        tx, ty = rx - mx, ry - my
        for _ in range(3):
            pairs = []
            for q in rp:
                j = min(range(len(pts)), key=lambda k: (pts[k][0] + tx - q.x) ** 2 + (pts[k][1] + ty - q.y) ** 2)
                pairs.append((q, j))
            dx = sum(q.x - (pts[j][0] + tx) for q, j in pairs) / len(pairs)
            dy = sum(q.y - (pts[j][1] + ty) for q, j in pairs) / len(pairs)
            tx += dx
            ty += dy
        err = sum(math.hypot(pts[j][0] + tx - q.x, pts[j][1] + ty - q.y) for q, j in pairs)
        # symmetric footprints align equally well at several rotations: prefer the one where pin numbers agree
        err += sum(0.5 for q, j in pairs if not _numbers_match(mp[j].number, q.number) and q.kind != "npth")
        if best is None or err < best[0]:
            best = (err, rot, tx, ty, pts)
    res = CompareResult(name or mine.name, ref_name or ref.name)
    if best is None:
        res.deltas = [PadDelta(q, None, 0, 0, 0, False) for q in rp]
        return res
    _, rot, tx, ty, pts = best
    res.rotation = rot
    used = set()
    for q in rp:
        cands = sorted(range(len(mp)), key=lambda k: math.hypot(pts[k][0] + tx - q.x, pts[k][1] + ty - q.y))
        k = next((c for c in cands if c not in used or (
            mp[c].number != q.number and _numbers_match(mp[c].number, q.number)
            and math.hypot(pts[c][0] + tx - q.x, pts[c][1] + ty - q.y) < 0.05)), None)
        if k is None:
            res.deltas.append(PadDelta(q, None, 0, 0, 0, False))
            continue
        pos = math.hypot(pts[k][0] + tx - q.x, pts[k][1] + ty - q.y)
        if pos > 0.6:
            res.deltas.append(PadDelta(q, None, pos, 0, 0, False))
            continue
        used.add(k)
        m = mp[k]
        mw, mh = _pad_dims(m, rot)
        qw, qh = _pad_dims(q, 0)
        size = max(abs(mw - qw), abs(mh - qh)) if (m.shape != "poly" and q.shape != "poly") else 0.0
        drill = abs(m.min_drill - q.min_drill) if (m.drill or q.drill) else 0.0
        res.deltas.append(PadDelta(q, m, pos, size, drill, _numbers_match(m.number, q.number) or q.kind == "npth"))
    res.extra = [mp[k] for k in range(len(mp)) if k not in used]
    return res


def kicad_root() -> Path | None:
    from .kicad import default_kicad_dirs
    for d in default_kicad_dirs():
        if (d / "Package_SO.pretty").exists():
            return d
    return None


def load_reference(ref: str, root: Path | None = None) -> Footprint | None:
    from .kicad import load_kicad_mod
    root = root or kicad_root()
    if root is None:
        return None
    lib, name = ref.split(":", 1)
    path = root / f"{lib}.pretty" / f"{name}.kicad_mod"
    return load_kicad_mod(path) if path.exists() else None


def verify_builtin(root: Path | None = None) -> list[CompareResult]:
    from ..model.footprints import find_part
    out = []
    for part_name, ref in REFERENCES.items():
        part = find_part(part_name)
        ref_fp = load_reference(ref, root)
        if part is None or ref_fp is None:
            continue
        ignore = KNOWN_VARIANTS.get(part_name, (set(), ""))[0]
        out.append(compare(part.make(), ref_fp, part_name, ref, ignore))
    return out
