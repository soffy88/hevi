"""N0 双 agent（撰稿 W / 审核 R）——HEVI-N0-DUALAGENT-SPEC-001。

稿子由 LLM 写(W)、由确定性代码审(R-hard)、由顾问闸裁——不可欺裁判的 N0 落地。
R-hard(rhard.py) 禁用任何模型；W(writer.py) 用 LLM，输入之外零事实来源。
"""
