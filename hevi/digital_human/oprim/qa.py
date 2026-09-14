"""Deprecated compatibility module alias; implementation remains Layer4-owned."""

import importlib
import sys

sys.modules[__name__] = importlib.import_module("hevi.digital_human.layer4.atoms_qa")
