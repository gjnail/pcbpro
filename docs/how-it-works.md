# How it works

The engineering behind PCBPro, for the curious and for anyone extending it. Everything is Python: the app is Qt (PySide6) with an OpenGL 3D view, geometry is done with Shapely, the simulator with NumPy, and the real-time audio kernel is compiled with numba. There's no browser, web runtime or external simulator.

## The board model

A project is a board outline, components (each carrying its full footprint, so a project opens without the library it came from), tracks, vias, zones, texts, net classes and design rules, plus optional pedal, amp and simulation data. It's saved as JSON (`.pcbpro`).

Model units are millimetres, Y points down (the screen and KiCad convention), and rotations are degrees counter-clockwise as displayed. A footprint is a list of pads (SMD or through-hole, with rectangle, rounded-rectangle, circle, oval, trapezoid or polygon shapes and round or slotted drills), graphics on the silkscreen, fab and courtyard layers, and a 3D model description.

Every edit goes through the document (`ui/document.py`), which records undo steps, tracks the selection and tells the views what changed.

## Copper and connectivity

- **Copper geometry** (`model/copper.py`): pads, tracks (as buffered line strings), vias and holes become Shapely polygons per layer.
- **Pours** are filled by subtracting every other net's copper, grown by the larger of the zone's and the net classes' clearance, then removing slivers thinner than the minimum width, adding thermal-relief spokes to through-hole pads of the zone's net, and dropping islands that aren't connected to the net. Overlapping zones fill in priority order. On amp boards the clearance is computed pair by pair from the voltage between the nets.
- **Connectivity** (`model/connectivity.py`) groups copper that touches into physical clusters per net. The ratsnest is the shortest set of connections joining a net's clusters (a minimum spanning tree), and two nets in one cluster are a short.

## The design rule check

`model/drc.py` checks the outline, then clearances between copper of different nets on each layer (using a spatial index to find neighbours), shorts from connectivity, minimum track widths, drills and annular rings, copper-to-edge distance, hole-to-hole spacing, parts outside the outline, courtyard overlaps, unrouted connections and stale pours. Pedal designs add `pedal/checks.py` (the enclosure, part heights from each 3D model, panel hardware) and amp designs `amp/checks.py` (IPC-2221B spacing by voltage, current, part ratings, bleeders, tube wiring).

## The autorouter

`route/autorouter.py` is a grid router:

1. The grid pitch comes from the default track width and clearance (0.1 to 0.25 mm), coarsened on big boards to keep the grid under about 300,000 cells per layer.
2. For each net, every obstacle (other nets' copper grown by the clearance and half the track width, the board edge, holes) is rasterised with Qt's polygon scan conversion into an occupancy grid. Via sites get their own grid, grown by the via radius, across all layers.
3. Each connection of the ratsnest is found with A* over 8-connected moves (45° routing) and via transitions, with a cost for each via and a direction penalty that makes the first layer prefer horizontal tracks and the last layer vertical ones.
4. Connections are routed shortest first. Nets with a copper pour wait until the end and are connected with short stubs and vias into the pour. On amp boards, nets are ranked by voltage so the highest go first, and each net keeps the IPC spacing its voltage needs from each other net, pair by pair.
5. Each path is split into runs per layer with a via at every layer change, and its ends are pulled onto the pad centres.

It runs on a copy of the project in a worker thread, so it can be cancelled and undone in one step.

## The parts library

- **Generated footprints** (`library/gen_*.py`): every module named `gen_*.py` with an `entries()` function is picked up automatically. Each entry is a category, a name, a reference prefix, a default value, a footprint factory and search keywords. Land patterns follow IPC-7351 nominal densities.
- **KiCad import** (`library/kicad.py`) parses KiCad 5 to 9 S-expression footprints and infers a 3D body from the name and fab outline.
- **EasyEDA import** (`library/easyeda.py`) converts EasyEDA's component records (pads, slots, holes, polygons, silkscreen, outline) into footprints, with retries, an on-disk cache and a file import that bypasses the network.
- **Verification** (`library/verify.py`): two footprints are aligned (rotations in 90° steps, then the translation that matches pads by position) and compared pad by pad for position, size, drill and numbering.

## 3D

`ui/mesh.py` builds procedural meshes for every footprint family (gull-wing ICs with their leads, chip parts, DIPs, headers, connectors, radial and axial parts with colour bands, LEDs, crystals, TO packages, USB-C), plus a generic body from the courtyard for anything else. The board is a triangulated (earcut) slab with its holes, textured with the copper, mask, finish and silkscreen artwork rendered at high resolution (`ui/boardtex.py`). Tubes (`amp/mesh3d.py`) are drawn with transparent glass, sorted back to front, and emissive heaters; pedal enclosures (`pedal/mesh3d.py`) are built in the box's own coordinates from the Hammond dimensions, with the draft of its walls, and turned knobs-up for the pedal view. LEDs glow with the brightness the simulation reports.

## Gerber and drill files

`export/gerber.py` writes RS-274X with X2 attributes: apertures for round, rectangular and obround pads, and regions for polygons and pours (a pour with holes is cut into hole-free pieces first, which every Gerber viewer reads the same way). `export/excellon.py` writes plated and unplated drills separately, with slots as G85 slot commands. The tests parse every exported file with pygerber, an independent implementation, and compare it with the board.

## The circuit simulator

`sim/engine.py` is a modified-nodal-analysis (MNA) engine: one equation per node voltage and per voltage-source branch current.

- **DC operating point**: Newton's method with SPICE-style junction limiting; if that fails, gmin stepping and then source stepping.
- **Transient**: adaptive time steps with trapezoidal and backward-Euler companion models for the capacitors and inductors, local error control from each device and exact landing on breakpoints (pulse edges) and events: a device with a discrete state (a comparator, a 555, a logic gate, a relay, a firmware pin) reports the thresholds whose zero crossings change it, and the engine finds the crossing.
- **AC**: a small-signal sweep around the operating point, for frequency responses.
- Semiconductors of a kind are stamped together with NumPy (vectorised groups), so a board with a hundred diodes costs little more than one with ten.

`sim/netlist.py` turns the board into a circuit. Nodes come from the nets (*as designed*) or from the copper clusters (*as built*). Each component is resolved to a model (`sim/models.py`): your override, the table of about 220 parts by part number, or the reference, footprint and value.

### Device models

| Device | Model |
|---|---|
| Diodes, LEDs, Zeners | Shockley with series resistance and reverse breakdown; LED forward voltage by colour |
| BJTs | Ebers-Moll transport model with the Early effect; germanium parts with their own saturation currents |
| MOSFETs, JFETs | Square law with a smooth sub-threshold corner |
| Op-amps | Behavioural: open-loop gain into an internal pole (its gain-bandwidth), slew-rate limiting, the output clamped smoothly short of the rails, and a current-limited output stage that draws its current from the supply pins |
| Comparators, 555, logic | Event devices with thresholds relative to their own supply pins, hysteresis, and push-pull or open outputs |
| Regulators, references, sensors | Behavioural blocks with dropout and limits |
| Vacuum tubes | Koren's equations with grid current and Miller capacitance (below) |
| Transformers | Ideal multi-winding transformer plus magnetising and leakage inductance and winding resistance |

### Vacuum tubes

Plate current follows Norman Koren's equations (1996), smooth from cut-off to grid conduction:

```
triode   E1 = Vpk / kp · ln(1 + exp(kp · (1/mu + Vgk / sqrt(kvb + Vpk²))))
         Ip = E1^ex / kg1
pentode  E1 = Vg2k / kp · ln(1 + exp(kp · (1/mu + Vg1k / Vg2k)))
         Ip = 2 · E1^ex / kg1 · atan(Vpk / kvb),   Ig2 = (Vg2k / mu + Vg1k)^ex / kg2
```

Grid current is a smooth power law after Cohen and Hélie (2010), which gives the blocking distortion of overdriven stages with coupling capacitors. The constants are Koren's published sets where they exist (12AX7, 12AT7, 12AU7, ECC88 and the power tubes); the other triodes are fitted to their datasheet transconductance and plate resistance. Then `kg1` and `kg2` are calibrated so every tube draws its datasheet current at its datasheet bias point, which is why the simulated bias voltages match real amps.

Amp boards' off-board parts (`sim/ampboard.py`) are modelled from the wire pads and the amp data: each rectified supply as a DC source behind the rectifier's source resistance, the output transformer from the design's primary impedance, a speaker impedance with its resonance and voice-coil inductance, and the choke. When the feedback polarity isn't given, both are simulated and the negative one is kept.

### The AVR emulator

`sim/avr/` runs Intel HEX firmware on an AVRe+ core. Flash words are decoded once into handler closures, ALU flags come from precomputed tables, and peripherals (ports, timers and PWM, the USART, the ADC, external and pin-change interrupts, the watchdog, the EEPROM) are computed lazily from the cycle counter: the CPU stops only at a peripheral's next event. `SLEEP` fast-forwards. The co-simulation runs the CPU ahead in short quanta, records each pin change at its exact cycle, and lets the analog engine land on every one.

### The real-time audio model

`sim/realtime.py` uses the nodal DK method. The circuit is built as for offline rendering, with the guitar source and its 10 kΩ pickup impedance and a 1 MΩ load. Every linear part (resistors, pots at their setting, capacitors and inductors as trapezoidal companions at the audio step) is folded into constant matrices once:

```
v  = Dz·z + Du·u + d0 + F·i(v)     nonlinear port voltages, solved each sample
z' = Az·z + Au·u + a0 + Ai·i(v)    capacitor and inductor history
y  = Yz·z + Yu·u + y0 + Yi·i(v)    the output
```

Only the nonlinear devices (diodes, BJTs, FETs, op-amps, triodes and pentodes) are solved per sample, with a small Newton iteration over their port voltages, in a loop compiled with numba. Other nonlinear blocks are linearised around the operating point and event devices frozen, which is what they do in an audio path. Oversampling runs the model at 2× or 4× with polyphase anti-alias filters. Circuits of tubes and diodes only use a "lazy" Newton that keeps the last factorised Jacobian until the solution moves too far; op-amp circuits always refactorise, because the shortcut can converge falsely on them.

Live audio (`sim/livefx.py`) runs that model in its own process, behind PortAudio through sounddevice. Cabinets (`sim/cabinet.py`) are convolved with uniformly partitioned overlap-save FFT convolution with the audio block as the partition, so they add no latency. FLAC impulse responses are read by a small pure-Python decoder (`sim/flac.py`) that checks every frame's CRC.

## The Amp Designer

`amp/designer.py` assembles a circuit from building blocks (gain stages, cathode followers, tone stacks, phase inverters, power stages, the bias supply, the rectifier and B+ filter chain, heater wiring) and picks every value. Power stages are tabulated, proven operating points rather than curve fits. Preamp DC is estimated with the linear triode model I = Vb / (ra + Ra + mu·Rk), good to about 20 %; the B+ chain is solved from the rectifier down with each node's current. The simulator, with its calibrated Koren models, is the check on both. The output, loudness and breakup point come from the gains and the input sensitivity.

`amp/gainstage.py` walks the recorded signal path: the small-signal response with the cathode-bypass shelves, coupling-cap high-passes, 470k / 470p attenuators and each stage's Miller capacitance against its source impedance; a peak-level cascade that follows the two half-waves separately, so a cold clipper and a hot stage are told apart; and the thermal noise of the input stage against the playing level.

`amp/tonestack.py` solves the TMB stack as a complex nodal network with real pot tapers. `amp/hv.py` holds IPC-2221B table 6-1 and the IPC-2221 conductor-sizing formula, I = k · ΔT^0.44 · A^0.725.

## Pedal enclosures

`pedal/enclosure.py` holds the Hammond catalogue and two coordinate systems: the board's (mm, X right, Y down, seen from the top copper) and the panel's (Tayda's: each side measured from its own centre in the unfolded drawing, +X right, +Y up). Panel holes come from footprints that carry `model["panel"]` metadata (the face, the hole, the body behind it) and from the enclosure's own list. When the pots hang under the board, the face sees the board mirrored, and the mapping between the two systems takes care of it.

## Testing

About 1,850 tests (`tests/`) cover:

- the model, file I/O and undo; placing, connecting, routing and DRC through the real UI;
- exports, parsed with an independent Gerber parser;
- the library: generators, the catalogue, KiCad import, LCSC parsing from saved real responses, and the pad-by-pad check of 151 footprints against KiCad when it's installed;
- pedals: every enclosure and knob count passes its own checks, drilling, the build sheet, the 3D meshes;
- amps: every Amp Designer combination designs, a representative set places and routes with a clean DRC, filter caps are rated for the switch-on voltage, heater currents add up, and the high-gain designs play tight palm mutes through the tube simulation;
- the simulator: device equations against known values, transient and AC results, logic, the AVR core (with test programs assembled in the tests), the real-time model against the offline engine, tubes against their datasheet points, cabinets and the FLAC decoder.

The Windows build has a self-test (`PCBPro.exe --selftest DIR`) that exercises the 3D view, the Gerber export, both simulation back ends, the real-time model, a cabinet IR and a tube amp board in the packaged app.
