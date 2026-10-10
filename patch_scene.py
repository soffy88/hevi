import re
import sys

with open('hevi/verdict/source_media_review.py', 'r') as f:
    content = f.read()

scene_detect_code = """
def _detect_scenes(path: Path) -> list[dict[str, Any]]:
    try:
        from scenedetect import detect, ContentDetector
        scene_list = detect(str(path), ContentDetector())
        return [{"start_time": s[0].get_seconds(), "end_time": s[1].get_seconds()} for s in scene_list]
    except Exception as exc:
        logger.warning(f"scene detect failed: {exc}")
        return []
"""

content = content.replace("def _probe_video", scene_detect_code + "\ndef _probe_video")

# Insert calling _detect_scenes inside _probe_video
idx = content.find("result[\"technical_probe\"] = {")
if idx != -1:
    content = content[:idx] + "scenes = _detect_scenes(path)\n        " + content[idx:]
    idx2 = content.find("}", idx)
    content = content[:idx2] + ",\n            \"scenes\": scenes" + content[idx2:]

with open('hevi/verdict/source_media_review.py', 'w') as f:
    f.write(content)
