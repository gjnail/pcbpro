"""Turn what capture.py saved into the files the README, the guides and the website use.

    python tools/docs_media/encode_media.py            # every shot and clip
    python tools/docs_media/encode_media.py sim-555    # the named ones

Shots (out/docs_media/shots/NAME.png) become docs/media/img/NAME.webp; the gallery pictures of the bundled examples
(example-*.png) become docs/media/examples/NAME.webp. Clips (out/docs_media/clips/NAME/) become an MP4 for the
website (docs/media/video/NAME.mp4, with a NAME.jpg poster) and a GIF for the README and the guides on GitHub
(docs/media/gif/NAME.gif). Needs Pillow and FFmpeg on the PATH. Then the website's showreel
(docs/media/video/showreel.mp4) is cut together from the clips' MP4s.

Sizes: screenshots are WebP at quality 88, at most 1600 px wide; MP4s are H.264 at CRF 23, at most 1280 px wide;
GIFs are 12 fps and shrink until they are under 3.5 MB. Keep new media about this size: every file stays in the
repository's history.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "out" / "docs_media"
MEDIA = ROOT / "docs" / "media"
GIF_MAX = 3.5e6
WIDTHS = {"drill-template": 1000}  # shots shown smaller than they were grabbed
GIF_WIDTHS = {"pedal-orbit": 560, "amp-orbit": 640, "autoroute": 720, "sim-555": 800, "designer-voicings": 800}


def ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if exe is None:
        raise SystemExit("FFmpeg is not on the PATH")
    return exe


def shot(png: Path) -> Path:
    name = png.stem
    if name.startswith("example-"):
        out = MEDIA / "examples" / f"{name[len('example-'):]}.webp"
        width = 960
    else:
        out = MEDIA / "img" / f"{name}.webp"
        width = WIDTHS.get(name, 1600)
    out.parent.mkdir(parents=True, exist_ok=True)
    im = Image.open(png).convert("RGB")
    if im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    im.save(out, "WEBP", quality=88, method=6)
    return out


def clip(folder: Path) -> list[Path]:
    name = folder.name
    meta = json.loads((folder / "frames.json").read_text(encoding="utf-8"))
    frames = meta["frames"]
    with tempfile.TemporaryDirectory() as tmp:
        concat = Path(tmp) / "frames.txt"
        lines = []
        for f, d in frames:
            lines += [f"file '{(folder / f).as_posix()}'", f"duration {max(d, 1 / 60):.4f}"]
        lines.append(f"file '{(folder / frames[-1][0]).as_posix()}'")  # the concat demuxer drops the last duration
        concat.write_text("\n".join(lines) + "\n", encoding="utf-8")
        video = MEDIA / "video" / f"{name}.mp4"
        gif = MEDIA / "gif" / f"{name}.gif"
        poster = MEDIA / "video" / f"{name}.jpg"
        for p in (video, gif):
            p.parent.mkdir(parents=True, exist_ok=True)
        w = Image.open(folder / frames[0][0]).width
        scale = f"scale={min(w, 1280) // 2 * 2}:-2:flags=lanczos"
        subprocess.run([ffmpeg(), "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat),
                        "-vf", f"{scale},fps=30", "-c:v", "libx264", "-preset", "slow", "-crf", "23",
                        "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", str(video)], check=True)
        im = Image.open(folder / frames[meta.get("poster", 0)][0]).convert("RGB")
        if im.width > 1280:
            im = im.resize((1280, round(im.height * 1280 / im.width)), Image.LANCZOS)
        im.save(poster, "JPEG", quality=86)
        width = GIF_WIDTHS.get(name, 720)
        while True:
            vf = (f"fps=12,scale={width}:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff:reserve_transparent=0[p];"
                  f"[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle")
            subprocess.run([ffmpeg(), "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat),
                            "-vf", vf, "-gifflags", "-transdiff", "-loop", "0", str(gif)], check=True)
            if gif.stat().st_size <= GIF_MAX or width <= 360:
                break
            width = int(width * 0.85)
    return [video, poster, gif]


# (clip, start s, length s) for the showreel at the top of the website, joined with short crossfades
REEL = [("pedal-orbit", 0.0, 6.0), ("designer-voicings", 1.6, 6.4), ("autoroute", 0.0, 6.0), ("sim-555", 0.5, 5.0),
        ("amp-orbit", 0.0, 6.5)]
FADE = 0.5


def showreel() -> list[Path]:
    video = MEDIA / "video"
    args, chains = [ffmpeg(), "-y", "-loglevel", "error"], []
    for i, (name, start, length) in enumerate(REEL):
        args += ["-ss", f"{start}", "-t", f"{length}", "-i", str(video / f"{name}.mp4")]
        chains.append(f"[{i}:v]scale=1280:720:force_original_aspect_ratio=decrease:flags=lanczos,"
                      f"pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=0x0b0d10,setsar=1,fps=30,format=yuv420p[v{i}]")
    prev, offset = "v0", 0.0
    for i in range(1, len(REEL)):
        offset += REEL[i - 1][2] - FADE
        out = f"x{i}"
        chains.append(f"[{prev}][v{i}]xfade=transition=fade:duration={FADE}:offset={offset:.3f}[{out}]")
        prev = out
    out = video / "showreel.mp4"
    subprocess.run(args + ["-filter_complex", ";".join(chains), "-map", f"[{prev}]", "-c:v", "libx264", "-preset",
                           "slow", "-crf", "24", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", str(out)],
                   check=True)
    poster = video / "showreel.jpg"
    subprocess.run([ffmpeg(), "-y", "-loglevel", "error", "-ss", "2.0", "-i", str(out), "-frames:v", "1", "-q:v", "3",
                    str(poster)], check=True)
    return [out, poster]


def main(argv: list[str]) -> None:
    names = set(a for a in argv if not a.startswith("-"))
    done = []
    for png in sorted((SRC / "shots").glob("*.png")):
        if not names or png.stem in names:
            done.append(shot(png))
    for folder in sorted((SRC / "clips").glob("*")):
        if (folder / "frames.json").exists() and (not names or folder.name in names):
            done += clip(folder)
    if not names or "showreel" in names:
        done += showreel()
    total = 0
    for p in done:
        total += p.stat().st_size
        print(f"{p.relative_to(ROOT).as_posix():48} {p.stat().st_size / 1e3:8.0f} kB")
    print(f"{len(done)} files, {total / 1e6:.1f} MB")


if __name__ == "__main__":
    main(sys.argv[1:])
