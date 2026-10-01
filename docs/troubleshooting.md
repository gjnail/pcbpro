# Troubleshooting and limits

Fixes for common problems, and what PCBPro doesn't do (yet). If something here doesn't help, [open an issue](https://github.com/gjnail/pcbpro/issues/new/choose) with your OS, the PCBPro version (**Help › About**) and, if you can share it, the project file.

## Starting up

**Windows says "Windows protected your PC".** The download isn't code-signed yet. Click **More info**, then **Run anyway**. You can check the zip against the release's SHA-256 checksum, or with `gh attestation verify` (see [Install](getting-started.md#the-windows-download)).

**The 3D view is black or the app closes when it opens.** The 3D view needs OpenGL 3.3. Update your graphics driver. Remote desktop sessions and some virtual machines only offer old OpenGL; in that case, start PCBPro with the environment variable `QT_OPENGL=software` to use Qt's software renderer (slower, but it works).

**The window doesn't fit on the screen.** Drag the docks (Library, Properties, Layers) to make them narrower, or close the ones you don't need; **View** brings them back. Windows display scaling above 150 % on a small screen leaves little room.

**Running from source fails to install.** You need Python 3.10 or newer, 64-bit. Delete the `.venv` folder and run `PCBPro.bat` or `pcbpro.sh` again to start over. On Linux, Play live needs PortAudio (`sudo apt install libportaudio2`).

**Resetting PCBPro.** Settings (window layout, recent files, audio devices, the cabinet list) are kept in the registry under `HKEY_CURRENT_USER\Software\PCBPro`. Deleting that key resets them. Your parts and downloads in `Documents\PCBPro` are separate.

## Layout and routing

**The autorouter leaves connections unrouted.** Move parts apart to open channels, especially around dense ICs; try a finer routing grid (0.15 or 0.1 mm); allow vias (*Prefer vias*); or route the difficult connections by hand first, then autoroute the rest. Check that the default track width and clearance in the board's Properties aren't larger than the parts' pin pitch allows.

**DRC reports clearance errors on a tube socket or a connector with fine pitch.** Pads use the net classes' clearance. For amps, use **Amp › Apply HV net classes**, which sets lead spacing for pads and conductor spacing for tracks. For a fine-pitch part, make sure its nets aren't in a class with a large clearance.

**DRC says the pours are out of date.** **Tools › Refill zones** (Ctrl+B). Pours refill after every edit, but a project saved by an older version may need it once.

**A part is mirrored.** It's on the bottom side; press **F** to flip it back. Pedal pots usually *should* be on the bottom (see [Mirroring](pedals.md#mirroring-handled-for-you)).

## Parts

**LCSC import fails.** The EasyEDA library behind it isn't a documented API and sometimes changes or goes down. Parts you've fetched before still import from the cache. Otherwise use **Open part data in browser**, save the page, and **Import from file…**, or get the part from the KiCad library or the footprint wizard. See [Any LCSC or JLCPCB part](library.md#any-lcsc-or-jlcpcb-part).

**The KiCad library download fails.** It's a large ZIP from GitLab; a proxy or firewall can stop it. Download `kicad-footprints-master.zip` from gitlab.com/kicad/libraries/kicad-footprints yourself, unpack it, and use **Add folder…** in **Library › KiCad footprint libraries…**.

**A footprint doesn't match my part.** Right-click it in the Library and **Check against KiCad footprint** with the KiCad footprint for your exact part, or import the exact part from LCSC. Always check footprints against the datasheet, and the fab's Gerber viewer, before you order.

## Simulation

**A part is hatched and its pins are open.** PCBPro doesn't know what it is, or doesn't simulate that kind of part. Double-click it in the Simulation panel to pick a model, or set its MPN or value to a known part (for example `TL072`, `2N3904`, `1N4148`).

**The simulation runs slowly.** Check the speed in the Simulation panel. Microcontrollers are the most expensive part: a busy 16 MHz AVR runs at about a third of real time. Timing inside the simulation stays exact. Keep *Run in a separate process* on so the window stays responsive.

**The LED doesn't light.** Check the power: **Simulate › Power and signal sources…** shows what supplies the board gets. A board that takes power from a header needs a net named like a supply (`5V`, `VCC`, `9V`) or a source you add there. In *As built* mode, a missing track really leaves the LED unconnected; switch to *As designed* to compare.

**A part shows smoke.** It's running beyond a rating: power, current, voltage, or (for tubes) plate dissipation. The Simulation panel's warnings say which. **Simulate › Clear smoke markers** clears them.

## Audio

**Play live has no input or output devices.** Plug in the interface before opening the dialog. Pick a different driver: WASAPI works with most interfaces; ASIO needs the interface's ASIO driver. Close other programs that use the interface in exclusive mode (a DAW).

**Crackles or dropouts.** Raise the buffer (256 or 512 samples), lower the oversampling, or turn off exclusive mode. Close CPU-heavy programs. Big amp boards are expensive: if Play live says a design is too heavy, use **Audio play-through** instead.

**It's far too loud or too quiet.** Set **Full scale =** to match your interface: with the interface's input gain where you normally record guitar, a 1 V full scale is a good start. Start with the volume low.

**A distortion sounds harsh or fizzy.** Turn on a cabinet: guitar speakers cut everything above about 5 kHz, and a distortion pedal or amp straight into headphones sounds like a beehive.

## Known issues

- Audio play-through and Play live render the bundled **Metal High-Gain Distortion** pedal wrongly (a DC offset, then instability) in the compiled real-time model; the offline simulator (**Run**) is correct. A fix is being worked on.

## Limits

What PCBPro doesn't do yet:

- **Platforms.** Windows 10 and 11 are what it's built and tested on. The test suite also runs on Linux and macOS for every change (the 3D view's tests on Linux only, since GitHub's Windows and macOS machines have no GPU), and the 3D view hasn't been checked on a Mac. macOS and Linux run from source and haven't been used much; reports are welcome.
- **No schematic editor.** You make the netlist on the board. Netlist import from other tools isn't supported either.
- **Layers.** Two or four copper layers. No blind or buried vias, no flex or rigid-flex.
- **Routing.** The autorouter is a grid router: no push-and-shove, differential pairs or length matching. Interactive routing doesn't shove other tracks.
- **Simulation.** Switching regulators, microcontrollers other than the AVRs listed, and I2C or SPI peripherals aren't simulated. Mains wiring and the transformer primary aren't either; amp boards get their supplies as DC sources.
- **Ordering.** No fab offers a public ordering API, so PCBPro prepares the files and opens the fab's upload page. Prices are estimates.
- **Safety.** The high-voltage checks follow IPC-2221B and common practice but are not a safety standard (IEC 62368-1 / UL) for mains wiring. See [Amp boards](amps.md#safety).
- **Hardware data.** Enclosure cavities, depths and bosses come from Hammond's data; the face thickness, the 3PDT lug pitch, the jack axis heights and some hole sizes are estimates. Measure your parts before drilling.
