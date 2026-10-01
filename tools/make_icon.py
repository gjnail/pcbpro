"""Render the application icon to pcbpro/resources/pcbpro.ico (used by the executable build)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)

from pcbpro.ui.icons import app_icon  # noqa: E402

out = Path(__file__).resolve().parents[1] / "pcbpro" / "resources" / "pcbpro.ico"
pm = app_icon().pixmap(256, 256)
if not pm.save(str(out), "ICO"):
    pm.save(str(out.with_suffix(".png")), "PNG")
    print("ICO writer unavailable, wrote PNG instead")
else:
    print("wrote", out)
