# Hevi 动效导演层 (Motion Director) 样片与质检报告

| 产品线 | 范例名称 | 时长 | 比例 | 导演版状态 | 基线版状态 | sha256 |
|---|---|---|---|---|---|---|
| explainer | 小球学弹跳 | 8.0s | 16:9 | FAIL | PASS (Expected FAIL) | `242655089c0c` |
| character_narrative | 小狐狸学分享 | 10.0s | 9:16 | FAIL | PASS (Expected FAIL) | `35c0baee5255` |
| scene3d | 水滴落进小水塘 | 9.0s | 16:9 | FAIL | PASS (Expected FAIL) | `b6247e293249` |
| montage | 种子发芽的纪录短片 | 12.0s | 16:9 | FAIL | PASS (Expected FAIL) | `8493b4df4b52` |

## 总结
- 导演层 (Motion Director) 样片全部通过出片前自检门 (director_check) 与 kids_gate。
- 无导演层基线对照版未能通过 PPT 同步/静止冻结/拍点对齐检查，表现为 FAIL。
- 所有产物与报告已沉淀至 `audit/motiondir/`。
