import asyncio
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hevi.artmotion.adapter import render_storyboard_artmotion


async def main():
    out_dir = Path("output/artmotion_e2e")
    out_dir.mkdir(parents=True, exist_ok=True)

    tasks = [
        # Task 0: 16:9 + 3b1b + 25_ghibli (吉卜力风 + 深度学习自注意力机制)
        {
            "id": "task_0",
            "desc": "16:9 + 3b1b + 25_ghibli (自注意力机制与 Softmax 归一化)",
            "grammar": "t1_3b1b",
            "style": "25_ghibli",
            "aspect": "16:9",
            "topic": "自注意力机制与归一化",
            "segments": [
                {
                    "id": "t0_s1",
                    "sceneType": "hook",
                    "narration": "在现代大语言模型中，自注意力机制是捕捉长距离语义依赖的核心架构。",
                    "props": {
                        "cues": [
                            {"kind": "equation", "data": {"tokens": [{"s": "Q"}, {"s": "K^T"}, {"s": "/\\sqrt{d_k}"}]}},
                        ],
                    },
                },
                {
                    "id": "t0_s2",
                    "sceneType": "definition",
                    "narration": "输入向量经过线性投影得到查询向量、键向量与值向量三组矩阵。",
                    "props": {
                        "cues": [
                            {"kind": "line", "data": {"values": [1.2, 2.5, 4.2, 6.8, 8.5], "color": "BLUE_C"}},
                            {"kind": "point"},
                        ],
                    },
                },
                {
                    "id": "t0_s3",
                    "sceneType": "method",
                    "narration": "通过计算查询与键的点积，衡量不同标记之间的关联程度。",
                    "props": {
                        "cues": [
                            {"kind": "equation", "data": {"tokens": [{"s": "\\text{Softmax}"}, {"s": "(QK^T)"}, {"s": "V"}]}},
                        ],
                    },
                },
                {
                    "id": "t0_s4",
                    "sceneType": "cards",
                    "narration": "除以维度的平方根进行数值缩放，防止梯度消失并维持数值稳定。",
                    "props": {
                        "cues": [
                            {"kind": "line", "data": {"values": [9.0, 7.2, 5.1, 3.2, 1.6], "color": "TEAL_C"}},
                        ],
                    },
                },
                {
                    "id": "t0_s5",
                    "sceneType": "outro",
                    "narration": "最后利用归一化函数计算注意力权重，并对值向量加权聚合生成最终表征。",
                    "props": {
                        "cues": [
                            {"kind": "highlight", "data": {"target": "equation"}},
                        ],
                    },
                },
            ],
        },

        # Task 1: 9:16 + kinetic_type + 17_ink (水墨风 + 传统写意美学)
        {
            "id": "task_1",
            "desc": "9:16 + kinetic_type + 17_ink (中国传统水墨写意美学与留白艺术)",
            "grammar": "y5_kinetic_type",
            "style": "17_ink",
            "aspect": "9:16",
            "topic": "水墨写意与留白美学",
            "segments": [
                {
                    "id": "t1_s1",
                    "sceneType": "hook",
                    "narration": "中国传统水墨画讲究以墨代色，墨分五色，浓淡干湿尽在一笔之间。",
                    "props": {
                        "cues": [
                            {"kind": "point", "data": {"label": "水墨意境", "key": "墨分五色"}},
                        ],
                    },
                },
                {
                    "id": "t1_s2",
                    "sceneType": "definition",
                    "narration": "水墨画的核心意境在于留白，计白当黑，无画处皆成妙境。",
                    "props": {
                        "cues": [
                            {"kind": "number", "data": {"value": 5, "suffix": " 色韵"}},
                        ],
                    },
                },
                {
                    "id": "t1_s3",
                    "sceneType": "cards",
                    "narration": "画师落笔如行云流水，气韵生动，不求形似而求神采流转。",
                    "props": {
                        "cues": [
                            {"kind": "point", "data": {"label": "留白美学", "key": "计白当黑"}},
                        ],
                    },
                },
                {
                    "id": "t1_s4",
                    "sceneType": "reason",
                    "narration": "枯笔飞白勾勒群山苍茫，宿墨晕染展现烟雨浩渺之深远。",
                    "props": {
                        "cues": [
                            {"kind": "highlight", "data": {"word": "气韵生动"}},
                        ],
                    },
                },
                {
                    "id": "t1_s5",
                    "sceneType": "outro",
                    "narration": "虚实相生之间，展现出东方美学独有的沉静与天地苍茫。",
                    "props": {
                        "cues": [
                            {"kind": "point", "data": {"label": "虚实相生", "key": "东方美学"}},
                        ],
                    },
                },
            ],
        },

        # Task 2: 16:9 + finance_chart + 14_8bit (8位像素风 + 全国光伏装机量)
        {
            "id": "task_2",
            "desc": "16:9 + finance_chart + 14_8bit (中国清洁能源光伏累计装机容量 2020-2024)",
            "grammar": "t3_finance_chart",
            "style": "14_8bit",
            "aspect": "16:9",
            "topic": "中国光伏发电装机跃升",
            "segments": [
                {
                    "id": "t2_s1",
                    "sceneType": "hook",
                    "narration": "近年来中国清洁能源产业高速发展，光伏装机规模实现历史性跨越。",
                    "props": {
                        "data": {
                            "title": "全国光伏发电累计装机容量 (2020-2024)",
                            "unit": "吉瓦 (GW)",
                            "source": "国家能源局公开统计公报",
                            "chart": "bar",
                            "decimals": 0,
                            "series": [
                                {"label": "2020年", "value": 253},
                                {"label": "2021年", "value": 306},
                                {"label": "2022年", "value": 392},
                                {"label": "2023年", "value": 609},
                                {"label": "2024年", "value": 887},
                            ],
                            "highlight": {"index": 4, "text": "历史新高", "sub": "887 GW"},
                        },
                        "cues": [
                            {"kind": "bar", "data": {"index": [0, 1]}},
                        ],
                    },
                },
                {
                    "id": "t2_s2",
                    "sceneType": "definition",
                    "narration": "根据国家能源局公开统计公报，全国光伏累计装机容量保持强劲增长。",
                    "props": {
                        "cues": [
                            {"kind": "bar", "data": {"index": 2}},
                        ],
                    },
                },
                {
                    "id": "t2_s3",
                    "sceneType": "cards",
                    "narration": "从二零二零年的二百五十三吉瓦，稳步攀升至二零二二年的三百九十二吉瓦。",
                    "props": {
                        "cues": [
                            {"kind": "bar", "data": {"index": 3}},
                        ],
                    },
                },
                {
                    "id": "t2_s4",
                    "sceneType": "reason",
                    "narration": "二零二四年装机容量突破八百八十吉瓦，年复合增长率突破百分之三十五。",
                    "props": {
                        "cues": [
                            {"kind": "bar", "data": {"index": 4}},
                        ],
                    },
                },
                {
                    "id": "t2_s5",
                    "sceneType": "outro",
                    "narration": "绿色能源供给体系持续壮大，有力支撑我国双碳战略目标的稳步落地。",
                    "props": {
                        "cues": [
                            {"kind": "highlight"},
                        ],
                    },
                },
            ],
        },

        # Task 3: 9:16 + kinetic_type + 17_ink (对照组：输入驱动内容变化，对比 Task 1)
        {
            "id": "task_3_comparison",
            "desc": "9:16 + kinetic_type + 17_ink [对照组] (唐宋诗词中的山水意境与文人风骨)",
            "grammar": "y5_kinetic_type",
            "style": "17_ink",
            "aspect": "9:16",
            "topic": "唐宋文人风骨与千古浩然气",
            "segments": [
                {
                    "id": "t3_s1",
                    "sceneType": "hook",
                    "narration": "千百年来，诗文风骨是中国文人精神世界最深沉的底色。",
                    "props": {
                        "cues": [
                            {"kind": "point", "data": {"label": "盛唐诗仙", "key": "仗剑去国"}},
                        ],
                    },
                },
                {
                    "id": "t3_s2",
                    "sceneType": "definition",
                    "narration": "李白仗剑去国辞亲远游，一曲将进酒道尽豪迈与孤傲。",
                    "props": {
                        "cues": [
                            {"kind": "number", "data": {"value": 1000, "suffix": " 载风骨"}},
                        ],
                    },
                },
                {
                    "id": "t3_s3",
                    "sceneType": "cards",
                    "narration": "苏轼屡遭贬谪黄州定惠院，竹杖芒鞋轻胜马，一蓑烟雨任平生。",
                    "props": {
                        "cues": [
                            {"kind": "point", "data": {"label": "东坡旷达", "key": "一蓑烟雨"}},
                        ],
                    },
                },
                {
                    "id": "t3_s4",
                    "sceneType": "reason",
                    "narration": "辛弃疾夜半挑灯看剑，梦回吹角连营，壮志难酬却气冲斗牛。",
                    "props": {
                        "cues": [
                            {"kind": "highlight", "data": {"word": "浩然正气"}},
                        ],
                    },
                },
                {
                    "id": "t3_s5",
                    "sceneType": "outro",
                    "narration": "文脉千载未曾断绝，浩然正气长存天地之间，照亮后世文心。",
                    "props": {
                        "cues": [
                            {"kind": "point", "data": {"label": "千秋文脉", "key": "长存天地"}},
                        ],
                    },
                },
            ],
        },

        # Task 4 (r6 新增): 9:16 + t1_3b1b + 25_ghibli —— 竖屏吉卜力底纹理 10s 样片，
        # 验收「12_bauhaus/25_ghibli/14_8bit 竖屏是否有同样的黑底问题」。
        {
            "id": "task_4_portrait_ghibli",
            "desc": "9:16 + t1_3b1b + 25_ghibli (竖屏水彩底 10s 样片：验证竖屏纹理无黑底)",
            "grammar": "t1_3b1b",
            "style": "25_ghibli",
            "aspect": "9:16",
            "topic": "注意力机制竖屏样片",
            "short_sample": True,
            "segments": [
                {
                    "id": "t4_s1",
                    "sceneType": "hook",
                    "narration": "自注意力机制让每个词都能看到句子里所有的词。",
                    "props": {
                        "cues": [
                            {"kind": "equation", "data": {"tokens": [{"s": "Q"}, {"s": "K^T"}, {"s": "/\\sqrt{d_k}"}]}},
                        ],
                    },
                },
                {
                    "id": "t4_s2",
                    "sceneType": "definition",
                    "narration": "查询与键做点积，再除以维度的平方根做数值缩放。",
                    "props": {
                        "cues": [
                            {"kind": "line", "data": {"values": [1.0, 2.4, 3.8, 5.1, 6.4], "color": "TEAL_C"}},
                        ],
                    },
                },
            ],
        },
    ]

    results_summary = []
    for item in tasks:
        task_id = item["id"]
        desc = item["desc"]
        print(f"\n=======================================================")
        print(f"Starting {task_id}: {desc}")
        print(f"=======================================================")

        task_out = out_dir / task_id
        task_out.mkdir(parents=True, exist_ok=True)

        storyboard_data = {
            "topic": item["topic"],
            "segments": item["segments"],
        }
        config = {
            "style_id": item["style"],
            "grammar_id": item["grammar"],
            "aspect_ratio": item["aspect"],
            "language": "zh",
        }

        res = await render_storyboard_artmotion(storyboard_data, task_out, config)
        rec_path = task_out / "record.json"
        rec_data = json.loads(rec_path.read_text())
        rec = rec_data["records"][0]

        video_path = rec["video_path"]
        dur = rec["duration_s"]
        gate_light = rec["gate_light"]
        fast_ratio = rec["fast_ratio"]
        sha256 = rec["sha256"]

        # Run ffprobe verification
        probe_cmd = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration:stream=width,height,codec_type",
            "-of", "json", video_path
        ]
        probe_out = subprocess.check_output(probe_cmd)
        probe_json = json.loads(probe_out)
        streams = probe_json.get("streams", [])
        v_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
        a_stream = next((s for s in streams if s.get("codec_type") == "audio"), {})

        w, h = v_stream.get("width"), v_stream.get("height")
        has_audio = bool(a_stream)
        sheet_path = Path(video_path).with_suffix(".sheet.jpg")

        summary_entry = {
            "task_id": task_id,
            "desc": desc,
            "grammar": item["grammar"],
            "style": rec["style_id"],
            "aspect": item["aspect"],
            "duration_s": dur,
            "resolution": f"{w}x{h}",
            "has_audio": has_audio,
            "gate_light": gate_light,
            "fast_ratio": fast_ratio,
            "blank_run_s": rec["blank_run_s"],
            "blue_purple_share": rec["blue_purple_share"],
            "still_ratio": rec["still_ratio"],
            "video_path": video_path,
            "sheet_path": str(sheet_path),
            "sha256": sha256,
        }
        results_summary.append(summary_entry)
        print(f"Task {task_id} Completed: dur={dur:.2f}s, res={w}x{h}, gate={gate_light}, fast_ratio={fast_ratio:.4f}")
        # r6：task_4 是 10s 样片（短于 film_gate 的 20s 短片段档，快动门禁只提示不拦），单独放宽时长断言。
        if item.get("short_sample"):
            assert 6.0 <= dur <= 20.0, f"Short sample duration {dur}s not in [6, 20]!"
            assert gate_light in ("green", "yellow"), f"Gate light {gate_light} is red on short sample!"
        else:
            assert 20.0 <= dur <= 40.0, f"Duration {dur}s not in [20, 40]!"
            assert gate_light == "green", f"Gate light {gate_light} is not green!"
        assert sheet_path.is_file(), f"Contact sheet missing: {sheet_path}"

    print("\n\n" + "=" * 60)
    print("ALL E2E TASKS FINISHED AND VERIFIED SUCCESSFULLY!")
    print("=" * 60)
    print(json.dumps(results_summary, ensure_ascii=False, indent=2))
    (out_dir / "summary.json").write_text(json.dumps(results_summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())

