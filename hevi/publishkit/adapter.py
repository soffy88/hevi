import os
import json
from pathlib import Path
from typing import Any, Dict

from hevi.layer4_legacy.publishkit.omodul_impl.publish import build_publish_bundle

def generate_publish_bundle(video_path: Path, script_path: Path, output_dir: Path, config: Dict[str, Any] = None) -> Dict[str, Any]:
    """生成发布产物包。"""
    config = config or {}
    return build_publish_bundle(
        video_path=video_path,
        script_path=script_path,
        output_dir=output_dir,
        config=config
    )
