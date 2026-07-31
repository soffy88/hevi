"""
管线检查点（对标 ViMax 各 pipeline 的 artifact 存储模式）

支持长管线的断点续跑：
- 每个阶段产出 artifact 文件
- 检查 artifact 存在则跳过，不存在则执行
- 支持 artifact 版本化
- 支持清理过期检查点
"""
import json
import hashlib
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, Optional, List, Callable, TypeVar, Generic
from datetime import datetime


T = TypeVar("T")


@dataclass
class ArtifactMetadata:
    """Artifact 元数据"""
    artifact_id: str
    stage_name: str
    created_at: float
    version: int = 1
    input_hash: str = ""
    output_hash: str = ""
    duration_s: float = 0.0
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ArtifactMetadata":
        return cls(**data)


@dataclass
class StageConfig:
    """阶段配置"""
    stage_name: str
    artifact_dir: Path
    version: int = 1
    skip_if_exists: bool = True
    hash_inputs: bool = True

    def artifact_path(self, artifact_id: str) -> Path:
        """获取 artifact 文件路径"""
        return self.artifact_dir / f"{self.stage_name}_{artifact_id}.json"

    def metadata_path(self, artifact_id: str) -> Path:
        """获取 metadata 文件路径"""
        return self.artifact_dir / f"{self.stage_name}_{artifact_id}.meta.json"


class PipelineCheckpoint:
    """
    管线检查点管理器

    用法:
        checkpoint = PipelineCheckpoint(working_dir)

        # 定义阶段
        stage = checkpoint.stage("extract_characters", version=1)

        # 检查是否存在
        if checkpoint.exists(stage, "scene_01"):
            chars = checkpoint.load(stage, "scene_01")
        else:
            chars = await extract_characters(script)
            checkpoint.save(stage, "scene_01", chars)

        # 或使用 run_if_missing 简化
        chars = await checkpoint.run_if_missing(
            stage, "scene_01",
            lambda: extract_characters(script),
            inputs={"script": script_hash},
        )
    """

    def __init__(self, working_dir: Path):
        self.working_dir = Path(working_dir)
        self.working_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir = self.working_dir / "artifacts"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)

    def stage(
        self,
        stage_name: str,
        version: int = 1,
        skip_if_exists: bool = True,
        hash_inputs: bool = True,
    ) -> StageConfig:
        """创建阶段配置"""
        artifact_dir = self.artifacts_dir / stage_name
        artifact_dir.mkdir(parents=True, exist_ok=True)

        return StageConfig(
            stage_name=stage_name,
            artifact_dir=artifact_dir,
            version=version,
            skip_if_exists=skip_if_exists,
            hash_inputs=hash_inputs,
        )

    def exists(self, stage: StageConfig, artifact_id: str) -> bool:
        """检查 artifact 是否存在"""
        if not stage.skip_if_exists:
            return False
        return stage.artifact_path(artifact_id).exists()

    def load(self, stage: StageConfig, artifact_id: str) -> Optional[Any]:
        """加载 artifact"""
        artifact_path = stage.artifact_path(artifact_id)
        if not artifact_path.exists():
            return None

        with open(artifact_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def load_metadata(self, stage: StageConfig, artifact_id: str) -> Optional[ArtifactMetadata]:
        """加载 artifact 元数据"""
        metadata_path = stage.metadata_path(artifact_id)
        if not metadata_path.exists():
            return None

        with open(metadata_path, 'r', encoding='utf-8') as f:
            return ArtifactMetadata.from_dict(json.load(f))

    def save(
        self,
        stage: StageConfig,
        artifact_id: str,
        data: Any,
        inputs: Optional[Dict[str, Any]] = None,
        duration_s: float = 0.0,
        extra: Optional[Dict[str, Any]] = None,
    ) -> ArtifactMetadata:
        """保存 artifact"""
        start_time = time.time()

        # 计算输入哈希
        input_hash = ""
        if stage.hash_inputs and inputs:
            input_hash = self._hash_dict(inputs)

        # 计算输出哈希
        output_hash = self._hash_dict(data) if stage.hash_inputs else ""

        # 保存 artifact
        artifact_path = stage.artifact_path(artifact_id)
        with open(artifact_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        # 创建元数据
        metadata = ArtifactMetadata(
            artifact_id=artifact_id,
            stage_name=stage.stage_name,
            created_at=time.time(),
            version=stage.version,
            input_hash=input_hash,
            output_hash=output_hash,
            duration_s=duration_s,
            extra=extra or {},
        )

        # 保存元数据
        metadata_path = stage.metadata_path(artifact_id)
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata.to_dict(), f, ensure_ascii=False, indent=2)

        return metadata

    async def run_if_missing(
        self,
        stage: StageConfig,
        artifact_id: str,
        func: Callable[[], Any],
        inputs: Optional[Dict[str, Any]] = None,
        force: bool = False,
    ) -> Any:
        """
        如果 artifact 不存在则执行函数并保存

        Args:
            stage: 阶段配置
            artifact_id: artifact ID
            func: 执行函数（同步或异步）
            inputs: 输入参数（用于哈希）
            force: 强制执行（忽略检查点）

        Returns:
            artifact 数据
        """
        if not force and self.exists(stage, artifact_id):
            # 检查输入哈希是否匹配
            metadata = self.load_metadata(stage, artifact_id)
            if metadata and inputs and stage.hash_inputs:
                current_hash = self._hash_dict(inputs)
                if metadata.input_hash == current_hash:
                    # 输入未变，直接返回
                    return self.load(stage, artifact_id)
                # 输入已变，继续执行（不 return）
            else:
                # 不检查哈希（无 inputs 或 hash_inputs=False），直接返回
                return self.load(stage, artifact_id)

        # 执行函数
        start_time = time.time()
        result = func()

        # 处理异步函数
        import asyncio
        if asyncio.iscoroutine(result):
            result = await result

        duration_s = time.time() - start_time

        # 保存
        self.save(
            stage,
            artifact_id,
            result,
            inputs=inputs,
            duration_s=duration_s,
        )

        return result

    def list_artifacts(self, stage: StageConfig) -> List[ArtifactMetadata]:
        """列出阶段的所有 artifacts"""
        artifacts = []
        for meta_file in stage.artifact_dir.glob("*.meta.json"):
            with open(meta_file, 'r', encoding='utf-8') as f:
                artifacts.append(ArtifactMetadata.from_dict(json.load(f)))
        return artifacts

    def delete_artifact(self, stage: StageConfig, artifact_id: str) -> bool:
        """删除 artifact"""
        artifact_path = stage.artifact_path(artifact_id)
        metadata_path = stage.metadata_path(artifact_id)

        deleted = False
        if artifact_path.exists():
            artifact_path.unlink()
            deleted = True
        if metadata_path.exists():
            metadata_path.unlink()
            deleted = True

        return deleted

    def clean_stage(self, stage: StageConfig, older_than_days: Optional[int] = None) -> int:
        """清理阶段的 artifacts"""
        count = 0
        now = time.time()

        for artifact in self.list_artifacts(stage):
            should_delete = False

            if older_than_days is not None:
                age_days = (now - artifact.created_at) / 86400
                if age_days > older_than_days:
                    should_delete = True

            if should_delete or older_than_days is None:
                self.delete_artifact(stage, artifact.artifact_id)
                count += 1

        return count

    def clean_all(self, older_than_days: Optional[int] = None) -> int:
        """清理所有 stages"""
        count = 0
        for stage_dir in self.artifacts_dir.iterdir():
            if stage_dir.is_dir():
                stage = self.stage(stage_dir.name)
                count += self.clean_stage(stage, older_than_days)
        return count

    def _hash_dict(self, data: Any) -> str:
        """计算数据的哈希"""
        try:
            # 尝试序列化
            serialized = json.dumps(data, sort_keys=True, ensure_ascii=False)
            return hashlib.sha256(serialized.encode('utf-8')).hexdigest()[:16]
        except (TypeError, ValueError):
            # 不可序列化，使用字符串表示
            return hashlib.sha256(str(data).encode('utf-8')).hexdigest()[:16]

    def get_stats(self) -> Dict[str, Any]:
        """获取检查点统计"""
        stats = {
            "total_artifacts": 0,
            "total_size_mb": 0.0,
            "stages": {},
        }

        for stage_dir in self.artifacts_dir.iterdir():
            if not stage_dir.is_dir():
                continue

            stage_name = stage_dir.name
            artifacts = list(stage_dir.glob("*.json"))
            artifacts = [a for a in artifacts if not a.name.endswith(".meta.json")]

            total_size = sum(a.stat().st_size for a in artifacts) / (1024 * 1024)

            stats["stages"][stage_name] = {
                "artifact_count": len(artifacts),
                "size_mb": round(total_size, 2),
            }
            stats["total_artifacts"] += len(artifacts)
            stats["total_size_mb"] += total_size

        stats["total_size_mb"] = round(stats["total_size_mb"], 2)
        return stats


class CheckpointedPipeline:
    """
    带检查点的管线基类

    子类实现 stages() 和 run_stage() 方法。
    """

    def __init__(self, working_dir: Path):
        self.checkpoint = PipelineCheckpoint(working_dir)

    def stages(self) -> List[str]:
        """返回阶段名称列表（子类实现）"""
        raise NotImplementedError

    async def run_stage(
        self,
        stage_name: str,
        artifact_id: str,
        **kwargs,
    ) -> Any:
        """执行单个阶段（子类实现）"""
        raise NotImplementedError

    async def run(self, artifact_id: str, force_from: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """
        执行完整管线

        Args:
            artifact_id: 主 artifact ID
            force_from: 从哪个阶段开始强制执行
            **kwargs: 传递给各阶段的参数

        Returns:
            各阶段的输出
        """
        results = {}
        force = False

        for stage_name in self.stages():
            if force_from and stage_name == force_from:
                force = True

            stage = self.checkpoint.stage(stage_name)
            result = await self.checkpoint.run_if_missing(
                stage,
                artifact_id,
                lambda sn=stage_name: self.run_stage(sn, artifact_id, **kwargs, previous=results),
                force=force,
            )
            results[stage_name] = result

        return results
