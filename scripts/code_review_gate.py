#!/usr/bin/env python3
"""Optional PR gate CLI.  See hevi.qa.code_review_gate and the attribution file.

    python3 scripts/code_review_gate.py <review_dir>

Exit 0 = pass, 1 = block.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hevi.qa.code_review_gate import main

if __name__ == "__main__":
    sys.exit(main())
