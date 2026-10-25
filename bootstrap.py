"""Use bundled libraries first; analysis tools are a source-checkout fallback."""
import sys
from pathlib import Path
player = Path(__file__).resolve().parent
bundled = player / 'runtime' / 'Lib' / 'site-packages'
local = player.parent / 'analysis_tools'
if bundled.is_dir():
    if sys.version_info[:2] == (3, 12):
        sys.path.insert(0, str(bundled))
elif local.is_dir():
    sys.path.insert(0, str(local))
