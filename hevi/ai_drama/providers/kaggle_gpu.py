"""KaggleGPUProvider: batch jobs on Kaggle's free T4 x2, no tunnel.

Uses the official Kaggle CLI only:

  kaggle kernels push -p <dir>
  kaggle kernels status <owner>/<slug>
  kaggle kernels output <owner>/<slug> -p <out>

Credentials come from KAGGLE_USERNAME / KAGGLE_KEY (or ~/.kaggle/kaggle.json).
Jobs have a hard timeout and are never kept alive as a service.  Without
credentials ``available()`` is false and the caller skips the provider.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any


class KaggleGPUProvider:
    name = "kaggle_gpu"

    def __init__(self, *, timeout_s: int = 3600) -> None:
        self.timeout_s = timeout_s

    def available(self) -> tuple[bool, str]:
        if not shutil.which("kaggle"):
            return False, "kaggle CLI 未安装（pip install kaggle）"
        if (not os.environ.get("KAGGLE_USERNAME") or not os.environ.get("KAGGLE_KEY")) and not (
            Path.home() / ".kaggle" / "kaggle.json").is_file():
            return False, "KAGGLE_USERNAME/KAGGLE_KEY 未设置"
        return True, "kaggle CLI and credentials present"

    def _run(self, args: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout)

    def submit(self, kernel_dir: str | Path, *, out_dir: str | Path | None = None) -> dict[str, Any]:
        ok, reason = self.available()
        if not ok:
            raise RuntimeError(f"KaggleGPUProvider 不可用: {reason}")
        kernel_dir = Path(kernel_dir)
        meta_path = kernel_dir / "kernel-metadata.json"
        if not meta_path.is_file():
            raise RuntimeError("kernel 目录缺少 kernel-metadata.json")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        slug = f"{meta.get('id', '')}"
        if "/" not in slug:
            raise RuntimeError("kernel-metadata.json 的 id 必须是 owner/slug")
        pushed = self._run(["kaggle", "kernels", "push", "-p", str(kernel_dir)], timeout=300)
        if pushed.returncode != 0:
            raise RuntimeError(f"kaggle kernels push 失败: {pushed.stderr[-800:]}")
        deadline = time.time() + self.timeout_s
        status = ""
        while time.time() < deadline:
            time.sleep(30)
            proc = self._run(["kaggle", "kernels", "status", slug], timeout=120)
            status = (proc.stdout + proc.stderr).strip()
            low = status.lower()
            if "complete" in low or "succeeded" in low:
                break
            if "error" in low or "failed" in low or "cancel" in low:
                raise RuntimeError(f"Kaggle kernel 失败: {status[-800:]}")
        else:
            raise RuntimeError(f"Kaggle kernel 超时 ({self.timeout_s}s): {status[-400:]}")
        out_dir = Path(out_dir or kernel_dir / "output")
        out_dir.mkdir(parents=True, exist_ok=True)
        pulled = self._run(["kaggle", "kernels", "output", slug, "-p", str(out_dir)], timeout=600)
        if pulled.returncode != 0:
            raise RuntimeError(f"kaggle kernels output 失败: {pulled.stderr[-800:]}")
        return {"kernel": slug, "status": status, "output_dir": str(out_dir),
                "files": sorted(p.name for p in out_dir.iterdir())}

    def write_probe(self, out_dir: str | Path, *, owner: str | None = None) -> Path:
        """Write a minimal probe kernel: nvidia-smi + optional MuseTalk 5 s."""
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        owner = owner or os.environ.get("KAGGLE_USERNAME", "your-username")
        meta = {
            "id": f"{owner}/hevi-musetalk-probe",
            "title": "hevi musetalk probe",
            "code_file": "probe.ipynb",
            "language": "python",
            "kernel_type": "notebook",
            "is_private": True,
            "enable_gpu": True,
            "enable_internet": True,
            "machine_shape": "NvidiaTeslaT4",
            "dataset_sources": [],
            "competition_sources": [],
            "kernel_sources": [],
        }
        (out / "kernel-metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        notebook = {
            "cells": [
                {
                    "cell_type": "markdown",
                    "metadata": {},
                    "source": ["# hevi MuseTalk probe\n", "nvidia-smi + one 5 s MuseTalk run when the model dataset is attached.\n"],
                },
                {
                    "cell_type": "code",
                    "metadata": {},
                    "execution_count": None,
                    "outputs": [],
                    "source": [
                        "!nvidia-smi\n",
                        "import os, glob\n",
                        "print('HOME', os.getcwd())\n",
                        "print('datasets', glob.glob('/kaggle/input/*'))\n",
                    ],
                },
                {
                    "cell_type": "code",
                    "metadata": {},
                    "execution_count": None,
                    "outputs": [],
                    "source": [
                        "# MuseTalk 5 s probe. Attach a private dataset containing MuseTalk/ + models/ + a 5 s wav.\n",
                        "import glob, os, subprocess, sys\n",
                        "home = '/kaggle/input/musetalk-min'\n",
                        "if not os.path.isdir(home):\n",
                        "    print('MISSING dataset /kaggle/input/musetalk-min; probe stops after nvidia-smi')\n",
                        "    sys.exit(0)\n",
                        "print(subprocess.run(['python', home + '/MuseTalk/scripts/inference.py', '--help'], capture_output=True, text=True).stdout[:2000])\n",
                        "# Actual invocation depends on the uploaded MuseTalk snapshot; record the command in the job log.\n",
                    ],
                },
            ],
            "metadata": {
                "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                "language_info": {"name": "python", "version": "3.11"},
            },
            "nbformat": 4,
            "nbformat_minor": 5,
        }
        (out / "probe.ipynb").write_text(json.dumps(notebook, ensure_ascii=False, indent=1), encoding="utf-8")
        (out / "README.md").write_text(
            "需要：KAGGLE_USERNAME/KAGGLE_KEY；可选私有数据集 musetalk-min（MuseTalk + 权重 + 5s wav）。"
            "`kaggle kernels push -p .`，完成后 `kaggle kernels output <owner>/hevi-musetalk-probe -p output`。"
            "一次作业有超时上限，不挂机、不挖矿。\n",
            encoding="utf-8",
        )
        return out
