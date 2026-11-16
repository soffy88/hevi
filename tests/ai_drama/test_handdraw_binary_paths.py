"""handdraw 产线的 ffmpeg/ffprobe 路径解析回归（S30E）。

部署把 ffmpeg/ffprobe 装在镜像里的 ``/usr/bin``，宿主机上却在
``/home/soffy/.local/bin``。handdraw 早期把后者写死，API 容器里调用直接
``FileNotFoundError``，手绘动画线（动画/手绘动画）整条出不了片。
"""

from __future__ import annotations

import shutil
from pathlib import Path

HOST_ONLY_PREFIX = "/home/soffy/.local/bin"


def test_pipeline_binaries_resolve() -> None:
    from hevi.layer4_legacy.handdraw import pipeline

    for binary in (pipeline.FFMPEG, pipeline.FFPROBE):
        assert shutil.which(binary) or Path(binary).is_file(), binary


def test_pipeline_does_not_hardcode_host_binary_path() -> None:
    """源码里不得再写死宿主机专属路径（容器里不存在）。"""
    from hevi.layer4_legacy.handdraw import pipeline

    source = Path(pipeline.__file__).read_text(encoding="utf-8")
    assert HOST_ONLY_PREFIX not in source


def test_line_module_has_no_host_only_binary() -> None:
    from hevi.layer4_legacy.handdraw import line

    source = Path(line.__file__).read_text(encoding="utf-8")
    assert HOST_ONLY_PREFIX not in source


def test_tmp_dir_fallback_is_writable_temp() -> None:
    """TMPDIR 未设置时不得退回宿主机路径（容器里建不出来）。"""
    from hevi.layer4_legacy.handdraw import pipeline

    source = Path(pipeline.__file__).read_text(encoding="utf-8")
    assert "/data/soffy/projects/hevi-handdraw/.tmp" not in source
