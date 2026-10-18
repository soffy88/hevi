# STICKMAN FIX1
磁盘已恢复(>20G)。继续上一轮被磁盘熔断中断的任务：读 STICKMAN_TASK.md 与 audit/stickman/REPORT.md、DISK_FULL_NOTE.md。
补齐：生成真实 ≥60 秒本地火柴人 mp4（SVG 渲染，非 lavfi 纯色，ffprobe 验证），放 audit/stickman/ 作为证明；Flow 包导出+导入拼接测试；台本 n-gram 重合检测；提案批准闸测试；跑全量回归确认无新增失败。
完成后 git commit，删除 .tmp 中间帧，REPORT.md 末行写 STICK-FIX1-FINAL DONE 或 BLOCKED <原因>。df /data<5G 则停止。不 push 不合并。
