"""hevi agent skills —— 3O 内化 Round 3(HyperFrames 验证的分发形态)。

来源: heygen-com/hyperframes 的 19-skill + router 分发 + claude-video/shotcraft 的
SKILL.md 形态。hevi 以三支核心 skill 起步(router 职责由 `/hevi` 概览承担):
  - hevi-watch   摄入侧:URL/本地 → 帧+转写+联络表(hevi.ingest)
  - hevi-media   media-use:一个 resolve 动词 → 冻结文件+台账(hevi.sourcing.media_use)
  - hevi-promo   产品宣传片:配方卡+节拍+声音设计 → 制作计划(hevi.assembly/motion)
  - hevi-studio  制片厂:列产线/填槽/签发工单(hevi.studio)
  - hevi-hyperframes 第二渲染运行时
  - hevi-daily   解说/历史现场日更

SKILL.md 与 scripts 同目录自包含;安装器 scripts/install_hevi_skills.py 把它们
symlink 进 ~/.claude/skills 等宿主目录(与 claude-video 的 npx skills 生态同构)。
"""
