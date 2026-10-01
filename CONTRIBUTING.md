# Contributing

Bug reports, fixes, footprints, enclosures, simulation models, pedal and amp
designs, boards that break the autorouter, and platform testing are all
welcome.

## Rules for parts, checks and simulation models

People order real boards and drill real boxes from what PCBPro produces, and
some of them plug the result into the mains. So these apply to every change
to a footprint, an enclosure, a design rule or a simulation model:

1. Use real numbers, and say where they come from. Footprints follow the
   manufacturer's datasheet or IPC-7351 and are checked against the official
   KiCad library where it has the part (`tools/verify_footprints.py`).
   Enclosure dimensions come from Hammond's drawings, tube data from the
   datasheets. Put the source in a comment or in the pull request. If a value
   is an estimate, say so where the user will see it.
2. Check it against something independent. A footprint against KiCad, a
   Gerber against an independent parser (`tests/test_route_export.py` uses
   pygerber), a device model against its datasheet's operating points, the
   real-time audio model against the offline engine
   (`tests/test_sim_realtime.py`). Add a test that does the same.
3. Never loosen a safety check without a reference. High-voltage spacing
   follows IPC-2221B table 6-1 (pads use the lead column, tracks and pours
   the conductor column); mains clearance, capacitor and resistor ratings,
   bleeders and heater wiring are checked in `pcbpro/amp/checks.py`. A change
   that lets more through needs the standard or the measurement behind it.
4. Don't break saved projects. A `.pcbpro` file is JSON; a new field gets a
   default that keeps old projects behaving as they did, and a renamed one
   still reads its old name.
5. Keep the window code small. Features plug into the main window through an
   `install(win)` function (`pedal_ui`, `sim_ui`, `amp_ui`, `shop`) rather than
   growing `main_window.py`.
6. No telemetry, and no network access the user didn't ask for. Today PCBPro
   only connects to EasyEDA (LCSC import) and GitLab (the KiCad library
   download), and opens fab and supplier websites in the browser.

## Building and testing

You need Python 3.10 or newer.

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt pytest pygerber   # Windows: .venv\Scripts\pip ...
.venv/bin/python -m pcbpro                                   # the app
.venv/bin/python -m pytest tests                             # the tests
```

`PCBPro.bat` (Windows) and `pcbpro.sh` (macOS and Linux) do the first part of
that setup on the first run.

The whole suite (about 1,850 tests) takes five to ten minutes. The slow ones
route full amp boards and play guitar clips through tube amps; run a single
file while you work (`pytest tests/test_pedal.py`) and the whole suite before
a pull request. A few UI tests open windows and need OpenGL 3.3.
`tests/test_verify.py` only runs when the KiCad footprint library is
installed (**Library › KiCad footprint libraries › Download**).

Tests must not touch your real settings or scan your disk: tests that open the
cabinet picker monkeypatch `cab_ui.settings` and `cab_ui.find_irs`. Tests that
play audio use a silent virtual device, never the speakers.

**The Windows app.** `powershell -ExecutionPolicy Bypass -File build_exe.ps1`
builds `dist\PCBPro\PCBPro.exe` with PyInstaller. Check a build with
`dist\PCBPro\PCBPro.exe --selftest OUTDIR`: it renders the example in 3D,
exports its Gerbers, simulates it in-process and in the worker process,
compiles the real-time audio model, convolves a cabinet IR, plays a tube amp
board, and writes `OUTDIR\selftest.txt` ending in `RESULT OK`.

Useful tools:

- `tools/build_examples.py` regenerates the bundled example projects
  (placed, autorouted, pours filled). Pass a group (`555`, `pedal`, `amp`,
  `metal`) to rebuild only those.
- `tools/verify_footprints.py -v` compares the built-in footprints with the
  official KiCad library, pad by pad.
- `tools/screenshot.py` and `tools/showcase.py` save quick screenshots for
  visual checks.
- `tools/make_icon.py` draws the app icon.
- `tools/docs_media/` makes the screenshots, recordings and sound clips in
  `docs/media` (see its README).
- `tools/build_site.py` builds the website.

## Things to know about the code

- The simulator runs in a spawn worker process. Scripts that start one need an
  `if __name__ == "__main__":` guard, and `pcbpro_launcher.py` calls
  `multiprocessing.freeze_support()` for the frozen app.
- `pcbpro/__init__.py` forces single-threaded BLAS before NumPy loads. The
  simulator solves many small systems, and OpenBLAS's worker threads make
  those thousands of times slower whenever the CPU is busy.
- The real-time audio kernel (`pcbpro/sim/realtime.py`) is compiled with
  numba. Its lazy Newton shortcut is for tube and diode circuits only; op-amp
  circuits must not use it.
- Amp boards carry their off-board hardware in `project.amp` (nets, settings,
  the Amp Designer's spec, and the output transformer in `ot`), which the tube
  simulation reads. Keep the wire-pad names stable.

## Documentation and the website

Every user-visible feature is documented in the guide it belongs to in
`docs/`: getting started, the layout editor, the parts library, the 3D view,
pedals, the Amp Designer, high-gain amps, amp boards, simulation, firmware,
audio, manufacturing, buying parts, how it works, or troubleshooting.
`README.md` is the front page, so it only gets a line for a headline feature.

The website is built from `docs/` and `site/` by `tools/build_site.py`. It
needs only `pip install markdown`, and `--serve` previews it on
http://localhost:8000. Pushing to `main` publishes it. In the guides, an image
of `media/gif/NAME.gif` shows as the video `media/video/NAME.mp4` on the site
when there is one. Keep media small (see `tools/docs_media/README.md`),
because every file stays in the repository's history.

## Source layout

```
pcbpro/
  app.py              entry point, --example, --selftest
  model/              the board: footprints, copper and zone geometry, connectivity, DRC, file I/O
  library/            the parts library: generated footprints (gen_*.py), the MPN catalog, LCSC/EasyEDA import,
                      KiCad libraries, My library, verification against KiCad
  route/              the autorouter
  pedal/              enclosures, drill templates, enclosure checks, build sheet, the new-pedal generator, 3D box
  amp/                tube data, HV rules and amp checks, the amp board builder and templates, tone stacks,
                      the Amp Designer (designer.py), gain staging (gainstage.py), metal pedals, demo riffs
  sim/                the circuit simulator: MNA engine, device and part models, logic, the AVR emulator (avr/),
                      audio rendering, the real-time model (realtime.py), live audio (livefx.py),
                      cabinet IRs (cabinet.py, flac.py), vacuum tubes (tubes.py), amp boards' off-board parts
                      (ampboard.py)
  export/             Gerber, Excellon, BOM and CPL, the zipped package
  fab/                fab capabilities, DFM checks, price estimates, suppliers and the shopping list
  ui/                 the Qt (PySide6) app: main window, canvas and tools, panels, 3D view, order page, and the
                      pedal, amp, simulation, audio and shop features
  resources/          example projects, the app icon, the built-in cabinet IRs
tests/                pytest suite
tools/                example builder, footprint verifier, screenshots, icon, docs media, the website build
docs/                 the guides (Markdown) and their media
site/                 the website's landing page, styles and scripts
```

## Pull requests

- Keep each pull request to one fix or feature.
- Add tests for new behaviour, especially anything with a datasheet or a
  safety rule behind it.
- Follow the style of the surrounding code.
- Run the tests before pushing, and say which OS you used.
- Update the guide in `docs/` for user-visible changes, and add them to
  `CHANGELOG.md` under "Unreleased".
- For a new footprint, enclosure or tube, link the datasheet or drawing.

## Reporting bugs

Include your OS, the PCBPro version (**Help › About**) or commit, what you did
and what happened. A saved project (`.pcbpro`) helps most; check that you have
the right to share it first.

Report anything that could make PCBPro run code from a file, or write or
delete files it shouldn't, privately, as described in
[SECURITY.md](SECURITY.md).

## License

Contributions are licensed under the [MIT License](LICENSE), like the rest of
the project.
