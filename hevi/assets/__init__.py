"""扩展资产实体管理 —— 道具(Prop)和服装(Costume)。

对标 Jellyfish 的资产实体模型:
- 角色(Character) → Hevi 已有 Subject
- 场景(Scene) → Hevi 已有 scene_ref_paths
- 道具(Prop) → 新增
- 服装(Costume) → 新增

支持:
- 道具/服装的 CRUD 管理
- 跨镜头关联复用
- 名称唯一性检查(鼓励复用已有资产)
- 资产图像管理
"""

from hevi.assets.models import Costume, Prop
from hevi.assets.service import AssetService

__all__ = ["AssetService", "Costume", "Prop"]
