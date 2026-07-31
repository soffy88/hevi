"""Agent Skill 知識層 —— Markdown 技能系統。

對標 OpenMontage 的 3 層知識架構：
Layer 1: tools/tool_registry.py     → "什麼工具存在" (runtime capabilities, status, cost)
Layer 2: skills/                    → "Hevi 如何使用它們" (項目慣例)
Layer 3: .agents/skills/            → "技術如何運作" (通用 API 規則、技能)

Hevi 目前所有智能都在 Python 代碼裡硬編碼，沒有 Markdown skill 層。
本模塊實現 skill 加載、解析和執行系統。

用法:
    from hevi.agent_skills import SkillManager
    sm = SkillManager()
    result = await sm.execute_skill("text-to-speech-guidelines", context={"provider": "edge_tts"})
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Skill:
    """技能定義"""
    id: str
    title: str
    category: str
    content: str
    tags: List[str]
    prerequisites: List[str]
    examples: List[str]
    warnings: List[str]


class SkillManager:
    """技能管理器"""
    
    def __init__(self, skills_dir: Path | None = None):
        self.skills_dir = skills_dir or Path(__file__).parent.parent / ".agents" / "skills"
        self.skills: Dict[str, Skill] = {}
        self._loaded = False
    
    async def load_skills(self) -> None:
        """加載所有技能"""
        if not self.skills_dir.exists():
            logger.warning("Skills directory does not exist: %s", self.skills_dir)
            return
        
        # 搜索所有 .md 文件
        md_files = list(self.skills_dir.rglob("*.md"))
        md_files.extend(list(self.skills_dir.rglob("*.markdown")))
        
        for md_file in md_files:
            try:
                skill = await self._parse_skill(md_file)
                if skill:
                    self.skills[skill.id] = skill
            except Exception as e:
                logger.warning("Failed to parse skill file %s: %s", md_file, e)
        
        self._loaded = True
        logger.info("Loaded %d skills from %s", len(self.skills), self.skills_dir)
    
    async def _parse_skill(self, file_path: Path) -> Skill | None:
        """解析單個技能文件"""
        content = file_path.read_text(encoding='utf-8')
        
        # 提取元數據
        metadata = self._extract_metadata(content)
        
        # 生成技能 ID（基於文件路徑）
        rel_path = file_path.relative_to(self.skills_dir)
        skill_id = str(rel_path).replace('/', '_').replace('\\', '_').replace('.md', '').replace('.markdown', '')
        
        # 提取主要內容（去除元數據部分）
        main_content = self._extract_main_content(content)
        
        # 提取示例
        examples = self._extract_examples(content)
        
        # 提取警告
        warnings = self._extract_warnings(content)
        
        return Skill(
            id=skill_id,
            title=metadata.get('title', file_path.stem),
            category=metadata.get('category', 'general'),
            content=main_content,
            tags=metadata.get('tags', []),
            prerequisites=metadata.get('prerequisites', []),
            examples=examples,
            warnings=warnings
        )
    
    def _extract_metadata(self, content: str) -> Dict[str, Any]:
        """提取 Markdown 元數據（YAML frontmatter 或註釋塊）"""
        import yaml
        
        # 檢查是否有 YAML frontmatter
        if content.startswith('---'):
            try:
                end_marker = content.find('---', 3)
                if end_marker != -1:
                    yaml_content = content[3:end_marker].strip()
                    metadata = yaml.safe_load(yaml_content) or {}
                    return metadata
            except:
                pass
        
        # 檢查是否有註釋塊元數據
        metadata = {}
        lines = content.split('\n')
        for line in lines[:10]:  # 只檢查前 10 行
            if line.strip().startswith('<!--'):
                continue
            if line.strip().startswith('#') or line.strip() == '':
                continue
            # 檢查 key: value 格式
            match = re.match(r'^([a-zA-Z_]+):\s*(.+)$', line.strip())
            if match:
                key, value = match.groups()
                # 解析列表
                if ',' in value:
                    metadata[key] = [item.strip() for item in value.split(',')]
                else:
                    metadata[key] = value
        
        return metadata
    
    def _extract_main_content(self, content: str) -> str:
        """提取主要內容（去除元數據）"""
        # 如果有 YAML frontmatter，跳過它
        if content.startswith('---'):
            end_marker = content.find('---', 3)
            if end_marker != -1:
                content = content[end_marker + 3:]
        
        return content.strip()
    
    def _extract_examples(self, content: str) -> List[str]:
        """提取示例"""
        examples = []
        # 檢查是否有 "Examples:" 或 "Example:" 章節
        example_patterns = [
            r'##\s*Examples?\s*\n((?:(?!\n##\s)[^\n]+\n?)*)',
            r'###\s*Examples?\s*\n((?:(?!\n##|\n###\s)[^\n]+\n?)*)',
            r'(?i)example[:\s]\s*\n((?:(?!\n##|\n###|\n[^\s#\n])[^\n]+\n?)*)'
        ]
        
        for pattern in example_patterns:
            matches = re.findall(pattern, content, re.MULTILINE | re.IGNORECASE)
            examples.extend(matches)
        
        return [ex.strip() for ex in examples if ex.strip()]
    
    def _extract_warnings(self, content: str) -> List[str]:
        """提取警告"""
        warnings = []
        # 檢查 "Warning:", "⚠️", "注意:", "小心:" 等
        warning_patterns = [
            r'Warning:\s*(.+?)(?=\n|$)',
            r'⚠[️]?\s*(.+?)(?=\n|$)', 
            r'注意:\s*(.+?)(?=\n|$)',
            r'小心:\s*(.+?)(?=\n|$)',
            r'(?i)\*\*warning\*\*[:\s]*(.+?)(?=\n|$)'
        ]
        
        for pattern in warning_patterns:
            matches = re.findall(pattern, content, re.MULTILINE | re.IGNORECASE)
            warnings.extend(matches)
        
        return [w.strip() for w in warnings if w.strip()]
    
    async def get_skill(self, skill_id: str) -> Skill | None:
        """獲取特定技能"""
        if not self._loaded:
            await self.load_skills()
        
        return self.skills.get(skill_id)
    
    async def find_skills_by_category(self, category: str) -> List[Skill]:
        """按類別查找技能"""
        if not self._loaded:
            await self.load_skills()
        
        return [skill for skill in self.skills.values() if skill.category == category]
    
    async def find_skills_by_tag(self, tag: str) -> List[Skill]:
        """按標籤查找技能"""
        if not self._loaded:
            await self.load_skills()
        
        return [skill for skill in self.skills.values() if tag in skill.tags]
    
    async def execute_skill(self, skill_id: str, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        """執行技能（根據上下文返回相關指導）"""
        skill = await self.get_skill(skill_id)
        if not skill:
            return {"error": f"Skill not found: {skill_id}"}
        
        # 簡單的上下文替換
        processed_content = skill.content
        if context:
            for key, value in context.items():
                placeholder = f"{{{key}}}"
                processed_content = processed_content.replace(placeholder, str(value))
                # 也嘗試使用下劃線格式
                underscore_key = key.replace('-', '_')
                placeholder_underscore = f"{{{underscore_key}}}"
                processed_content = processed_content.replace(placeholder_underscore, str(value))
        
        return {
            "skill_id": skill.id,
            "title": skill.title,
            "category": skill.category,
            "content": processed_content,
            "tags": skill.tags,
            "prerequisites": skill.prerequisites,
            "examples": skill.examples,
            "warnings": skill.warnings,
            "executed_context": context or {}
        }
    
    async def list_all_skills(self) -> List[Dict[str, str]]:
        """列出所有技能的基本信息"""
        if not self._loaded:
            await self.load_skills()
        
        return [
            {
                "id": skill.id,
                "title": skill.title,
                "category": skill.category,
                "tags": ", ".join(skill.tags)
            }
            for skill in self.skills.values()
        ]
    
    async def search_skills(self, query: str) -> List[Skill]:
        """搜索技能"""
        if not self._loaded:
            await self.load_skills()
        
        query_lower = query.lower()
        results = []
        
        for skill in self.skills.values():
            # 檢查標題、內容、標籤是否包含查詢詞
            if (query_lower in skill.title.lower() or 
                query_lower in skill.content.lower() or 
                any(query_lower in tag.lower() for tag in skill.tags)):
                results.append(skill)
        
        return results


# 預定義的一些常用技能模板
PREDEFINED_SKILLS = {
    "text-to-speech-guidelines": {
        "title": "Text-to-Speech Guidelines",
        "category": "audio",
        "content": """
# Text-to-Speech Provider Selection Guidelines

## When to Use Each Provider

### Edge TTS
- **Best for**: Natural human-like voices in multiple languages
- **Pricing**: Free for personal use, commercial licenses available
- **Quality**: High naturalness, good for narration
- **Limitations**: Limited customization options

### VoiSynth (Voice Cloning)
- **Best for**: Custom voice cloning, consistent character voices
- **Requirements**: Sample audio files for training
- **Quality**: Very high if trained properly
- **Limitations**: Requires initial training, computational resources

## Quality Optimization Tips

1. **Preprocessing Text**
   - Break long sentences with commas
   - Spell out numbers when beneficial
   - Add pauses with punctuation strategically

2. **Voice Selection**
   - Match voice personality to content
   - Consider regional accents for localization
   - Test multiple samples before committing

## Common Pitfalls to Avoid

- Don't use overly expressive voices for technical content
- Avoid very fast speaking rates (>300 wpm) for clarity
- Always review output for unnatural pauses or emphasis
""",
        "tags": ["audio", "tts", "voice", "quality"],
        "prerequisites": ["audio_setup"],
        "examples": [],
        "warnings": ["Ensure compliance with voice licensing terms", "Test on target devices for quality verification"]
    },
    
    "video-generation-guidelines": {
        "title": "Video Generation Guidelines", 
        "category": "video",
        "content": """
# Video Generation Best Practices

## Prompt Engineering for Video

### Structure
1. **Subject**: Clear description of main elements
2. **Action**: What is happening
3. **Environment**: Setting and background  
4. **Style**: Artistic style or realism level
5. **Camera**: Movement and angle (if needed)

### Timing Considerations
- 2-3 seconds: Simple transformation or reveal
- 4-6 seconds: Complex action or scene change
- 7-10 seconds: Detailed sequence or story beat

## Quality Optimization

### High-Quality Results
- Use specific, concrete language
- Include lighting and atmospheric details
- Specify desired motion characteristics
- Mention style references when applicable

### Common Issues and Solutions
- **Blurry output**: Add clarity keywords like "sharp focus", "crystal clear"
- **Jittery motion**: Request "smooth motion", "steady camera"
- **Subject inconsistency**: Emphasize key identifying features
""",
        "tags": ["video", "prompt", "generation", "quality"],
        "prerequisites": ["understand_video_concepts"],
        "examples": [],
        "warnings": ["Monitor costs as video generation can be expensive", "Validate generated content for compliance"]
    },
    
    "style-consistency-check": {
        "title": "Style Consistency Verification",
        "category": "quality",
        "content": """
# Style Consistency Verification Checklist

## Visual Consistency
- [ ] Color palette remains uniform across shots
- [ ] Lighting conditions match between consecutive shots
- [ ] Character designs remain consistent
- [ ] Background elements maintain coherence

## Temporal Consistency  
- [ ] Scene transitions flow naturally
- [ ] Character positions/orientations are logically consistent
- [ ] Time progression makes sense
- [ ] Cause-effect relationships are maintained

## Audio Consistency
- [ ] Background music levels are balanced
- [ ] Dialogue levels match throughout
- [ ] Sound effects are appropriately mixed
- [ ] Audio quality is consistent

## Common Inconsistencies to Watch For
1. **Jump Cuts**: Abrupt changes in character position/orientation
2. **Color Drift**: Gradual shift in color temperature or saturation
3. **Temporal Displacement**: Events happening out of logical order
4. **Audio Sync**: Dialogue/voiceover not matching mouth movements
""",
        "tags": ["quality", "consistency", "review", "verification"],
        "prerequisites": ["review_process"],
        "examples": [],
        "warnings": ["Verify consistency across entire sequence, not just individual clips", "Pay attention to subtle changes that accumulate over time"]
    }
}


async def get_predefined_skill(skill_id: str) -> Skill | None:
    """獲取預定義技能"""
    if skill_id in PREDEFINED_SKILLS:
        data = PREDEFINED_SKILLS[skill_id]
        return Skill(
            id=skill_id,
            title=data["title"],
            category=data["category"], 
            content=data["content"],
            tags=data["tags"],
            prerequisites=data["prerequisites"],
            examples=data["examples"],
            warnings=data["warnings"]
        )
    return None


# 全局技能管理器實例
_global_skill_manager: SkillManager | None = None


async def get_skill_manager() -> SkillManager:
    """獲取全局技能管理器"""
    global _global_skill_manager
    if _global_skill_manager is None:
        _global_skill_manager = SkillManager()
        await _global_skill_manager.load_skills()
    return _global_skill_manager