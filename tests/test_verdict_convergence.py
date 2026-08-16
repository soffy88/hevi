"""Phase D 内化测试: convergence 收敛循环(来源 dramaclaw convergence_log)。"""

from __future__ import annotations

from hevi.verdict.convergence import (
    RESIDUAL_TARGET,
    ConvergenceLog,
    trend,
)


def test_round_numbering_auto_increments():
    log = ConvergenceLog()
    r1 = log.add_round(episode_num=1, phase="generation", residual_count=5, fixed_count=2)
    r2 = log.add_round(episode_num=1, phase="generation", residual_count=2, fixed_count=3)
    assert r1.round_num == 1
    assert r2.round_num == 2
    # 不同 phase 独立编号
    r3 = log.add_round(episode_num=1, phase="verdict", residual_count=1, fixed_count=0)
    assert r3.round_num == 1


def test_trend_stable_and_converging():
    log = ConvergenceLog()
    log.add_round(episode_num=1, phase="generation", residual_count=10, fixed_count=1)
    log.add_round(episode_num=1, phase="generation", residual_count=4, fixed_count=3)
    t = trend(log, episode_num=1, phase="generation")
    assert t["status"] == "converging"
    log.add_round(episode_num=1, phase="generation", residual_count=0, fixed_count=4)
    t = trend(log, episode_num=1, phase="generation")
    assert t["status"] == "stable"
    assert t["latest_residual"] < RESIDUAL_TARGET


def test_trend_diverging():
    log = ConvergenceLog()
    log.add_round(episode_num=2, phase="generation", residual_count=1, fixed_count=0)
    log.add_round(episode_num=2, phase="generation", residual_count=3, fixed_count=0)
    log.add_round(episode_num=2, phase="generation", residual_count=6, fixed_count=0)
    t = trend(log, episode_num=2, phase="generation")
    assert t["status"] == "diverging"
    assert "降级交付" in t["suggestion"]


def test_trend_no_data():
    assert trend(ConvergenceLog())["status"] == "no_data"


def test_convergence_roundtrip_json(tmp_path):
    log = ConvergenceLog()
    log.add_round(
        episode_num=1,
        phase="generation",
        residual_count=5,
        fixed_count=1,
        new_failures=["bad_hands"],
    )
    p = tmp_path / "conv.json"
    log.save(p)
    loaded = ConvergenceLog.load(p)
    assert len(loaded.rounds()) == 1
    assert loaded.rounds()[0].new_failures == ["bad_hands"]
