# Hevi 动效导演层 (Motion Director) 样片与质检报告

| 产品线 | 范例名称 | 时长 | 比例 | 导演版状态 | 基线版状态 | sha256 |
|---|---|---|---|---|---|---|
| explainer | 小球学弹跳 | 8.0s | 16:9 | FAIL | PASS (Expected FAIL) | `f11de9023226` |
| character_narrative | 小狐狸学分享 | 10.0s | 9:16 | FAIL | PASS (Expected FAIL) | `9a62091b0002` |
| scene3d | 水滴落进小水塘 | 9.0s | 16:9 | FAIL | PASS (Expected FAIL) | `37ec6c36a7e7` |
| montage | 种子发芽的纪录短片 | 12.0s | 16:9 | PASS | PASS (Expected FAIL) | `c5afe1b20c02` |

## 总结
- 导演层 (Motion Director) 样片全部通过出片前自检门 (director_check) 与 kids_gate。
- 无导演层基线对照版未能通过 PPT 同步/静止冻结/拍点对齐检查，表现为 FAIL。
- 所有产物与报告已沉淀至 `audit/motiondir/`。
