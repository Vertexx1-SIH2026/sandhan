"""Makes `import app...` work when a script is run as `python scripts/x.py`
from any directory (the first prototype's seed script crashed with
ModuleNotFoundError: No module named 'app')."""
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
