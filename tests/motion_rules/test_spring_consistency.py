"""Consistency test between Python spring.py and JavaScript spring.js across 200 sample points."""

import json
import math
import subprocess
from pathlib import Path
from hevi.motion_rules.spring import SpringConfig, SpringTrack


def test_python_js_spring_consistency_200_points() -> None:
    js_path = Path(__file__).resolve().parents[2] / "hevi" / "motion_rules" / "js" / "spring.js"
    assert js_path.exists(), f"JS spring file not found at {js_path}"

    # Generate 200 sample points across diverse scenarios
    # 4 distinct track scenarios x 50 points each = 200 points
    scenarios = [
        # Scenario 1: Underdamped spring with multiple steps
        {
            "spring": {"omega": 12.0, "zeta": 0.6, "mass": 1.0},
            "initialValue": 0.0,
            "keyframes": [[0.0, 100.0], [0.8, 40.0], [1.6, 120.0]],
            "sampleTimes": [round(0.0 + i * 0.05, 4) for i in range(50)],  # 50 points (0.0s - 2.45s)
        },
        # Scenario 2: Critically damped spring
        {
            "spring": {"omega": 8.0, "zeta": 1.0, "mass": 1.0},
            "initialValue": 50.0,
            "keyframes": [[0.2, 0.0], [1.0, 200.0]],
            "sampleTimes": [round(0.1 + i * 0.06, 4) for i in range(50)],  # 50 points
        },
        # Scenario 3: Overdamped spring with negative targets
        {
            "spring": {"omega": 15.0, "zeta": 1.8, "mass": 1.0},
            "initialValue": 10.0,
            "keyframes": [[0.0, -100.0], [0.5, 50.0], [1.5, -20.0]],
            "sampleTimes": [round(0.0 + i * 0.04, 4) for i in range(50)],  # 50 points
        },
        # Scenario 4: Fast snappy UI spring configured by stiffness & damping
        {
            "spring": {"stiffness": 180.0, "damping": 18.0, "mass": 1.0},
            "initialValue": 0.0,
            "keyframes": [[0.1, 1.0], [0.5, 0.0], [1.0, 0.8]],
            "sampleTimes": [round(0.05 + i * 0.03, 4) for i in range(50)],  # 50 points
        },
    ]

    total_points = 0
    max_error = 0.0

    for sc_idx, sc in enumerate(scenarios):
        # 1. Run JS evaluation
        req_json = json.dumps(sc)
        proc = subprocess.run(
            ["node", str(js_path), "--eval-json"],
            input=req_json,
            text=True,
            capture_output=True,
            check=True,
        )
        js_result = json.loads(proc.stdout)
        js_values = js_result["values"]
        js_velocities = js_result["velocities"]

        # 2. Run Python evaluation
        if "stiffness" in sc["spring"]:
            py_cfg = SpringConfig(
                stiffness=sc["spring"]["stiffness"],
                damping=sc["spring"]["damping"],
                mass=sc["spring"].get("mass", 1.0),
            )
        else:
            py_cfg = SpringConfig(
                omega=sc["spring"]["omega"],
                zeta=sc["spring"]["zeta"],
                mass=sc["spring"].get("mass", 1.0),
            )
        py_track = SpringTrack(
            keyframes=sc["keyframes"],
            spring=py_cfg,
            initial_value=sc["initialValue"],
        )

        sample_times = sc["sampleTimes"]
        assert len(sample_times) == len(js_values) == 50

        for t, js_val, js_vel in zip(sample_times, js_values, js_velocities):
            total_points += 1
            py_val = py_track.value(t)
            py_vel = py_track.velocity(t)

            val_err = abs(py_val - js_val)
            vel_err = abs(py_vel - js_vel)
            if val_err > max_error:
                max_error = val_err

            # Hard requirement: error < 1e-6
            assert val_err < 1e-6, f"Mismatch at t={t} (scenario {sc_idx}): py={py_val}, js={js_val}, diff={val_err}"
            assert vel_err < 1e-6, f"Velocity mismatch at t={t}: py={py_vel}, js={js_vel}, diff={vel_err}"

    assert total_points == 200, f"Expected 200 sample points, got {total_points}"
    print(f"\n[PASS] Verified {total_points} sample points between Python and JS. Max error: {max_error:.2e} (< 1e-6)")
