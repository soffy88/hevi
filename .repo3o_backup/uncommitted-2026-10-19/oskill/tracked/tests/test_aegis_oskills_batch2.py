import sys
from unittest.mock import MagicMock

sys.modules["docker"] = MagicMock()
sys.modules["docker.errors"] = MagicMock()


# === container_health_aggregate tests ===
