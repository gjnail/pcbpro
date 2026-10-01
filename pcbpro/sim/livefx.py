"""Live guitar through the circuit: a full-duplex, low-latency audio stream (PortAudio via sounddevice) driving the
real-time circuit model. It runs in its own process so the interface never interrupts the audio.

Signal chain per block: input channel -> volts (full scale = ``in_volts``) -> circuit (or bypass) -> DC blocker ->
speaker cabinet IR (optional) -> output gain -> soft safety limiter -> every output channel. The circuit output is
divided by ``out_ref`` volts (1 V for pedals; an amplifier's speaker voltage at rated power).
"""
from __future__ import annotations

import math
import threading
import time
import traceback

import numpy as np

from .realtime import dcblock

HOST_PREFERENCE = ("Windows WASAPI", "ASIO", "Windows DirectSound", "MME", "Core Audio", "ALSA", "JACK Audio")


def list_devices() -> dict:
    """Host APIs and their input / output devices: {"hostapis": [...], "inputs": [...], "outputs": [...]}."""
    import sounddevice as sd
    apis = sd.query_hostapis()
    devs = sd.query_devices()
    out = {"hostapis": [], "inputs": [], "outputs": []}
    for i, h in enumerate(apis):
        out["hostapis"].append({"index": i, "name": h["name"], "default_in": h.get("default_input_device", -1),
                                "default_out": h.get("default_output_device", -1)})
    for d in devs:
        rec = {"index": d["index"], "name": d["name"], "hostapi": d["hostapi"], "rate": d["default_samplerate"],
               "in": d["max_input_channels"], "out": d["max_output_channels"]}
        if d["max_input_channels"] > 0:
            out["inputs"].append(rec)
        if d["max_output_channels"] > 0:
            out["outputs"].append(rec)
    return out


def preferred_hostapi(devs: dict) -> int:
    names = {h["name"]: h["index"] for h in devs["hostapis"]}
    for n in HOST_PREFERENCE:
        if n in names:
            return names[n]
    return devs["hostapis"][0]["index"] if devs["hostapis"] else 0


class LiveEngine:
    def __init__(self, project, opts: dict):
        from .realtime import RealtimeModel, dcblock
        dcblock(np.zeros(4), np.zeros(4), 0.9, np.zeros(2))  # compile before the stream starts
        self.opts = opts
        self.rate = float(opts.get("rate", 48000))
        self.model = RealtimeModel(project, opts.get("in", "IN"), opts.get("out", "OUT"), opts.get("controls"),
                                   self.rate, int(opts.get("oversample", 2)))
        self.model.warm_up()
        self.model.settle(0.4)
        self.notices: list[str] = []
        if opts.get("cpu_check", True):
            self._cpu_check(project, opts)
        self.channel = int(opts.get("channel", 0))
        self.in_volts = float(opts.get("in_volts", 1.0))
        self.out_ref = float(opts.get("out_ref", 1.0)) or 1.0
        self.out_gain = 10 ** (float(opts.get("out_db", -12.0)) / 20)
        self.bypass = bool(opts.get("bypass", False))
        self.dc_a = math.exp(-2 * math.pi * 8.0 / self.rate)
        self.dc_state = np.zeros(2)
        self.peak_in = 0.0
        self.peak_out = 0.0
        self.load = 0.0
        self.load_max = 0.0
        self.xruns = 0
        self.clipped = 0
        self.lock = threading.Lock()
        self.pending: dict = {}
        self.block = int(opts.get("block", 128))
        self.cab = None  # Convolver, swapped in by the audio thread
        self.cab_name = ""
        self._cab_seq = 0
        self._cab_next = (0, None)  # (sequence, Convolver or None) handed from the control thread
        if opts.get("cab"):
            self.set_cab(opts["cab"])
            self._cab_seq, self.cab = self._cab_next

    def _cpu_check(self, project, opts) -> None:
        """Measure the circuit's real-time cost first: lower the oversampling if it cannot keep up, and refuse a
        circuit that is too heavy for this computer even without it (it would only stutter)."""
        from .realtime import RealtimeModel
        load = self.model.benchmark(0.1, 0.5 * float(opts.get("in_volts", 1.0)))
        while load > 0.75 and self.model.R > 1:
            r = self.model.R // 2
            self.model = RealtimeModel(project, opts.get("in", "IN"), opts.get("out", "OUT"), opts.get("controls"),
                                       self.rate, r)
            self.model.warm_up()
            self.model.settle(0.4)
            load = self.model.benchmark(0.1, 0.5 * float(opts.get("in_volts", 1.0)))
            self.notices.append(f"Oversampling lowered to {r}× so this circuit keeps up "
                                f"(about {load * 100:.0f} % of a CPU core)")
        if load > 0.95:
            raise RuntimeError(f"this circuit needs about {load * 100:.0f} % of a CPU core to run in real time, more "
                               "than this computer has. Use Audio play-through to hear it (it renders offline).")
        self.cpu_estimate = load

    # ------------------------------------------------------------------ control (worker main thread)
    def set_control(self, key: str, value) -> None:
        self.model.set_control(key, value)

    def set_cab(self, path) -> None:
        """Load a cabinet IR (or None for no cabinet); the audio thread crossfades to it over one block."""
        from .cabinet import Convolver, describe, load_ir
        try:
            conv = Convolver(load_ir(path, self.rate), self.block) if path else None
        except (OSError, ValueError) as e:
            raise ValueError(f"Could not use the cabinet IR '{path}': {getattr(e, 'strerror', None) or e}") from e
        self.cab_name = " · ".join(describe(path)) if path else ""
        self._cab_next = (self._cab_next[0] + 1, conv)

    def command(self, msg) -> None:
        cmd = msg[0]
        if cmd == "control":
            self.set_control(msg[1], msg[2])
        elif cmd == "bypass":
            self.bypass = bool(msg[1])
        elif cmd == "out_db":
            self.out_gain = 10 ** (float(msg[1]) / 20)
        elif cmd == "in_volts":
            self.in_volts = float(msg[1])
        elif cmd == "channel":
            self.channel = int(msg[1])
        elif cmd == "cab":
            self.set_cab(msg[1])

    # ------------------------------------------------------------------ audio thread
    def _cabinet(self, x: np.ndarray) -> np.ndarray:
        seq, nxt = self._cab_next
        if seq != self._cab_seq:  # a new cabinet: crossfade from the old one over this block
            old = self.cab
            self._cab_seq, self.cab = seq, nxt
            yo = old.process(x) if old is not None else x
            yn = nxt.process(x) if nxt is not None else x
            r = np.linspace(0.0, 1.0, len(x))
            return yo * (1.0 - r) + yn * r
        return self.cab.process(x) if self.cab is not None else x

    def callback(self, indata, outdata, frames, time_info, status):
        t0 = time.perf_counter()
        if status:
            if status.input_overflow or status.output_underflow:
                self.xruns += 1
        ch = min(self.channel, indata.shape[1] - 1)
        x = indata[:, ch].astype(np.float64)
        self.peak_in = max(self.peak_in * 0.9, float(np.max(np.abs(x))) if frames else 0.0)
        if self.bypass:
            y = x * self.in_volts
            # keep the circuit running silently so switching back is seamless
            self.model.process_block(np.zeros(frames))
        else:
            y = self.model.process_block(x * self.in_volts) / self.out_ref
        out = np.empty(frames)
        dcblock(y, out, self.dc_a, self.dc_state)  # 8 Hz DC blocker
        out = self._cabinet(out) * self.out_gain
        big = np.abs(out) > 0.8
        if big.any():  # soft safety limiter above -2 dBFS
            self.clipped += 1
            s = np.sign(out[big])
            out[big] = s * (0.8 + 0.2 * np.tanh((np.abs(out[big]) - 0.8) / 0.2))
        self.peak_out = max(self.peak_out * 0.9, float(np.max(np.abs(out))) if frames else 0.0)
        outdata[:] = out.astype(np.float32)[:, None]
        dt = time.perf_counter() - t0
        ld = dt / (frames / self.rate) if frames else 0.0
        self.load = 0.9 * self.load + 0.1 * ld
        self.load_max = max(self.load_max * 0.995, ld)

    def status(self, stream) -> dict:
        lat = stream.latency if stream is not None else (0, 0)
        if isinstance(lat, (int, float)):
            lat = (lat, lat)
        return {"in": self.peak_in, "out": self.peak_out, "load": self.load, "load_max": self.load_max,
                "xruns": self.xruns, "latency": (float(lat[0]) + float(lat[1])) * 1000.0,
                "nonconv": int(self.model.stats[0]), "limiter": self.clipped, "notes": self.model.notes,
                "rate": self.rate, "cab": self.cab_name}


def open_stream(engine: LiveEngine, opts: dict):
    """Open the full-duplex stream, falling back from exclusive to shared WASAPI mode."""
    import sounddevice as sd
    din, dout = int(opts["in_device"]), int(opts["out_device"])
    ii = sd.query_devices(din)
    oi = sd.query_devices(dout)
    in_ch = max(1, min(int(ii["max_input_channels"]), max(engine.channel + 1, 1)))
    if "WASAPI" in sd.query_hostapis(ii["hostapi"])["name"]:
        in_ch = int(ii["max_input_channels"])  # WASAPI wants the device's channel count
    out_ch = int(oi["max_output_channels"]) if "WASAPI" in sd.query_hostapis(oi["hostapi"])["name"] else \
        min(2, int(oi["max_output_channels"]))
    block = int(opts.get("block", 128))
    attempts = []
    if opts.get("exclusive") and "WASAPI" in sd.query_hostapis(ii["hostapi"])["name"]:
        attempts.append((sd.WasapiSettings(exclusive=True), sd.WasapiSettings(exclusive=True)))
    attempts.append((None, None))
    last = None
    for extra in attempts:
        try:
            st = sd.Stream(device=(din, dout), samplerate=engine.rate, blocksize=block, dtype="float32",
                           channels=(in_ch, out_ch), latency="low", callback=engine.callback,
                           extra_settings=extra if extra[0] is not None else None)
            st.start()
            return st, ("exclusive" if extra[0] is not None else "shared")
        except Exception as e:  # try the next mode
            last = e
    raise RuntimeError(f"Could not open the audio devices: {last}")


def live_worker(conn, project_dict: dict, opts: dict) -> None:  # pragma: no cover - child process
    import sys

    from ..model.board import Project
    # loading a cabinet IR runs Python on this thread: hand the GIL to the audio callback within 0.5 ms
    sys.setswitchinterval(0.0005)
    stream = None
    try:
        conn.send({"stage": "Compiling the circuit…"})
        engine = LiveEngine(Project.from_dict(project_dict), opts)
        conn.send({"stage": "Opening the audio devices…"})
        stream, mode = open_stream(engine, opts)
        conn.send({"started": True, "mode": mode, "notes": engine.notices + engine.model.notes,
                   "sizes": engine.model.sizes})
        last = 0.0
        while True:
            while conn.poll():
                msg = conn.recv()
                if msg[0] == "stop":
                    return
                try:
                    engine.command(msg)
                except Exception as e:  # e.g. an unreadable IR file: keep playing
                    conn.send({"notice": f"{e}"})
            now = time.perf_counter()
            if now - last > 0.05:
                last = now
                conn.send({"status": engine.status(stream)})
            time.sleep(0.01)
    except (EOFError, BrokenPipeError, OSError):
        return
    except Exception as e:
        try:
            conn.send({"error": f"{e}", "trace": traceback.format_exc()})
        except Exception:
            pass
    finally:
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
