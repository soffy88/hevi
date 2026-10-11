# OMFOOTAGE 返工（核验未通过）
1. DONE 报告说 output/om_footage_e2e/piper/{portrait,landscape}.mp4 已生成，实际 piper/ 目录里只有 __init__.py、brief.py 等无关代码文件，没有任何 mp4。必须真跑出中文 piper 旁白的 60–90s 纪录片（横竖各一或至少一个），报告里的路径必须存在。
2. music（无旁白）那条 63s 视频：run_manifest 里所有 cue 的 assetUrl 都是同一个文件 stock/archive_American1955.mp4（一部 1955 年老片的片头字卡 "For a better appreciation of our America"），画面里反复出现同一字卡并夹杂纯黑帧，检索词是 "forest landscape aerial view" / "wild animals in nature savanna" 却取到字卡。要求：每个镜头槽按检索词从 Archive.org/NASA/Wikimedia 取不同的、内容真相符的运动片段；去重（同一素材最多用 1-2 次）；黑帧/字卡/片头用 scenedetect+亮度检查剔除；用 CLIP 相似度对检索结果打分并写入 provenance（相似度阈值，低于就换下一个候选）。
3. 任务第 4 项"研究阶段 hevi/research"完全没做（hevi/research 无任何改动）。实现：用免费 LLM 通道或规则模板 + 真实 web 搜索（免 key 的来源如 Wikipedia API / DuckDuckGo html）输出 research_report.json（含引用 URL），注入 screenplay，E2E 里至少一条带它。
4. 检查 CLIP 是否真用上了（/home/soffy/models/open_clip/ 有权重）：Corpus 不可用时必须报错或 record 标 degraded，禁止零向量；E2E record 里写明 CLIP 模式和各镜头得分。
5. 有 .py 被提交到根目录等垃圾的话清理；git status 干净。
6. 重跑 E2E，ffprobe 时长/分辨率/音轨、sha256、每镜头帧间差异、contact sheet 写入 OMFOOTAGE_DONE.md；跑新增测试和 lint（不得多于基线 4 项失败）并 commit。clean-room：不得复制 OpenMontage 代码。禁止 mock/占位兜底/造假。
