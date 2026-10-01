# Keyboard shortcuts and command line

Press **F1** in the app for the same list.

## Tools

| Key | Tool |
|---|---|
| S or Esc | Select and move |
| X | Route tracks |
| V | Place a via (while routing: a via and a layer change) |
| Z | Copper zone |
| B | Board outline |
| T | Text |
| M | Measure |
| N | Connect pads (edit the netlist) |
| P | Place the part selected in the Library |

## Editing

| Key | Action |
|---|---|
| R / Shift+R | Rotate the selection by 90° either way |
| F | Flip to the other side |
| Del | Delete |
| Ctrl+D | Duplicate |
| Arrows | Nudge by one grid step (Shift: ten) |
| U | Select the whole trace |
| E or double-click | Properties |
| Ctrl+A | Select all |
| Ctrl+Z / Ctrl+Y | Undo / redo |

## Routing

| Key | Action |
|---|---|
| W / Shift+W | Wider / narrower track |
| / | Switch the 45° corner posture |
| Backspace | Remove the last corner |
| Enter or double-click | Finish the route |
| V | Via and change layer |

## View

| Key | Action |
|---|---|
| Wheel | Zoom at the cursor |
| Middle-drag, right-drag or Space + drag | Pan |
| Home | Fit the board |
| L, Page Up, Page Down | Change the active copper layer |
| F3 | The 3D view |
| F8 | Run the design rule check |

## 3D view

| Key | Action |
|---|---|
| Left-drag | Orbit |
| Right-drag | Pan |
| Wheel | Zoom |
| Double-click or Home | Fit |
| 1 / 2 / 3 / 0 | Top / bottom / front / iso |
| 4 / 6 / 8 | Left / right / back |

## Simulation

| Key | Action |
|---|---|
| F5 | Run or pause the circuit |
| Shift+F5 or Esc | Stop |
| Click or hold | Operate a switch or press a button |
| Drag or scroll on a pot | Turn the knob |
| Double-click a net | Probe it on the oscilloscope |
| Ctrl+Shift+L | Play live: guitar through the circuit |

## Menus

| Key | Command |
|---|---|
| Ctrl+N | New board |
| Ctrl+Shift+N | New pedal |
| Ctrl+Alt+A | Amp Designer |
| Ctrl+O, Ctrl+S, Ctrl+Shift+S | Open, save, save as |
| Ctrl+E | Export Gerbers, drills, BOM and CPL |
| Ctrl+Shift+A | Autoroute |
| Ctrl+B | Refill zones |
| Ctrl+Shift+O | Order PCBs |
| Ctrl+Shift+B | Buy components |
| F1 | Keyboard shortcuts |
| Ctrl+Q | Exit |

## Command line

```bash
PCBPro.exe [project.pcbpro] [--example] [--no-welcome] [--selftest DIR]
python -m pcbpro [project.pcbpro] [--example] [--no-welcome] [--selftest DIR]
```

| Argument | Effect |
|---|---|
| `project.pcbpro` | Opens that project |
| `--example` | Opens the demo board (the 555 LED flasher) |
| `--no-welcome` | Skips the start screen |
| `--selftest DIR` | Checks an installed build, then exits. It renders the example in 3D, exports its Gerbers to `DIR`, simulates it in-process and in a worker process, compiles the real-time audio model and runs a block through it, convolves a built-in cabinet IR, plays the Tweed Champ amp board, and writes `DIR/selftest.txt` ending in `RESULT OK` or `RESULT FAIL`. On a machine without a GPU, set `PCBPRO_SELFTEST_NO_GPU=1` to make the 3D step optional. |

### Scripts in `tools/`

From a source checkout, with the app's environment:

| Script | What it does |
|---|---|
| `tools/build_examples.py [555 pedal amp metal]` | Regenerates the bundled example projects (placed, autorouted, pours filled), or only the named groups |
| `tools/verify_footprints.py [-v]` | Compares the built-in footprints with the official KiCad library, pad by pad |
| `tools/screenshot.py OUTDIR` | Saves screenshots of the example's layout, DRC, 3D views and order page |
| `tools/showcase.py OUTDIR` | Places a wide range of library parts on one board and saves its layout and 3D views |
| `tools/make_icon.py` | Draws the app icon (`pcbpro/resources/pcbpro.ico`) |
| `tools/docs_media/capture.py` | The screenshots and screen recordings in `docs/media` |
| `tools/docs_media/audio_clips.py` | The sound clips on the website |
| `tools/build_site.py [--serve]` | Builds the website from `docs/` and `site/` |
| `tools/third_party_licenses.py OUT` | Collects the licences of the libraries the Windows app bundles |
