"""提示词模板管理。

对标 Jellyfish 的 Prompt Template Management:
- 统一管理图像/视频/镜头提示词模板
- 按类别分类(image / video / shot / script)
- 模板变量插值({character_name}, {scene_description} 等)
- CRUD + 版本管理

用途:
- 生成镜头提示词时从模板库取,而不是硬编码在各处
- 前端可编辑模板,无需改代码
"""

from hevi.prompts.models import PromptCategory, PromptTemplate
from hevi.prompts.service import PromptTemplateService

__all__ = [
    "PromptCategory",
    "PromptTemplate",
    "PromptTemplateService",
]
