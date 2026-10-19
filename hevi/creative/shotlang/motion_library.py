import json
from pathlib import Path

class MotionLibraryBridge:
    """huashu-motion 20种运动语言与节奏单在 hevi 中的桥接实现"""
    def __init__(self):
        self.motions = [
            {"id": "core-focus", "name": "核心聚焦", "desc": "3秒内抓住用户眼球，去除冗余视觉干扰"},
            {"id": "fast-cut", "name": "高频快切", "desc": "多镜头节奏叠加，适合密集产品亮点展示"},
            {"id": "glitch-stream", "name": "故障流光", "desc": "科技感与赛博风格切换过渡"},
            {"id": "number-zoom", "name": "数字放大", "desc": "核心指标与转化率百分比的夸张视觉放大"}
        ]

    def get_motion(self, motion_id: str):
        for m in self.motions:
            if m["id"] == motion_id:
                return m
        return None
