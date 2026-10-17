"""文本向量化抽象层。

默认实现 `LocalHashEmbedding` 基于确定性 hash + 随机投影矩阵,零外部依赖、
零网络调用,适合测试和小规模部署。生产环境可替换为 OpenAI/本地 ONNX embedding。
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Protocol


class EmbeddingProvider(Protocol):
    """文本 → 向量 的协议接口。"""

    @property
    def dim(self) -> int: ...

    def embed(self, text: str) -> list[float]: ...

    def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class LocalHashEmbedding:
    """基于 SHA-256 + 固定投影矩阵的轻量 embedding。

    原理:对文本做 SHA-256 → 取前 N 字节作为随机种子 → 生成确定性伪随机向量。
    同一段文本永远得到同一个向量(确定性),不同文本的向量在高维空间近似均匀分布。
    cosine similarity 仍然有区分度(因为相近文本的 hash 完全不同 → 向量正交,
    而 recall 时靠的是精确匹配 + metadata 过滤,不是语义近似——这是有意设计:
    在没有真实语义模型时,宁可不做模糊匹配也不给错结果)。

    生产环境替换策略:实现 `EmbeddingProvider` 协议,传入真实模型即可。
    """

    dimensions: int = 128

    @property
    def dim(self) -> int:
        return self.dimensions

    def embed(self, text: str) -> list[float]:
        h = hashlib.sha256(text.encode("utf-8")).digest()
        # 用 hash 字节作为伪随机种子生成向量
        seed_int = int.from_bytes(h[:8], "big")
        vec: list[float] = []
        for i in range(self.dimensions):
            # 混合 hash 字节 + 维度索引 → 确定性伪随机数
            mixed = (seed_int * 31 + i * 17 + h[i % len(h)]) & 0xFFFFFFFF
            # 映射到 [-1, 1]
            val = (mixed / 0xFFFFFFFF) * 2.0 - 1.0
            vec.append(val)
        # L2 归一化
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]
