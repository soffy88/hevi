#!/app/.venv/bin/python
# earshot CLI shim: vendored model-free earshot package (MIT, Leonxlnx/earshot);
# hevi.audio.earshot_client expects the CLI at $HOME/.venvs/earshot/bin/earshot.
import sys

sys.path.insert(0, "/app/earshot_pkg")

from earshot.cli import main

raise SystemExit(main())
