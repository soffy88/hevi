# PUBLISHKIT 第二轮返工（核验未通过）
上一轮已去掉 mock 且白板确实真渲染了（35.6s 有音轨），但内容是模板占位：
1. 抽帧看到白板上显示的是字面的 "Beat 0 / Beat 1 / Beat 2 / Beat 3" 和 "Your Brand / 一句话说清你的账号给观众什么。"——这是起手模板占位，不是旁白对应的内容。要求：每个 beat 的白板内容取自旁白稿（小标题+要点/简单图形/图标），品牌文字取自输入（没提供就不显示品牌条，不能留默认 "Your Brand"）。
2. 竖版 whiteboard_portrait.mp4 只是 16:9 缩小后上下加糊底，白板内容占画面 1/4 不可读。要求：竖版用 1080x1920 视口重新排版渲染（或按竖版自适应布局），内容充满画面、字号可读。
3. 字幕与白板文字要同步：旁白说到哪个要点，白板就写到哪个要点（用 whisper 逐句时间戳对齐）。
4. scripts/whiteboard_e2e.py 至少用两份不同主题的旁白稿跑，证明内容随输入变化；亲自抽帧确认画面。
5. 仓库根有被提交的垃圾：blender_e2e_real.py、v2v_e2e_real.py、pull_duix.sh，删除；produce.py:46 "Write a dummy script.json" 去掉。
6. 重跑 E2E，ffprobe+sha256+抽帧写入 PUBLISHKIT_DONE.md；跑 lint（不得多于基线 4 项失败）和新增测试，commit。禁止 mock/占位兜底。
