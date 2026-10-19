# hevi 集成 huashu-motion 能力实现说明

为打通并补齐 `hevi` 与 `huashu-motion` 的动效和导演能力，我们在 `hevi` 中集成了如下桥接与增强模块：

1. **运动语言与节奏单规范 (`hevi/creative/shotlang/motion_library.py`)**:
   - 引入了 huashu-motion 的 20 种核心运动语言（如核心聚焦、快切、故障流光、数字放大等）及其节奏控制规范。
2. **ABC 记谱与音效对齐桥接 (`hevi/production/huashu_sound_bridge.py`)**:
   - 支持将 ABC 记谱法文本与音效触发事件映射到 hevi 的主音频时钟工作流中。
3. **点到即改收件箱协议 (`hevi/services/om_inbox_service.py`)**:
   - 实现了类似 huashu-motion 的 `.om/inbox.jsonl` 反向评论与收件箱写入服务，便于 Agent 接收前端点击反馈并增量修改动效源码。

---
HUASHU DONE
