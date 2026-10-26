"""Application data stays outside the source checkout."""
import os
from pathlib import Path
DEMO = os.getenv("SCHEDULOR_DEMO") == "1"
DATA_DIR = Path(os.getenv("SCHEDULOR_DATA_DIR", str(Path.home() / "Library/Application Support" / ("Schedulor-Demo" if DEMO else "Schedulor")))).expanduser()
DATA_DIR.mkdir(parents=True, exist_ok=True)
if DEMO:
    os.environ["NOTES_BACKEND"] = "sqlite"
