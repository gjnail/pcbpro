# Docs media

These scripts make the screenshots, screen recordings, sound clips and pictures in `docs/media`, which the README,
the guides and the website use. Everything in them comes from PCBPro itself. The working files go to
`out/docs_media/`, which is not committed. Use the app's environment (`.venv`) for all of them.

## Screenshots and recordings

`capture.py` opens the app on screen (OpenGL needs a real window) and drives it: it loads the examples, opens the
dialogs, runs the simulator, and turns the 3D view. It uses throwaway settings in `out/docs_media/settings.ini`, so
your own recent files, window layout and cabinet list are left alone; it never searches your PC for cabinet IRs, shows
made-up audio devices in the Play live dialog, and never plays sound.

```bash
python tools/docs_media/capture.py --list                 # the jobs
python tools/docs_media/capture.py                        # all of them (a few minutes)
python tools/docs_media/capture.py pedal designer sim     # just these
python tools/docs_media/encode_media.py                   # PNG -> WebP, frames -> MP4 + GIF, and the showreel
```

`encode_media.py` writes:

- `docs/media/img/NAME.webp` for each screenshot (WebP at quality 88, at most 1600 px wide);
- `docs/media/examples/NAME.webp` for the examples gallery;
- `docs/media/video/NAME.mp4` and a `NAME.jpg` poster for each recording (H.264 at CRF 23), shown on the website;
- `docs/media/gif/NAME.gif` for each recording (12 fps, under 3.5 MB), shown in the README and the guides on GitHub;
- `docs/media/video/showreel.mp4`, the montage at the top of the website.

It needs FFmpeg on the PATH and Pillow.

## Sound clips

`audio_clips.py` renders guitar clips through Amp Designer voicings and the bundled pedals with the same simulator as
the app's Listen tab, adds a built-in cabinet IR, levels them to the same loudness and encodes them as MP3 for the
website's Listen section. `docs/media/audio/clips.json` holds their titles and captions.

```bash
python tools/docs_media/audio_clips.py --list
python tools/docs_media/audio_clips.py               # renders what's missing in out/docs_media/audio, encodes all
python tools/docs_media/audio_clips.py modern        # renders one again
```

## Icons and link previews

`make_brand.py` writes the site's icons (`icon-256.png`, `icon-64.png`), the website's link preview (`og.jpg`) and
`social-preview.png`, which goes in the GitHub repository's **Settings › Social preview** (GitHub only takes it by
hand). Run it after the 3D renders exist.

## Sizes

Keep new media about the size of what's there: screenshots under 200 kB, MP4s about 100 kB per second, GIFs under
3.5 MB. Every file stays in the repository's history.
