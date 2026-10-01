# Changelog

Notable changes to PCBPro. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[semantic versioning](https://semver.org/).

## [Unreleased]

## [1.0.0] - 2026-10-01

This is the first public version.

### Added

- **Layout editor:** 2- and 4-layer boards with any outline and cut-outs; placing, rotating and flipping parts; making the netlist on the board with the Connect tool and pad nets; a 45° interactive router with live clearance highlighting; an A* autorouter with vias, layer directions and pour nets stubbed in last; copper pours with thermal reliefs, priorities and island removal; net classes; a design rule check for clearances, shorts, widths, drills, annular rings, edges, holes, courtyards and unrouted connections.
- **Parts library:** 1,200+ parametric footprints, about 265 catalogue parts by MPN, import of any LCSC part by C-number (with retries, an offline cache and a manual path), the official KiCad library and any `.pretty` folder, a footprint wizard, standard E24/E6 values, and pad-by-pad checks against KiCad's datasheet-based footprints (151 built-in footprints verified).
- **3D view:** real-time OpenGL with mask, finish and silkscreen, a procedural body for every footprint, pedals in their enclosures, tubes in their sockets, and LEDs that glow while the simulation runs.
- **Guitar pedals:** a new-pedal wizard; nine Hammond enclosures; mirrored drilling for boards that hang from their pots; the Enclosure & Drilling tab with a 1:1 PDF template and Tayda coordinates; enclosure checks; pedal parts; kit-style silkscreen; a build sheet; circuit blocks; and a three-knob overdrive example.
- **Amps:** the Amp Designer (eleven voicings from Blackface clean to five-stage extreme high gain, tube and solid-state power stages from 5 to 100 W, operating points, transformers, gain and breakup, tone, a first power-up checklist, a voltage chart, a Listen tab and a routed board); high-gain options (tightness, depth, a tube-buffered effects loop, DC heaters) with a gain-staging analysis; three metal pedals (Tight Boost, 4-cable Noise Gate, High-Gain Distortion); amp templates; 24 tubes drawn in 3D; IPC-2221B high-voltage rules and amp checks; a tone stack designer and calculators.
- **Simulation:** a built-in MNA circuit simulator with analog parts, about 220 real parts by number, vacuum tubes (Koren models calibrated to their datasheets), whole amp boards with their transformer and speaker, 74HC/CD4000 logic, and ATmega/ATtiny chips running compiled `.hex` firmware; an oscilloscope, an operating-point table, *as built* mode and overstress markers.
- **Audio:** Play live (your guitar through the circuit in real time, through a compiled nodal DK model), Audio play-through, the frequency response, and speaker cabinets (four public-domain IRs, or your own WAV and FLAC files).
- **Manufacturing:** Gerber RS-274X X2, Excellon drills, BOM and CPL in JLCPCB's format, pre-flight checks, a price and capability comparison of JLCPCB, PCBWay, OSH Park and AISLER, and a shopping list with links at eight shops.
- **The project:** the MIT license, a website with 18 guides, an examples gallery and sound clips, a contributor guide, a code of conduct, a security policy, issue and pull request templates, CI on Windows, Linux and macOS, a release workflow with a self-tested Windows build, and Ko-fi links.

[Unreleased]: https://github.com/gjnail/pcbpro/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/gjnail/pcbpro/releases/tag/v1.0.0
