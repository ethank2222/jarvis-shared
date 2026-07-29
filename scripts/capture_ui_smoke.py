from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from PIL import ImageGrab


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
os.environ["JARVIS_DATA_DIR"] = str(WORKSPACE_ROOT / "tmp_smoke" / "visual")
sys.path.insert(0, str(WORKSPACE_ROOT))

from jarvis_app.main import build_app  # noqa: E402


def main() -> None:
    app = build_app()
    app.root.attributes("-topmost", True)
    app.root.lift()
    app.root.update_idletasks()
    app._set_tts_activity(True)

    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline:
        app.root.update()
        time.sleep(0.02)

    x = app.root.winfo_rootx()
    y = app.root.winfo_rooty()
    width = app.root.winfo_width()
    height = app.root.winfo_height()
    print(
        "Geometry:",
        f"root={width}x{height}",
        f"entry=({app.entry.winfo_rootx()},{app.entry.winfo_rooty()}) "
        f"{app.entry.winfo_width()}x{app.entry.winfo_height()}",
    )
    output = WORKSPACE_ROOT / "tmp_smoke" / "jarvis-redesign.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    ImageGrab.grab(bbox=(x, y, x + width, y + height), all_screens=True).save(output)
    app.recognizer.stop()
    app.root.destroy()
    print(f"Captured {width}x{height} to {output}")


if __name__ == "__main__":
    main()
