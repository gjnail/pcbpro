# Releasing PCBPro

Releases are built by [`.github/workflows/release.yml`](../.github/workflows/release.yml).
Nothing is published until you publish the draft release it creates.

## Try the build first

**Actions › Release › Run workflow** builds the Windows download without making a release. Use it after changing
the workflow, `pcbpro_launcher.py`, the resources or the dependencies. The zip is attached to the run.

## Make a release

1. Set the new version in `pcbpro/__init__.py` (`__version__`) and in `pyproject.toml`.
2. In `CHANGELOG.md`, move everything under `## [Unreleased]` into a new `## [x.y.z] - YYYY-MM-DD` section, and
   update the links at the bottom. That section becomes the release notes.
3. Commit, then tag and push:

   ```
   git tag vx.y.z
   git push origin main vx.y.z
   ```

4. The workflow checks that the tag matches both version numbers and that the changelog has a section for it. It
   builds `PCBPro.exe` with PyInstaller, runs the packaged app's own self-test (`--selftest`: Gerber export, both
   simulation back ends, the real-time audio model, a cabinet IR and a tube amp; GitHub's machines have no GPU, so
   `PCBPRO_SELFTEST_NO_GPU` makes the 3D step optional there), collects the licences,
   zips `dist/PCBPro` as `PCBPro-x.y.z-windows-x64.zip`, and opens a draft release with the zip,
   `SHA256SUMS.txt` and a build provenance attestation.
5. Look over the draft on the Releases page, download the zip and try it, then click **Publish release**.

If something is wrong before publishing, delete the draft and the tag (`git push origin :vx.y.z`), fix it, and tag
again.

## Licences

Every download includes `LICENSE` and `THIRD-PARTY-LICENSES.txt`: Python's licence, and the name, version, licence
and full licence texts of every library the app bundles (PySide6 and Qt, NumPy, Shapely, numba and llvmlite,
PyOpenGL, sounddevice and PortAudio, mapbox-earcut, cffi, pycparser). Qt is used under the LGPL v3, whose text its
wheels don't include, so the FSF's LGPL and GPL texts are kept in `tools/licenses` and added too.
`tools/third_party_licenses.py` writes the file; if a new dependency is added, add it to the list at the top of that
script.

## Code signing

The download isn't signed yet, so Windows SmartScreen warns the first time it runs. Signing (for example through
SignPath Foundation, as Heft does) would remove the warning; it needs a signing step between the build and the
package steps.
