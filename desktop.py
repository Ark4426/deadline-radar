"""Desktop entry point: runs DeadlineRadar locally and opens it in the browser.

This is the script PyInstaller bundles into DeadlineRadar.exe.
"""

import os
import secrets
import sys
import threading
import webbrowser
from pathlib import Path

URL = "http://127.0.0.1:5000"

# Keep data next to the .exe; PyInstaller's own extract dir is deleted on exit.
base = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
data_dir = base / "DeadlineRadar-data"
data_dir.mkdir(exist_ok=True)

# Per-install session key instead of the placeholder default in backend.config.
key_file = data_dir / "secret.key"
if not key_file.exists():
    key_file.write_text(secrets.token_hex(32), encoding="utf-8")
os.environ.setdefault("SECRET_KEY", key_file.read_text(encoding="utf-8").strip())
os.environ.setdefault("DATABASE_PATH", str(data_dir / "deadline_radar.db"))

from backend import create_app  # noqa: E402  (must import after env is set)

app = create_app()

if __name__ == "__main__":
    if not os.environ.get("DEADLINE_RADAR_NO_BROWSER"):
        threading.Timer(1, webbrowser.open, [URL]).start()
    print(f"DeadlineRadar is running at {URL} - close this window to quit.")
    # ponytail: fixed port 5000, make it configurable if it ever clashes
    app.run(host="127.0.0.1", port=5000)
