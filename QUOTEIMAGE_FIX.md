# QUOTEIMAGE 第二轮返工（核验未通过）
核验方式：亲自查看 output/quoteimage_e2e/vid_0_script/quote_script.jpg、vid_0_native/01_quote_image.jpg 的画面。问题：
1. script 模式成品是乱的：字幕行互相重叠、叠在上一条字幕之上，"想让复利为你工作"被写成"想让富力为你工作"（ASR 错字，且 script 模式应使用传入脚本原文，而不是 ASR 识别文本），多种字号/描边风格混杂，右侧卡片被裁出画面，头像被切成碎片重复出现。要求：每个 strip 只出现一条字幕、位置固定、无重叠无截断；文本取自 script.json 原文。
2. native 模式：底部有 ~135px 纯黑条（拼接高度算错），右侧头像被切成 4 段重复（可接受为"原生字幕条"拼接，但每条 strip 必须只截取字幕带本身，不是整幅画面的底部切片）。要求：去掉黑条；strip 间距均匀。
3. 质检门不诚实：QUOTEIMAGE_DONE.md 里 subtitle_truncation 对所有成品都是 FAIL，final_contact_sheet 分辨率 FAIL，但 status 仍是 succeeded。要求：任何 gate FAIL → status=failed 并抛错/重试；contact sheet 不参与分辨率 gate；调阈值要有依据，不能为了过而放宽到无意义。
4. 仓库根目录有垃圾文件被提交：blender_e2e_real.py、v2v_e2e_real.py、detect_band.py、patch_produce.py、patch_vendor.py、test_detect.py、test_gate.py、pull_duix.sh（除 patch_*/临时脚本外，若 detect_band 是正式代码就移入 hevi/layer4_legacy/quoteimage/ 下并有测试）。删除或归位，git status 必须干净。
5. tests/test_quoteimage.py 把质检门整个 mock 掉了；至少加一个真实图片 fixture 的 gate 测试（好图 PASS、截断图 FAIL）。
6. 重跑 E2E（talkcraft_e2e 两条成片，各 native+script），亲自看图，把真实 gate 数值、sha256、ffprobe 写入 QUOTEIMAGE_DONE.md，跑 lint（失败项不得多于基线 4 项）并 commit。
禁止 mock/硬编码通过/占位兜底。
