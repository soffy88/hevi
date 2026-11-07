# REPO_3O_IMPL

| 元素名 | 类型 | 候选 | worktree 内路径 | pytest 实际输出摘要 | commit hash |
|---|---|---|---|---|---|
| KokoroRuntime | obase | kokoro | obase-repo3o/obase/kokoro_runtime.py | 3 passed, 0 failed | e2b97bd6d07f2c8112dc640181b7d69204c22588 |
| synthesize_speech_chunk | oprim | kokoro | oprim-repo3o/oprim/_synthesize_speech_chunk.py | 3 passed, 0 failed | ab5864573134104e5e5be48759276a7c5b822a3e |
| whisper_transcribe | oprim | AI-Youtube-Shorts-Generator | oprim-repo3o/oprim/_whisper_transcribe.py | 2 passed, 0 failed | ab5864573134104e5e5be48759276a7c5b822a3e |
| crop_video_to_portrait | oprim | AI-Youtube-Shorts-Generator | oprim-repo3o/oprim/_crop_video_to_portrait.py | 3 passed, 0 failed | ab5864573134104e5e5be48759276a7c5b822a3e |
| highlight_detection_algorithm | oskill | AI-Youtube-Shorts-Generator | oskill-repo3o/oskill/_highlight_detection_algorithm.py | 3 passed, 0 failed | d214fa39ed7e01d8ee0ba6f96ace0637e0a71cad |
| long_to_short_video_workflow | omodul | AI-Youtube-Shorts-Generator | omodul-repo3o/omodul/long_to_short_video_workflow.py | 2 passed, 0 failed | 7dc633124bc6c9610a4322f148e4f72a45e77f5b |
| query_expansion | oskill | local-deep-research | oskill-repo3o/oskill/_query_expansion.py | 3 passed, 0 failed | d214fa39ed7e01d8ee0ba6f96ace0637e0a71cad |
| search_synthesize_loop | oskill | local-deep-research | oskill-repo3o/oskill/_search_synthesize_loop.py | 2 passed, 0 failed | d214fa39ed7e01d8ee0ba6f96ace0637e0a71cad |
| deep_research_workflow | omodul | local-deep-research | omodul-repo3o/omodul/deep_research_workflow.py | 2 passed, 0 failed | 7dc633124bc6c9610a4322f148e4f72a45e77f5b |
| dialogue_script_generation | oskill | podcastfy | oskill-repo3o/oskill/_dialogue_script_generation.py | 3 passed, 0 failed | d214fa39ed7e01d8ee0ba6f96ace0637e0a71cad |
| multi_speaker_tts_merge | oskill | podcastfy | oskill-repo3o/oskill/_multi_speaker_tts_merge.py | 2 passed, 0 failed | d214fa39ed7e01d8ee0ba6f96ace0637e0a71cad |
| podcast_generation_workflow | omodul | podcastfy | omodul-repo3o/omodul/podcast_generation_workflow.py | 1 passed, 0 failed | 7dc633124bc6c9610a4322f148e4f72a45e77f5b |
| video_subtitle_align | oskill | short-video-factory | oskill-repo3o/oskill/_video_subtitle_align.py | 2 passed, 0 failed | d214fa39ed7e01d8ee0ba6f96ace0637e0a71cad |
| template_scene_compose | oskill | short-video-factory | oskill-repo3o/oskill/_template_scene_compose.py | 2 passed, 0 failed | d214fa39ed7e01d8ee0ba6f96ace0637e0a71cad |
| marketing_video_generation | omodul | short-video-factory | omodul-repo3o/omodul/marketing_video_generation.py | 1 passed, 0 failed | 7dc633124bc6c9610a4322f148e4f72a45e77f5b |
| EmbeddingGemmaClient | obase | DigUp | obase-repo3o/obase/embedding_gemma.py | 2 passed, 0 failed | e2b97bd6d07f2c8112dc640181b7d69204c22588 |
| multimodal_embed | oprim | DigUp | oprim-repo3o/oprim/_multimodal_embed.py | 2 passed, 0 failed | ab5864573134104e5e5be48759276a7c5b822a3e |
| vector_cosine_search | oprim | DigUp | oprim-repo3o/oprim/_vector_cosine_search.py | 3 passed, 0 failed | ab5864573134104e5e5be48759276a7c5b822a3e |
| multimodal_index_pipeline | oskill | DigUp | oskill-repo3o/oskill/_multimodal_index_pipeline.py | 2 passed, 0 failed | d214fa39ed7e01d8ee0ba6f96ace0637e0a71cad |

## 未完成 / 阻塞项
- oservi：未新增元素；复用已有 sequential_composer 引擎，未改动，无 commit。
- oprim 主工作区原有未解决合并冲突（changefeed）未触碰，worktree 独立。
- 重依赖（kokoro/torch、ffmpeg、whisper）未安装，实现采用懒加载 + mock 测试；真实模型推理未验证。
- obase 未单独创建 search API 适配器，复用现有 web_search/http_fetch 能力。
- 未 push、未合并 main。
REPO3O_IMPL DONE
