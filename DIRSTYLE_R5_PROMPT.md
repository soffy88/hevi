# DIRSTYLE 第5轮返工
读 DIRSTYLE_FIX_R5.md，逐条修复并达到其中全部机器验收标准。F2 已失败 5 次：旁白分段必须由确定性代码严格按 。？！ 切句（不准让 LLM 切句或改写原句），每段首尾必须落在原文句末标点边界；sentences_are_not_split 测试必须能真实抓到断句（加反例测试证明它会 fail）。修 E2E 文件名不一致使其从干净副本可跑通；删任一产物测试必须 fail；reframe 测试连跑 5 次全过。所有 python 设 PYTHONPATH=$(pwd)。只改本 worktree，不删 worktree 外任何文件，不清理磁盘（/data 剩余<5G 写 DISK_FULL_NOTE.md 并停止），不 push。完成后在 DIRSTYLE_DONE.md 末尾写证据，最后一行写 DONE FIX-R5 并 commit。
