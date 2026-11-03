import sys
from pathlib import Path

# The repo root holds the shared modules (football_api, leagues, round_stats)
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))
