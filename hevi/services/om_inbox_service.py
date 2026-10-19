import json
from pathlib import Path

class OMInboxService:
    """浏览器内点到即改反向收件箱协议 (对接 huashu-motion 模式)"""
    def __init__(self, inbox_path: str = ".om/inbox.jsonl"):
        self.inbox_path = Path(inbox_path)
        self.inbox_path.parent.mkdir(parents=True, exist_ok=True)

    def record_comment(self, selector: str, timestamp: float, comment: str):
        record = {
            "selector": selector,
            "timestamp": timestamp,
            "comment": comment
        }
        with open(self.inbox_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return {"recorded": True, "record": record}
