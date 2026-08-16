"""v9.1 防复读记忆 —— 已验收内容的句式指纹存储与检索。

移植自 novel-studio 的"已验收正文防复读记忆"概念: 长连载/多集脚本的
声口漂移与句式重复, 靠把**已验收**(人工审核通过/编辑保存)的文本片段
沉淀成语料, 生成新脚本前检索相似片段并注入 prompt, 提示模型避免重复。

实现(轻量、零外部依赖):
  * 存储: data/anti_repeat/<key>.json —— 每个系列/来源一个文件(与任务库同目录);
  * 指纹: 中文按标点切句, 归一化后取字符 bigram 集合;
  * 检索: query 句子与已存句子 Jaccard 相似度, 返回 top-k 相似片段;
  * 线程安全: 模块级锁(API 多请求并发写)。
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from pathlib import Path

_SENTENCE_SPLIT = re.compile(r"[。！？!?;；\n]+")
_DEFAULT_ROOT = Path("data/anti_repeat")
_lock = threading.Lock()


class AntiRepeatMemory:
    """一个系列/来源的防复读记忆(文件 JSON: {sentences: [归一化句子]})。"""

    def __init__(self, key: str, root: Path = _DEFAULT_ROOT) -> None:
        safe = re.sub(r"[^\w\u4e00-\u9fff.-]", "_", key).strip("_") or "default"
        self._path = root / f"{safe}.json"
        self._sentences: list[str] = []
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._sentences = list(data.get("sentences") or [])
        except (OSError, ValueError):
            self._sentences = []

    def remember(self, text: str) -> int:
        """吸收一段已验收文本(按句切分 + 归一化去重), 返回新增句数。"""
        if not text.strip():
            return 0
        new_sentences = [s for s in _split_sentences(text) if s]
        with _lock:
            known = set(self._sentences)
            added = 0
            for s in new_sentences:
                norm = _normalize(s)
                if norm and norm not in known:
                    known.add(norm)
                    self._sentences.append(norm)
                    added += 1
            if added:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                self._path.write_text(
                    json.dumps({"sentences": self._sentences}, ensure_ascii=False, indent=1),
                    encoding="utf-8",
                )
        return added

    def similar_to(self, text: str, top_k: int = 3, threshold: float = 0.35) -> list[str]:
        """检索与 text 相似的已验收句子, 返回原始片段。

        相似度 = max(Jaccard, query→stored 覆盖率):
          * Jaccard 抓"同一句式"(人名/动词重叠);
          * 覆盖率抓"query 大部分字面出现在已写内容里"(近字面重复)。
        """
        if not self._sentences or not text.strip():
            return []
        query_sentences = _split_sentences(text)
        if not query_sentences:
            return []
        query_grams = set().union(
            *(_bigrams(_normalize(q)) for q in query_sentences[:40])
        )
        scored: list[tuple[float, str]] = []
        for stored in self._sentences:
            grams = _bigrams(stored)
            if not grams:
                continue
            inter = len(query_grams & grams)
            union = len(query_grams | grams)
            jaccard = inter / union if union else 0.0
            coverage = inter / len(query_grams) if query_grams else 0.0
            score = max(jaccard, coverage)
            if score >= threshold:
                scored.append((score, stored))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [s for _, s in scored[:top_k]]

    @property
    def size(self) -> int:
        return len(self._sentences)

    def clear(self) -> None:
        with _lock:
            self._sentences = []
            self._path.unlink(missing_ok=True)


def _split_sentences(text: str) -> list[str]:
    parts = _SENTENCE_SPLIT.split(text)
    return [p.strip() for p in parts if p.strip()]


def _normalize(sentence: str) -> str:
    """去空白/标点, 保留汉字/字母/数字(便于 bigram 指纹比较)。"""
    return re.sub(r"[\s，。！？、；：""''（）【】《》,.!?;:\"'()\[\]{}]", "", sentence)


def _bigrams(s: str) -> set[str]:
    if len(s) < 2:
        return {s} if s else set()
    return {s[i : i + 2] for i in range(len(s) - 1)}


def memory_fingerprint(sentences: list[str]) -> str:
    """记忆指纹(SHA-256): 判断记忆是否变化(审计/缓存失效用)。"""
    return hashlib.sha256("\n".join(sentences).encode("utf-8")).hexdigest()[:16]


__all__ = ["AntiRepeatMemory", "memory_fingerprint"]
