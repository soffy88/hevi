# 小雅人设微调（Unsloth · Colab T4）

- 数据：Qwen3-14B（4bit）老师模型，155 条手写种子弹幕 × 9 类 + 每类扩写 30 条 → 过滤后 663 条（Drive: xiaoya_ft/xiaoya_sft.jsonl）。
- 学生：unsloth/Qwen3-4B-Instruct-2507，LoRA r16，2 epoch，train_on_responses_only；导出 Q4_K_M GGUF（2.5 GB）→ /data/soffy/models/xiaoya，ollama 名 `xiaoya-qwen3-4b`。
- ollama 模型目录已迁到 /data/soffy/ollama/models（~/.ollama/models 软链；旧副本 ~/.ollama/models.old 待确认后删，根分区 100%）。
- 留出 25 条弹幕评测（eval_*.json / stream_*.json）：

| 模型 | 违规率(英文/括号/表情) | 平均字数 | 首句延迟 |
|---|---|---|---|
| llama3.2:3b | 52% | 58.8 | 首 token 5.0 s |
| xiaoya-qwen3-4b + clean_text | 0% | 27.2 | 首句 1.9 s |

- 已知问题：模型开头会吐 `<tool_call>` 一类特殊标记（训练模板里的空 think 段导致），由 llm_ollama.clean_text 剔除；25 条里 1 条空回复、1 条夹日文假名。下一版训练去掉 think 前缀、加“没卖货/不报价”样本。
