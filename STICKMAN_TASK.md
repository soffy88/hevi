# 火柴人解说片 + Flow 积分通道（worker brief）
上游：https://github.com/kaomei/stickman-video-director（MIT）。可引入其画风库/结构规则/提示词模板，放 third_party/stickman_director/ 并保留 LICENSE 与 NOTICE；只引入有价值部分。
另一个工人正在 feat/explainer-flow 做解说流水线（hevi/explainer 相关）：你不要改那些文件，新代码放 hevi/stickman/ 与独立路由，通过接口复用即可。
要做：
1. stickman.topic_scout：输入对标频道数据（CSV/手填）按“少发高爆”规则打分排序（不联网也能跑）；能力注册。
2. stickman.structure_clone：五段骨架（悬念追问/常识铺垫/反转/揭秘/互动收尾）按参考字幕秒数比例生成新题材台本，含事实核查清单，禁止复制参考原句（加 n-gram 重合度检测测试）；本地模型或规则，不调付费 API。
3. stickman.proposal：导演提案（钩子、色调、分镜表、旁白、BGM 风格），状态机 draft→approved，未批准不得出提示词/出片；画幅、画风只能在提案阶段改。
4. 两条出片路线：
   a) 本地路线 stickman.render_local：SVG/PIL 程序化火柴人（白底黑线圆头、彩色故事风两套，角色 IP 一致性锁定：同一角色参数固定），本地 TTS + 双语字幕 + 微缩放转场 + 音效，ffmpeg 出 mp4，CPU-only。
   b) Flow 路线 stickman.flow_pack：按分镜导出 Flow 任务包（每条 ≤10 秒提示词，带画风锁定段、模型 Omni Flash、720P、顺序号、预估积分 15/条），JSON+TXT；并提供导入接口 stickman.flow_import：接收人工/外部代理下载回来的 Flow mp4（按顺序号），自动校验时长、拼接、加本地双语字幕和转场，出成片。另加积分台账：月度 1000 + 每日 50 的余额估算与消耗记录，接近用完时提示。Hevi 服务器绝不自动登录谷歌或调用 Flow/Gemini API。
5. 端到端：一个原创题材→台本→提案批准→本地路线 ≥60 秒 mp4（ffprobe）；Flow 路线用 6 段本地生成的 10 秒测试片模拟导入，验证拼接成片时长正确（只做测试夹具，报告中注明非 Flow 真片）。
测试：真实测试，全量回归相对基线无新增失败。CPU-only，不 push/合并/部署，不删 worktree 外文件，worktree 内中间产物及时清理；/data<5G 立即停。
报告 audit/stickman/REPORT.md，末行 `STICK-FINAL DONE <commit>` 或 `STICK-FINAL BLOCKED <原因>` 并 commit。
