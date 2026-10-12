"""CER（字错率）计算：编辑距离 / 参考字数。用于评估 TTS→STT 往返质量。"""

from __future__ import annotations


def _edit_distance(a: str, b: str) -> int:
    la, lb = len(a), len(b)
    dp = list(range(lb + 1))
    for i in range(1, la + 1):
        prev = dp[0]
        dp[0] = i
        for j in range(1, lb + 1):
            tmp = dp[j]
            cost = 0 if a[i - 1] == b[j - 1] else 1
            dp[j] = min(dp[j] + 1, dp[j - 1] + 1, prev + cost)
            prev = tmp
    return dp[lb]


def cer(reference: str, hypothesis: str) -> float:
    """字错率 = 编辑距离(reference, hypothesis) / len(reference)。"""
    ref = reference.strip()
    if not ref:
        return 0.0 if not hypothesis.strip() else 1.0
    return _edit_distance(ref, hypothesis.strip()) / len(ref)
