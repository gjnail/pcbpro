"""Library dialogs: LCSC / JLCPCB part import, KiCad library management and the footprint wizard."""
from __future__ import annotations

import os
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox,
                               QProgressBar, QPushButton, QSpinBox, QStackedWidget, QVBoxLayout, QWidget)

from ..library import easyeda
from ..library.kicad import OFFICIAL_ZIP, default_kicad_dirs, load_kicad_mod
from ..library.userlib import library_dir, save_part
from ..model.board import Footprint, Pad
from .icons import icon
from .panels import FootprintPreview


class _Worker(QObject):
    done = Signal(object, object)  # result, error
    progress = Signal(int, int, str)

    def __init__(self, fn, *args):
        super().__init__()
        self.fn, self.args = fn, args
        self.cancel = False

    def run(self):
        try:
            self.done.emit(self.fn(self, *self.args), None)
        except Exception as e:  # reported to the dialog
            self.done.emit(None, e)


class _Relay(QObject):
    """Lives in the GUI thread so worker signals are delivered (queued) on the GUI thread."""

    def __init__(self, on_done, on_progress, parent):
        super().__init__(parent)
        self.on_done, self.on_progress = on_done, on_progress
        self.thread = None

    @Slot(object, object)
    def done(self, res, err):
        if self.thread is not None:
            self.thread.quit()
            self.thread.wait()
        self.on_done(res, err)

    @Slot(int, int, str)
    def progress(self, a, b, msg):
        if self.on_progress:
            self.on_progress(a, b, msg)


def _run_in_thread(owner, fn, *args, on_done, on_progress=None):
    thread = QThread(owner)
    worker = _Worker(fn, *args)
    worker.moveToThread(thread)
    relay = _Relay(on_done, on_progress, owner)
    relay.thread = thread
    thread.started.connect(worker.run)
    worker.done.connect(relay.done)
    worker.progress.connect(relay.progress)
    owner._threads = getattr(owner, "_threads", []) + [(thread, worker, relay)]
    thread.start()
    return worker


# --------------------------------------------------------------------------- LCSC import

class LcscImportDialog(QDialog):
    """Import any part stocked by LCSC (and assembled by JLCPCB) using its C-number."""

    def __init__(self, parent=None, initial: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Import part from LCSC / JLCPCB")
        self.setMinimumSize(620, 560)
        self.part: easyeda.LcscPart | None = None
        self.saved_name: str | None = None
        self.place_after = False
        lay = QVBoxLayout(self)
        intro = QLabel("Every part sold by LCSC (1,000,000+ parts, including JLCPCB's assembly library) can be "
                       "imported with its footprint. Find the part on lcsc.com or jlcpcb.com/parts, copy its "
                       "<b>C-number</b> (e.g. C25804) and paste it below.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search LCSC in your browser, e.g. 'STM32G0 TSSOP-20' or '10k 0603'")
        sbtn = QPushButton("Search LCSC…")
        sbtn.clicked.connect(self._search)
        self.search.returnPressed.connect(self._search)
        row.addWidget(self.search, 1)
        row.addWidget(sbtn)
        lay.addLayout(row)
        row = QHBoxLayout()
        self.code = QLineEdit(initial)
        self.code.setPlaceholderText("LCSC part number, e.g. C2040")
        self.fetch_btn = QPushButton("Import")
        self.fetch_btn.setProperty("primary", True)
        self.fetch_btn.clicked.connect(self._fetch)
        self.code.returnPressed.connect(self._fetch)
        row.addWidget(QLabel("C-number"))
        row.addWidget(self.code, 1)
        row.addWidget(self.fetch_btn)
        lay.addLayout(row)
        row = QHBoxLayout()
        self.refresh = QCheckBox("Refresh from LCSC (ignore cached copy)")
        row.addWidget(self.refresh)
        row.addStretch(1)
        self.browser_btn = QPushButton("Open part data in browser")
        self.browser_btn.setToolTip("Opens the EasyEDA record for this C-number. Save it as a .json file and use "
                                    "'Import from file' if the direct download does not work on your network.")
        self.browser_btn.clicked.connect(self._open_api)
        file_btn = QPushButton("Import from file…")
        file_btn.setToolTip("Import a saved EasyEDA part record (.json) or an EasyEDA footprint source export")
        file_btn.clicked.connect(self._from_file)
        row.addWidget(self.browser_btn)
        row.addWidget(file_btn)
        lay.addLayout(row)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.preview = FootprintPreview()
        self.preview.setMinimumHeight(220)
        self.preview.hide()  # shown once a part has been imported (keeps room for error guidance)
        lay.addWidget(self.preview, 1)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setTextFormat(Qt.RichText)
        lay.addWidget(self.info)
        bb = QHBoxLayout()
        bb.addStretch(1)
        self.save_btn = QPushButton("Save to My library")
        self.place_btn = QPushButton("Save && place on board")
        self.place_btn.setProperty("primary", True)
        close = QPushButton("Close")
        for b in (self.save_btn, self.place_btn):
            b.setEnabled(False)
        self.save_btn.clicked.connect(lambda: self._save(False))
        self.place_btn.clicked.connect(lambda: self._save(True))
        close.clicked.connect(self.reject)
        bb.addWidget(self.save_btn)
        bb.addWidget(self.place_btn)
        bb.addWidget(close)
        lay.addLayout(bb)

    def _search(self):
        q = self.search.text().strip()
        if q:
            QDesktopServices.openUrl(QUrl(easyeda.search_url(q)))

    def _fetch(self):
        try:
            code = easyeda.normalise_lcsc(self.code.text())
        except ValueError as e:
            self.status.setText(f"<span style='color:#f0605d'>{e}</span>")
            return
        self.fetch_btn.setEnabled(False)
        self.status.setText(f"Fetching {code} from the EasyEDA / LCSC library…")
        refresh = self.refresh.isChecked()
        _run_in_thread(self, lambda w, c: easyeda.import_lcsc(c, refresh=refresh), code, on_done=self._fetched)

    def _open_api(self):
        try:
            QDesktopServices.openUrl(QUrl(easyeda.api_url(self.code.text())))
        except ValueError as e:
            self.status.setText(f"<span style='color:#f0605d'>{e}</span>")

    def _from_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import EasyEDA part record", "", "EasyEDA JSON (*.json);;All files (*)")
        if not path:
            return
        code = self.code.text().strip()
        try:
            part = easyeda.import_easyeda_file(path, easyeda.normalise_lcsc(code) if code else "")
        except Exception as e:  # malformed or unsupported file
            self._fetched(None, e)
            return
        self._fetched(part, None)

    def _fetched(self, part, err):
        self.fetch_btn.setEnabled(True)
        if err is not None:
            msg = str(err).replace("\n", "<br>")
            self.preview.hide()
            self.status.setText(f"<span style='color:#f0605d'>Import failed: {msg}</span>")
            return
        self.part = part
        fp = part.footprint
        self.preview.show()
        self.preview.set_footprint(fp)
        kinds = {}
        for p in fp.pads:
            kinds[p.kind] = kinds.get(p.kind, 0) + 1
        pads = ", ".join(f"{v} {k.upper()}" for k, v in kinds.items())
        warn = ("<br><span style='color:#f5b83d'>" + "<br>".join(part.warnings[:5]) + "</span>") if part.warnings else ""
        self.info.setText(f"<b>{part.mpn}</b> — {part.manufacturer}<br>{part.description}<br>"
                          f"Package: {part.package} · {pads} · designator {part.prefix}?<br>"
                          f"<span style='color:#8b93a1'>Always compare imported footprints with the datasheet.</span>{warn}")
        src = " (from the local cache)" if part.from_cache else ""
        self.status.setText(f"<span style='color:#3fcf8e'>✔ Imported {part.lcsc}{src}</span>")
        self.save_btn.setEnabled(True)
        self.place_btn.setEnabled(True)

    def _save(self, place: bool):
        p = self.part
        if p is None:
            return
        name = f"{p.mpn} ({p.lcsc})"
        save_part(name, p.footprint, category="LCSC imports", prefix=p.prefix, value=p.value or p.mpn, mpn=p.mpn,
                  manufacturer=p.manufacturer, lcsc=p.lcsc, description=f"{p.description} [{p.package}]", source="lcsc")
        self.saved_name = name
        self.place_after = place
        self.accept()


# --------------------------------------------------------------------------- KiCad libraries

def _download_kicad(worker, dest: Path):
    tmp = Path(tempfile.gettempdir()) / "pcbpro-kicad-footprints.zip"
    req = urllib.request.Request(OFFICIAL_ZIP, headers={"User-Agent": "PCBPro/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as out:  # noqa: S310 - fixed URL
        total = int(resp.headers.get("Content-Length") or 0)
        got = 0
        while True:
            if worker.cancel:
                raise RuntimeError("Download cancelled")
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            out.write(chunk)
            got += len(chunk)
            worker.progress.emit(got, total, f"Downloading… {got / 1e6:.1f} MB" + (f" of {total / 1e6:.0f} MB" if total else ""))
    worker.progress.emit(0, 0, "Extracting footprints…")
    staging = dest.with_name(dest.name + ".partial")
    if staging.exists():
        shutil.rmtree(staging)
    count = 0
    with zipfile.ZipFile(tmp) as zf:
        for info in zf.infolist():
            parts = Path(info.filename).parts
            if len(parts) >= 3 and parts[-2].endswith(".pretty") and parts[-1].endswith(".kicad_mod"):
                target = staging / parts[-2] / parts[-1]
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                count += 1
    if dest.exists():
        shutil.rmtree(dest)
    staging.rename(dest)
    try:
        tmp.unlink()
    except OSError:
        pass
    return count


class KicadLibraryDialog(QDialog):
    def __init__(self, index, parent=None):
        super().__init__(parent)
        self.index = index
        self.changed = False
        self.setWindowTitle("KiCad footprint libraries")
        self.setMinimumSize(640, 440)
        lay = QVBoxLayout(self)
        intro = QLabel("PCBPro can use any KiCad footprint library (.pretty folders). The official KiCad library "
                       "contains ~14,000 footprints covering practically every standard package and connector. "
                       "It is licensed CC-BY-SA 4.0 with an exception that allows its use in your designs.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.list = QListWidget()
        lay.addWidget(self.list, 1)
        self.count = QLabel()
        lay.addWidget(self.count)
        row = QHBoxLayout()
        add = QPushButton("Add folder…")
        add.clicked.connect(self._add)
        rem = QPushButton("Remove")
        rem.clicked.connect(self._remove)
        self.dl = QPushButton("Download official KiCad library")
        self.dl.setProperty("primary", True)
        self.dl.clicked.connect(self._download)
        row.addWidget(add)
        row.addWidget(rem)
        row.addStretch(1)
        row.addWidget(self.dl)
        lay.addLayout(row)
        self.bar = QProgressBar()
        self.bar.hide()
        lay.addWidget(self.bar)
        self.status = QLabel()
        lay.addWidget(self.status)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.worker = None
        self._fill()

    def _fill(self):
        self.list.clear()
        auto = set(map(str, default_kicad_dirs()))
        for d in self.index.all_kicad_dirs():
            self.list.addItem(f"{d}" + ("   (detected automatically)" if str(d) in auto else ""))
        self.count.setText(f"{len(self.index.kicad):,} KiCad footprints available")

    def _add(self):
        d = QFileDialog.getExistingDirectory(self, "Folder containing .pretty libraries (or a single .pretty folder)")
        if d:
            n = self.index.add_kicad_dir(d)
            self.changed = True
            self.status.setText(f"Added {n:,} footprints" if n else "No .kicad_mod footprints found in that folder")
            self._fill()

    def _remove(self):
        it = self.list.currentItem()
        if it is None:
            return
        path = it.text().split("   (")[0]
        if path in self.index.kicad_dirs:
            self.index.kicad_dirs.remove(path)
            self.index.reload_kicad()
            self.changed = True
            self._fill()
        else:
            self.status.setText("Automatically detected folders cannot be removed here.")

    def _download(self):
        dest = Path.home() / "Documents" / "PCBPro" / "kicad-footprints"
        if QMessageBox.question(self, "Download KiCad library",
                                f"Download the official KiCad footprint library from GitLab (about 100-200 MB) and "
                                f"install it to\n{dest}?") != QMessageBox.Yes:
            return
        self.dl.setEnabled(False)
        self.bar.show()
        self.bar.setRange(0, 0)
        self.worker = _run_in_thread(self, _download_kicad, dest, on_done=self._downloaded, on_progress=self._progress)

    def _progress(self, got, total, msg):
        if total:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(got / total * 1000))
        else:
            self.bar.setRange(0, 0)
        self.status.setText(msg)

    def _downloaded(self, count, err):
        self.bar.hide()
        self.dl.setEnabled(True)
        self.worker = None
        if err is not None:
            self.status.setText(f"<span style='color:#f0605d'>Download failed: {err}</span>")
            return
        self.index.reload_kicad()
        self.changed = True
        self.status.setText(f"<span style='color:#3fcf8e'>✔ Installed {count:,} footprints</span>")
        self._fill()

    def reject(self):
        if self.worker is not None:
            self.worker.cancel = True
        super().reject()


# --------------------------------------------------------------------------- footprint wizard

def _custom_inline(n, pitch, pad, drill, H):
    from ..library.shapes import B, _fp, _rect, composite, inline_tht
    pads = inline_tht(n, pitch, pad, drill)
    w = n * pitch
    return _fp(f"Custom_1x{n:02d}_P{pitch:g}mm", f"Custom single-row connector, {n} pins, {pitch:g} mm pitch", pads,
               _rect(-w / 2, -pitch / 2 - 0.3, w / 2, pitch / 2 + 0.3), (-w / 2, -pitch / 2, w / 2, pitch / 2),
               composite(B(-w / 2, -pitch / 2, 0, w / 2, pitch / 2, H, "#161616"), pins="tht") if H > 0 else
               {"type": "none"})


def _smd_grid(cols, rows, px, py, pw, ph, bw, bh, H):
    from ..library.shapes import B, _fp, _rect, composite
    pads = []
    n = 1
    for r in range(rows):
        for c in range(cols):
            pads.append(Pad(str(n), round((c - (cols - 1) / 2) * px, 4), round((r - (rows - 1) / 2) * py, 4), pw, ph,
                            "roundrect"))
            n += 1
    bw = bw or (cols - 1) * px + pw
    bh = bh or (rows - 1) * py + ph
    model = composite(B(-bw / 2, -bh / 2, 0.05, bw / 2, bh / 2, H, "#1e1e20")) if H > 0 else {"type": "none"}
    return _fp(f"Custom_SMD_Grid_{cols}x{rows}", f"Custom SMD pad grid {cols}x{rows}", pads,
               _rect(-bw / 2, -bh / 2, bw / 2, bh / 2, 0.1, "fab"), (-bw / 2, -bh / 2, bw / 2, bh / 2), model)


def _mount(drill, pad):
    from ..model.footprints import _fp, _circle
    plated = pad > drill
    pads = [Pad("1", 0, 0, pad if plated else drill, pad if plated else drill, "circle", "tht" if plated else "npth",
                drill)]
    r = max(pad, drill) / 2
    return _fp(f"MountingHole_{drill:g}mm{'_Pad' if plated else ''}", f"Mounting hole, drill {drill:g} mm", pads,
               [_circle(0, 0, r + 0.3, 0.12, "fab")], (-r, -r, r, r), {"type": "none"})


def _wizard_families():
    from ..library import gen_conn, gen_ic, gen_passive
    from ..library.shapes import two_terminal_smd
    from ..model import footprints as fpm

    def chip2(pw, ph, pitch, L, W, H, pol):
        model = {"type": "chip", "L": L, "W": W, "H": H, "body": "#1e1e20", "term": "#c9c9c9", "cls": "R"}
        return two_terminal_smd(f"Custom_2Pad_{L:g}x{W:g}mm", f"Custom 2-pad SMD, body {L:g}x{W:g} mm", pw, ph, pitch / 2,
                                L, W, model, polarity=bool(pol))

    I = "int"
    return {
        "Two-pad SMD (chip, diode, any 2-terminal)": ([("pw", "Pad length (X)", 1.0), ("ph", "Pad width (Y)", 1.4),
                                                        ("pitch", "Pad pitch (centre-centre)", 1.9), ("L", "Body length", 2.0),
                                                        ("W", "Body width", 1.25), ("H", "Body height", 0.6),
                                                        ("pol", "Polarity mark (0/1)", 0, I)], chip2),
        "Dual-row gull-wing (SOIC, SOP, TSSOP…)": ([("n", "Pins", 8, I), ("pitch", "Pitch", 1.27), ("E", "Lead span tip-to-tip", 6.0),
                                                    ("L", "Foot length", 0.8), ("b", "Lead width", 0.42),
                                                    ("bw", "Body width", 3.9), ("bl", "Body length", 4.9), ("H", "Height", 1.5),
                                                    ("epw", "Exposed pad W (0 = none)", 0.0), ("eph", "Exposed pad H", 0.0)],
                                                   lambda n, pitch, E, L, b, bw, bl, H, epw, eph: gen_ic.gullwing_dual(
                                                       f"Custom_SO-{n}_P{pitch:g}mm", f"Custom dual-row gull-wing, {n} pins",
                                                       int(n), pitch, E, L, b, bw, bl, H, (epw, eph) if epw > 0 else None)),
        "Quad flat pack (QFP)": ([("n", "Pins (multiple of 4)", 48, I), ("body", "Body size", 7.0), ("pitch", "Pitch", 0.5),
                                  ("H", "Height", 1.4)], lambda n, body, pitch, H: gen_ic.qfp(int(n) // 4 * 4, body, pitch, H)),
        "QFN (quad, no leads)": ([("n", "Pins (multiple of 4)", 32, I), ("body", "Body size", 5.0), ("pitch", "Pitch", 0.5),
                                  ("ep", "Exposed pad size", 3.45)], lambda n, body, pitch, ep: fpm.qfn(int(n) // 4 * 4, body,
                                                                                                          pitch, ep)),
        "DFN / SON (dual, no leads)": ([("n", "Pins (even)", 8, I), ("bw", "Body width", 3.0), ("bl", "Body length", 3.0),
                                        ("pitch", "Pitch", 0.65), ("epw", "Exposed pad W (0 = none)", 1.6),
                                        ("eph", "Exposed pad H", 2.4)],
                                       lambda n, bw, bl, pitch, epw, eph: gen_ic.dfn(int(n) // 2 * 2, bw, bl, pitch,
                                                                                     (epw, eph) if epw > 0 else None)),
        "BGA": ([("rows", "Rows", 10, I), ("cols", "Columns", 10, I), ("pitch", "Ball pitch", 0.8), ("body", "Body size", 9.0),
                 ("depop", "Depopulated centre ring", 0, I)],
                lambda rows, cols, pitch, body, depop: gen_ic.bga(int(rows), int(cols), pitch, body, int(depop))),
        "DIP (dual row through-hole)": ([("n", "Pins (even)", 16, I), ("row", "Row spacing", 7.62)],
                                        lambda n, row: gen_ic.dip(int(n) // 2 * 2, row)),
        "Pin header / socket grid": ([("cols", "Pins per row", 10, I), ("rows", "Rows", 1, I), ("pitch", "Pitch (2.54/2.0/1.27)", 2.54),
                                      ("female", "Female socket (0/1)", 0, I)],
                                     lambda cols, rows, pitch, female: gen_conn.header(
                                         int(cols), int(rows), min((2.54, 2.0, 1.27), key=lambda p: abs(p - pitch)),
                                         "female" if female else "male")),
        "Single-row THT connector (any pitch)": ([("n", "Pins", 4, I), ("pitch", "Pitch", 3.5), ("pad", "Pad diameter", 2.0),
                                                  ("drill", "Drill", 1.1), ("H", "Body height (0 = none)", 8.0)], _custom_inline),
        "Radial 2-pin (capacitor, LED, inductor)": ([("D", "Body diameter", 6.3), ("P", "Lead pitch", 2.5), ("H", "Height", 11.0)],
                                                    lambda D, P, H: fpm.cap_radial(D, P, H)),
        "Axial 2-pin (resistor, diode)": ([("pitch", "Lead pitch", 10.16), ("L", "Body length", 6.3), ("D", "Body diameter", 2.5)],
                                          lambda pitch, L, D: gen_passive.resistor_axial_p(pitch, L, D, "custom")),
        "SMD pad grid / array": ([("cols", "Columns", 4, I), ("rows", "Rows", 2, I), ("px", "Pitch X", 1.27),
                                  ("py", "Pitch Y", 5.0), ("pw", "Pad width", 0.6), ("ph", "Pad height", 2.0),
                                  ("bw", "Body width (0 = auto)", 0.0), ("bh", "Body height (0 = auto)", 0.0),
                                  ("H", "Body 3D height (0 = none)", 1.0)], _smd_grid),
        "Mounting hole": ([("drill", "Drill", 3.2), ("pad", "Pad diameter (0 = unplated)", 6.0)], _mount),
    }


class FootprintWizardDialog(QDialog):
    """Generate a footprint for any standard package from datasheet dimensions."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Footprint wizard")
        self.setMinimumSize(760, 560)
        self.families = _wizard_families()
        self.footprint: Footprint | None = None
        self.saved_name: str | None = None
        self.place_after = False
        lay = QHBoxLayout(self)
        left = QVBoxLayout()
        self.family = QComboBox()
        self.family.addItems(list(self.families))
        left.addWidget(QLabel("Package family"))
        left.addWidget(self.family)
        self.stack = QStackedWidget()
        self.fields: dict[str, dict] = {}
        for fam, (params, _fn) in self.families.items():
            w = QWidget()
            form = QFormLayout(w)
            fields = {}
            for spec in params:
                key, label, default = spec[:3]
                if len(spec) > 3 and spec[3] == "int":
                    sb = QSpinBox()
                    sb.setRange(0, 2000)
                    sb.setValue(int(default))
                else:
                    sb = QDoubleSpinBox()
                    sb.setRange(0, 500)
                    sb.setDecimals(3)
                    sb.setSingleStep(0.05)
                    sb.setSuffix(" mm")
                    sb.setValue(float(default))
                sb.valueChanged.connect(self._update)
                form.addRow(label, sb)
                fields[key] = sb
            self.fields[fam] = fields
            self.stack.addWidget(w)
        left.addWidget(self.stack)
        meta = QGroupBox("Part")
        mf = QFormLayout(meta)
        self.name = QLineEdit()
        self.prefix = QLineEdit("U")
        self.value = QLineEdit()
        self.mpn = QLineEdit()
        mf.addRow("Name", self.name)
        mf.addRow("Designator prefix", self.prefix)
        mf.addRow("Value", self.value)
        mf.addRow("MPN (optional)", self.mpn)
        left.addWidget(meta)
        left.addStretch(1)
        lay.addLayout(left, 1)
        right = QVBoxLayout()
        self.preview = FootprintPreview()
        right.addWidget(self.preview, 1)
        self.info = QLabel()
        self.info.setWordWrap(True)
        right.addWidget(self.info)
        row = QHBoxLayout()
        row.addStretch(1)
        save = QPushButton("Save to My library")
        place = QPushButton("Save && place")
        place.setProperty("primary", True)
        close = QPushButton("Close")
        save.clicked.connect(lambda: self._save(False))
        place.clicked.connect(lambda: self._save(True))
        close.clicked.connect(self.reject)
        row.addWidget(save)
        row.addWidget(place)
        row.addWidget(close)
        right.addLayout(row)
        lay.addLayout(right, 1)
        self.family.currentIndexChanged.connect(self._family_changed)
        self._family_changed(0)

    def _family_changed(self, i):
        self.stack.setCurrentIndex(i)
        self._update()

    def _update(self, *_):
        fam = self.family.currentText()
        params, fn = self.families[fam]
        kwargs = {k: (w.value()) for k, w in self.fields[fam].items()}
        try:
            fp = fn(**kwargs)
        except Exception as e:  # invalid parameter combination
            self.footprint = None
            self.preview.set_footprint(None)
            self.info.setText(f"<span style='color:#f0605d'>Cannot build footprint: {e}</span>")
            return
        self.footprint = fp
        self.preview.set_footprint(fp)
        x0, y0, x1, y1 = fp.courtyard
        self.info.setText(f"<b>{fp.name}</b><br>{len(fp.pads)} pads · courtyard {x1 - x0:.2f} x {y1 - y0:.2f} mm")
        if not self.name.isModified():
            self.name.setText(fp.name)

    def _save(self, place: bool):
        if self.footprint is None:
            return
        name = self.name.text().strip() or self.footprint.name
        self.footprint.name = name
        save_part(name, self.footprint, category="Wizard", prefix=self.prefix.text().strip() or "U",
                  value=self.value.text().strip() or name, mpn=self.mpn.text().strip(), source="user")
        self.saved_name = name
        self.place_after = place
        self.accept()


class CompareDialog(QDialog):
    """Compare a library part's land pattern pad-by-pad with a KiCad library footprint."""

    def __init__(self, part, index, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QCompleter, QTableWidget, QTableWidgetItem, QHeaderView
        from ..library.verify import KNOWN_VARIANTS, REFERENCES
        self.part = part
        self.index = index
        self.setWindowTitle(f"Check footprint: {part.name}")
        self.setMinimumSize(760, 560)
        lay = QVBoxLayout(self)
        intro = QLabel("The official KiCad library is built from manufacturer datasheets. Pick the KiCad footprint for "
                       "the exact part you will buy and PCBPro compares every pad (position, size, drill, numbering).")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        row = QHBoxLayout()
        self.ref = QComboBox()
        self.ref.setEditable(True)
        names = [p.name for p in index.kicad]
        self.ref.addItems(names)
        comp = QCompleter(names, self)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        self.ref.setCompleter(comp)
        guess = REFERENCES.get(part.name, "")
        if not guess:
            try:
                fp_name = part.make().name.lower()
                guess = next((n for n in names if n.split(":", 1)[1].lower() == fp_name), "")
            except Exception:
                guess = ""
        self.ref.setCurrentText(guess)
        go = QPushButton("Compare")
        go.setProperty("primary", True)
        go.clicked.connect(self._compare)
        row.addWidget(QLabel("KiCad footprint"))
        row.addWidget(self.ref, 1)
        row.addWidget(go)
        lay.addLayout(row)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.RichText)
        lay.addWidget(self.summary)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Ref pad", "This pad", "Position error", "Size error", "Drill error",
                                              "Status"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        lay.addWidget(self.table, 1)
        self.known = KNOWN_VARIANTS.get(part.name)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        if not names:
            self.summary.setText("<span style='color:#f5b83d'>No KiCad library is installed yet - use Library > KiCad "
                                 "footprint libraries > Download official KiCad library.</span>")
        elif guess:
            self._compare()

    def _compare(self):
        from PySide6.QtWidgets import QTableWidgetItem
        from ..library.verify import compare
        ref_part = next((p for p in self.index.kicad if p.name == self.ref.currentText().strip()), None)
        if ref_part is None:
            self.summary.setText("<span style='color:#f0605d'>Choose a footprint from the KiCad library list.</span>")
            return
        ignore = self.known[0] if self.known else set()
        res = compare(self.part.make(), ref_part.make(), self.part.name, ref_part.name, ignore)
        ok = res.ok()
        col = "#3fcf8e" if ok else "#f0605d"
        verdict = "matches the reference within tolerance" if ok else "differs from the reference"
        self.summary.setText(
            f"<b style='color:{col}'>{'✔' if ok else '✖'} {self.part.name} {verdict}</b><br>"
            f"{len(res.matched)}/{len(res.deltas)} reference pads matched, {len(res.extra)} extra · max position error "
            f"{res.max_pos:.3f} mm · max size error {res.max_size:.3f} mm · max drill error {res.max_drill:.3f} mm · "
            f"numbering errors {res.numbering_errors}"
            + (f"<br><span style='color:#8b93a1'>Known, intended difference: {self.known[1]}</span>" if self.known else ""))
        rows = list(res.deltas) + [None] * len(res.extra)
        self.table.setRowCount(len(rows))
        for r, d in enumerate(rows):
            if d is None:
                m = res.extra[r - len(res.deltas)]
                vals = ["—", m.number or "(no number)", "", "", "", "extra pad"]
            else:
                bad = d.mine is None or d.pos_err > 0.1 or d.size_err > 0.3 or d.drill_err > 0.15 or not d.number_ok
                vals = [d.ref.number or "(npth)", (d.mine.number or "(npth)") if d.mine else "MISSING",
                        f"{d.pos_err:.3f}" if d.mine else "", f"{d.size_err:.3f}" if d.mine else "",
                        f"{d.drill_err:.3f}" if d.mine else "", "check" if bad else "ok"]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c == 5 and v != "ok":
                    from PySide6.QtGui import QColor
                    it.setForeground(QColor("#f0605d"))
                self.table.setItem(r, c, it)


def import_kicad_file(parent) -> str | None:
    """Pick a .kicad_mod file, convert it and store it in My library. Returns the saved part name."""
    path, _ = QFileDialog.getOpenFileName(parent, "Import KiCad footprint", "", "KiCad footprint (*.kicad_mod)")
    if not path:
        return None
    try:
        fp = load_kicad_mod(path)
    except Exception as e:
        QMessageBox.critical(parent, "Import failed", f"Could not read {path}:\n{e}")
        return None
    save_part(fp.name, fp, category="KiCad imports", prefix="U", value=fp.name, source="user")
    return fp.name


def open_library_folder():
    d = library_dir()
    if os.name == "nt":
        os.startfile(str(d))  # noqa: S606 - the user's own library folder
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))
