from hevi.creative.shotlang.schemas import ShotLangSpec, ContinuityCard
from hevi.creative.shotlang.continuity import validate_continuity
from hevi.creative.shotlang.qa_report import ShotLangQAReporter

def test_shotlang_schema_and_continuity():
    card = ContinuityCard(
        project_id="greenbook_chicken_01",
        characters=["Tony", "Don Shirley"],
        props=["Fried chicken", "Paper cup"],
        seating_and_direction="Tony front left, Shirley back right",
        axis_rule="180-degree axis respected"
    )
    
    shot = ShotLangSpec(
        shot_id="shot_01_hand_out",
        task="托尼向后排递炸鸡，交代动作方向",
        framing="中景 (Medium Shot - 腰部以上，手与炸鸡入画)",
        camera_position_and_angle="过肩镜头 (Over-the-shoulder from back seat)",
        composition_and_negative_space="留出右侧空间给递出的炸鸡",
        focus_and_depth="前排托尼手臂清晰，背景车内微虚",
        lighting="柔光侧射，阴影过渡柔和",
        camera_movement="相对车内固定 (Static relative to interior)",
        start_state="托尼手中拿大块炸鸡，正向后递出",
        end_state="炸鸡递到画格中心，等待接住",
        continuity_rules=card,
        acceptance_criteria="第一遍看懂谁在递，第二遍手部动作连贯"
    )
    
    res = validate_continuity(shot, card)
    assert res.valid

def test_shotlang_qa_reporter():
    card = ContinuityCard(project_id="greenbook_chicken_01")
    shots = [
        ShotLangSpec(
            shot_id=f"shot_0{i}",
            task=f"Task {i}",
            framing="中景",
            camera_position_and_angle="平视",
            composition_and_negative_space="留白正常",
            focus_and_depth="主体清晰",
            lighting="自然光",
            camera_movement="固定",
            start_state="开始",
            end_state="结束",
            continuity_rules=card
        ) for i in range(1, 4)
    ]
    
    reporter = ShotLangQAReporter()
    report = reporter.evaluate_shots(shots)
    assert report["passed"] is True
    assert report["total_shots"] == 3
