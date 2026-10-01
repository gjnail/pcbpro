# Security

PCBPro opens files that often come from other people: projects (`.pcbpro`),
KiCad footprints and libraries (`.kicad_mod`, `.pretty` folders), EasyEDA part
records, firmware (`.hex`), guitar recordings and speaker-cabinet impulse
responses (WAV and FLAC), and parts shared through *My library*. It also
downloads two kinds of data when you ask it to: a part's footprint from the
EasyEDA library behind LCSC (**Import any LCSC part**), and the official KiCad
footprint library as a ZIP from GitLab. Bugs in how it reads those files, or
in where it writes exports, can be security issues.

## What to report privately

- Any file PCBPro opens (a project, a footprint or library, an EasyEDA record,
  a `.hex` file, a WAV or FLAC file) that can make it run code, or write or
  delete files outside the folder you chose.
- A downloaded KiCad library or EasyEDA response that can write outside
  `Documents/PCBPro` (for example a ZIP entry with `..` in its path).
- Firmware that can escape the AVR emulator: anything a `.hex` file does that
  reaches beyond the simulated chip's memory.
- An export (Gerbers, drill files, BOM, drill template, build sheet, WAV) that
  overwrites or removes files it shouldn't.
- Anything that sends your designs or other data off the machine. PCBPro only
  connects to EasyEDA and GitLab for the two downloads above, and opens fab and
  supplier websites in your browser when you click them. The only things those
  pages receive are what the link carries, such as the search words for a part.

Crashes on broken files, wrong simulation results, DRC misses and UI bugs can
go in public issues. A design-rule check that misses a real high-voltage
spacing problem is a safety bug, but it can still be reported publicly, since
the fix helps everyone building amps.

## How to report

Use GitHub's private vulnerability reporting: open the **Security** tab of the
repository and choose **Report a vulnerability**. Include your OS, the PCBPro
version or commit, steps to reproduce, and the file that triggers it if you
can share one. Please don't open a public issue until a fix is released.

Expect a reply within a week. Fixes go into the next commit on `main`, and the
changelog credits the reporter unless they'd rather not be named.

## Supported versions

Only the latest release and the latest commit on `main` receive fixes.
