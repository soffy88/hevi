# Hevi 后端 API 能力清单

> 由 `scripts/export_api_inventory.py` 从 FastAPI OpenAPI 自动生成；不要手工编辑。
> `⚠️ 兼容` 表示仍可调用但新客户端不应使用的弃用入口。

## audio_library

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/audio` | Search Audio |
| POST | `/api/audio` | Create Audio Asset |
| DELETE | `/api/audio/{asset_id}` | Delete Audio Asset |
| GET | `/api/audio/{asset_id}` | Get Audio Asset |

## auth

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/auth/login` | Login |
| GET | `/api/auth/me` | Get Me |
| POST | `/api/auth/oauth/google` | Google Oauth |
| POST | `/api/auth/register` | Register |

## backlot

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/backlot/runs/{run_id}/events` | Get Run Events |
| POST | `/api/backlot/runs/{run_id}/events` | Emit Run Event |
| GET | `/api/backlot/runs/{run_id}/status` | Get Run Status |

## canvas

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/canvas` | List Graphs |
| POST | `/api/canvas` | Save Graph |
| GET | `/api/canvas/graphs` | ⚠️ 兼容 · List Graphs Legacy |
| POST | `/api/canvas/graphs` | ⚠️ 兼容 · Save Graph Legacy |
| DELETE | `/api/canvas/graphs/{graph_id}` | ⚠️ 兼容 · Delete Graph Legacy |
| GET | `/api/canvas/graphs/{graph_id}` | ⚠️ 兼容 · Get Graph Legacy |
| PATCH | `/api/canvas/graphs/{graph_id}` | ⚠️ 兼容 · Update Graph Legacy |
| POST | `/api/canvas/graphs/{graph_id}/execute` | ⚠️ 兼容 · Execute Graph Legacy |
| POST | `/api/canvas/reference-image` | Upload Canvas Reference Image |
| DELETE | `/api/canvas/{graph_id}` | Delete Graph |
| GET | `/api/canvas/{graph_id}` | Get Graph |
| PATCH | `/api/canvas/{graph_id}` | Update Graph |
| POST | `/api/canvas/{graph_id}/execute` | Execute Graph |

## cinematic

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/cinematic/animate` | Animate |
| GET | `/api/cinematic/tasks/{task_id}` | Get Animation Task |
| GET | `/api/cinematic/tasks/{task_id}/video` | Get Animation Video |

## creative

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/creative/capabilities` | List Capabilities |
| POST | `/api/creative/element-edit` | Edit Video Element |
| POST | `/api/creative/multi-angle` | Gen Multi Angle |
| POST | `/api/creative/story-predict` | Predict Story |
| POST | `/api/creative/storyboard` | Gen Storyboard |
| POST | `/api/creative/three-view` | Gen Three View |
| POST | `/api/creative/transition` | Make Transition |
| POST | `/api/creative/workflow/character-consistency` | Run Character Consistency |
| POST | `/api/creative/workflow/comic-to-animation` | Run Comic To Animation |
| POST | `/api/creative/workflow/storyboard` | Run Storyboard Workflow |
| POST | `/api/creative/xia/chat` | Xia Chat |

## credits

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/credits/balance` | Get Balance |
| POST | `/api/credits/estimate` | Estimate Credits |
| POST | `/api/credits/topup` | Manual Topup |
| GET | `/api/credits/transactions` | List Transactions |

## dashboard

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/dashboard/tasks` | List Tasks |
| GET | `/api/dashboard/tasks/{task_id}` | Get Task |
| GET | `/api/dashboard/tasks/{task_id}/output` | Serve Task Output |

## director

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/director/episodes` | Director Create Episode |
| POST | `/api/director/plan` | Director Plan |
| POST | `/api/director/render` | Director Render |

## director-pipeline

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/director-pipeline/works` | List Works |
| POST | `/api/director-pipeline/works` | Create Work |
| POST | `/api/director-pipeline/works/parse` | Parse Work |
| GET | `/api/director-pipeline/works/{work_id}` | Get Work |
| POST | `/api/director-pipeline/works/{work_id}/concept` | Regenerate Concept |
| POST | `/api/director-pipeline/works/{work_id}/concept/lock` | Lock Concept |
| GET | `/api/director-pipeline/works/{work_id}/constraints` | Get Work Constraints |
| POST | `/api/director-pipeline/works/{work_id}/constraints/compile` | Compile Work Constraints |
| POST | `/api/director-pipeline/works/{work_id}/design-list` | Regenerate Design List |
| POST | `/api/director-pipeline/works/{work_id}/design-list/lock` | Lock Design List |
| POST | `/api/director-pipeline/works/{work_id}/dispatch-season` | Dispatch Industrial Season |
| GET | `/api/director-pipeline/works/{work_id}/preparation-overview` | Preparation Overview |
| POST | `/api/director-pipeline/works/{work_id}/produce` | Produce Work |
| POST | `/api/director-pipeline/works/{work_id}/scene-stage` | Regenerate Scene Stage |
| POST | `/api/director-pipeline/works/{work_id}/scene-stage/lock` | Lock Scene Stage |
| POST | `/api/director-pipeline/works/{work_id}/screenplay` | Regenerate Screenplay |
| POST | `/api/director-pipeline/works/{work_id}/screenplay/lock` | Lock Screenplay |
| POST | `/api/director-pipeline/works/{work_id}/shot-list` | Regenerate Shot List |
| POST | `/api/director-pipeline/works/{work_id}/shot-list/lock` | Lock Shot List |
| POST | `/api/director-pipeline/works/{work_id}/shots/{shot_id}/candidates/{candidate_id}/confirm` | Confirm Shot Candidate |
| POST | `/api/director-pipeline/works/{work_id}/shots/{shot_id}/extract` | Extract Shot Candidates |
| GET | `/api/director-pipeline/works/{work_id}/shots/{shot_id}/preparation-state` | Get Shot Preparation State |
| PATCH | `/api/director-pipeline/works/{work_id}/shots/{shot_id}/readiness` | Patch Shot Readiness |

## embrace

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/embrace/chat` | Chat |
| GET | `/api/embrace/chat/{project_id}` | Chat State |
| GET | `/api/embrace/promote/{project_id}` | Promotion State |
| POST | `/api/embrace/promote/{project_id}/candidates` | Add Candidate |
| POST | `/api/embrace/promote/{project_id}/decide` | Decide Candidate |
| POST | `/api/embrace/repair-plan` | Repair Plan Endpoint |
| POST | `/api/embrace/sketch-edit` | Sketch Edit Endpoint |
| POST | `/api/embrace/style-analyze` | Style Analyze Endpoint |
| POST | `/api/embrace/workflows/run` | Run Workflow |

## explainer

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/explainer/assemble` | Assemble Explainer |
| POST | `/api/explainer/research` | Research Explainer |
| GET | `/api/explainer/research/{session_id}` | Get Research Cache |
| POST | `/api/explainer/run` | Start Run |
| GET | `/api/explainer/runs` | List Runs |
| GET | `/api/explainer/runs/{run_id}` | Get Run |
| POST | `/api/explainer/upload-presenter-image` | Upload Presenter Image Endpoint |
| POST | `/api/explainer/validate-presenter-image` | Validate Presenter Image Endpoint |

## freezone

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/freezone/candidates` | List Candidates |
| POST | `/api/freezone/candidates/{candidate_id}/promote` | Promote Candidate |
| POST | `/api/freezone/candidates/{candidate_id}/reject` | Reject Candidate |
| POST | `/api/freezone/graphs` | Create Graph |
| GET | `/api/freezone/graphs/{graph_id}` | Get Graph |
| POST | `/api/freezone/graphs/{graph_id}/run` | Run Graph |

## gallery

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/gallery` | List Gallery |
| POST | `/api/gallery` | Create Gallery Item |
| GET | `/api/gallery/{item_id}` | Get Gallery Item |

## history-series

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/history-series/animate` | Animate Episode |
| GET | `/api/history-series/next` | Get Next |
| POST | `/api/history-series/produce` | Produce |
| POST | `/api/history-series/produce-daily` | Produce Daily |
| GET | `/api/history-series/queue` | Get Queue |

## lite

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/lite/assemble` | Assemble Lite |
| POST | `/api/lite/generate` | Generate Lite Sync |
| POST | `/api/lite/runs` | Create Run |
| GET | `/api/lite/runs/{run_id}` | Get Run |
| POST | `/api/lite/runs/{run_id}/confirm` | Confirm Run |
| GET | `/api/lite/runs/{run_id}/preview.html` | Get Preview Html |
| POST | `/api/lite/runs/{run_id}/reloop` | Reloop |
| PATCH | `/api/lite/runs/{run_id}/script` | Patch Script |

## longcat

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/agent/longcat/capabilities` | Capabilities |
| POST | `/api/agent/longcat/run` | Run Longcat |

## material

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/material/archive` | Get Archive Videos |
| GET | `/api/material/coverr` | Get Coverr Videos |
| GET | `/api/material/pixabay` | Get Pixabay Videos |

## montage

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/montage/pipelines` | Pipelines |
| POST | `/api/montage/run` | Run Montage |
| POST | `/api/montage/video-agent/plan` | Plan Video Agent |
| POST | `/api/montage/video-agent/run` | Run Video Agent |

## mpt

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/mpt/cross-post` | Cross Post |
| POST | `/api/mpt/generate` | Generate Video |
| GET | `/api/mpt/health` | Health Check |
| POST | `/api/mpt/hevi/submit-job` | Submit Job From Hevi |
| POST | `/api/mpt/material/search` | Search Materials |
| POST | `/api/mpt/production` | Create Canonical Mpt Production |
| POST | `/api/mpt/reference/analyze` | Analyze Reference Video |
| GET | `/api/mpt/status/{task_id}` | Get Task Status |

## narrator

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/narrator/run` | Run |
| GET | `/api/narrator/status` | Status |

## openshorts

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/openshorts/ai-short/run` | Run Ai Short |

## payment

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/payment/checkout` | Create Checkout |
| GET | `/api/payment/orders` | List My Orders |
| GET | `/api/payment/plans` | List Plans |

## pipeline

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/pipeline/capabilities` | List Capabilities |
| POST | `/api/pipeline/generate` | Generate Unified |
| POST | `/api/pipeline/productions` | Create Production |

## presenters

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/presenters` | List Presenters |
| POST | `/api/presenters` | Create Presenter |
| POST | `/api/presenters/default` | Ensure Default Presenter |
| GET | `/api/presenters/{presenter_id}` | Get Presenter |
| PATCH | `/api/presenters/{presenter_id}` | Update Presenter |
| POST | `/api/presenters/{presenter_id}/test` | Test Presenter |

## pro-studio

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/pro/code-explainer/generate` | Code Explainer |
| POST | `/api/pro/indextts/emotion-from-text` | Emotion From Text |
| GET | `/api/pro/indextts/emotions` | Emotions |
| POST | `/api/pro/indextts/synthesize` | Synthesize Tts |
| GET | `/api/pro/livestream/capabilities` | Livestream Capabilities |
| POST | `/api/pro/livestream/start` | Livestream Start |
| GET | `/api/pro/livestream/status` | Livestream Status |
| POST | `/api/pro/livestream/stop` | Livestream Stop |
| GET | `/api/pro/livetalking/rtmp/status` | Livetalking Rtmp Status |
| GET | `/api/pro/livetalking/webrtc/capabilities` | Livetalking Webrtc Capabilities |
| POST | `/api/pro/livetalking/webrtc/offer` | Livetalking Webrtc Offer |
| POST | `/api/pro/orchestration/create-plan` | Create Plan |
| POST | `/api/pro/orchestration/execute` | Execute Plan |
| GET | `/api/pro/orchestration/roles` | Orchestration Roles |
| POST | `/api/pro/stock/search` | Stock Search |

## production-v2

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/production/v2/clip-video` | Clip Video |
| POST | `/api/production/v2/digital-human/approve` | Digital Human Approve |
| POST | `/api/production/v2/digital-human/preflight` | Digital Human Preflight |
| POST | `/api/production/v2/digital-human/preview` | Digital Human Preview |
| POST | `/api/production/v2/localize-video` | Localize Video |
| GET | `/api/production/v2/recipes` | List Recipes |
| GET | `/api/production/v2/recipes/{name}` | Get Recipe |
| POST | `/api/production/v2/recipes/{name}/execute` | Execute Recipe |
| POST | `/api/production/v2/seedance/generate` | Seedance |

## providers

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/providers/plugins` | List Provider Plugins |
| GET | `/api/providers/plugins/{provider_id}` | Get Provider Plugin |
| GET | `/api/providers/presets` | List Provider Presets |
| GET | `/api/providers/presets/{name}` | Get Provider Preset |
| GET | `/api/providers/status` | Provider Status |

## publishers

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/publishers` | Get Publishers |
| POST | `/api/publishers/{platform}/publish` | Trigger Publish |

## screenshot-studio

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/studio/screenshot/presets` | Presets |
| GET | `/api/studio/screenshot/projects` | Projects |
| POST | `/api/studio/screenshot/projects` | Create Project |
| GET | `/api/studio/screenshot/projects/{project_id}` | Get One Project |
| PATCH | `/api/studio/screenshot/projects/{project_id}` | Patch Project |
| POST | `/api/studio/screenshot/projects/{project_id}/animation-plan` | Get Animation Plan |
| POST | `/api/studio/screenshot/projects/{project_id}/export` | Export Project |

## series

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/series` | List Series |
| POST | `/api/series` | Create Series |
| GET | `/api/series/{series_id}` | Get Series |
| GET | `/api/series/{series_id}/episodes` | List Episodes |
| POST | `/api/series/{series_id}/episodes` | Create Episode |

## shortdrama

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/shortdrama/runs` | List Runs |
| POST | `/api/shortdrama/runs` | Start Run |
| GET | `/api/shortdrama/runs/{run_id}` | Get Run |
| POST | `/api/shortdrama/runs/{run_id}/characters/{char_id}/upload` | Upload Character Reference |
| POST | `/api/shortdrama/runs/{run_id}/confirm` | Confirm Run |
| POST | `/api/shortdrama/runs/{run_id}/replan` | Replan Run |

## shortdrama-writer

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/shortdrama/writer/capabilities` | Capabilities |
| POST | `/api/shortdrama/writer/draft` | Draft |
| POST | `/api/shortdrama/writer/review` | Review |

## stream-edit

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/stream-edit/budget` | Stream Budget |
| GET | `/api/stream-edit/capabilities` | Stream Capabilities |
| GET | `/api/stream-edit/sessions` | Sessions |
| POST | `/api/stream-edit/sessions` | Create Stream Session |
| GET | `/api/stream-edit/sessions/{session_id}` | Stream Session |
| POST | `/api/stream-edit/sessions/{session_id}/finish` | Finish Stream Session |

## studio

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/studio/assets` | Get Studio Assets |
| POST | `/api/studio/assets/pull` | Pull Studio Assets |
| GET | `/api/studio/daily/calendars` | Get Daily Calendars |
| POST | `/api/studio/daily/calendars` | Post Daily Calendar |
| POST | `/api/studio/daily/calendars/{calendar_id}/topics` | Post Daily Topics |
| GET | `/api/studio/daily/jobs` | Get Daily Jobs |
| POST | `/api/studio/daily/tick` | Post Daily Tick |
| GET | `/api/studio/lines` | Get Studio Lines |
| GET | `/api/studio/lines/{line_id}` | Get Studio Line |
| GET | `/api/studio/motion/shot-cards` | Get Shot Cards |
| GET | `/api/studio/nle/presets` | Get Nle Presets |
| GET | `/api/studio/nle/projects` | Get Nle Projects |
| POST | `/api/studio/nle/projects` | Create Nle Project |
| GET | `/api/studio/nle/projects/{project_id}/revisions` | Get Nle Revisions |
| POST | `/api/studio/nle/projects/{project_id}/timelines/{timeline_id}` | Attach Nle Timeline |
| GET | `/api/studio/packs` | Get Studio Packs |
| POST | `/api/studio/slates` | Create Slate |
| GET | `/api/studio/timelines` | Get Timelines |
| POST | `/api/studio/timelines` | Create Timeline |
| GET | `/api/studio/timelines/{timeline_id}` | Get One Timeline |
| PATCH | `/api/studio/timelines/{timeline_id}` | Patch Timeline |
| POST | `/api/studio/timelines/{timeline_id}/chat` | Chat Edit Timeline |
| POST | `/api/studio/timelines/{timeline_id}/export` | Export One Timeline |
| GET | `/api/studio/tools` | Get Studio Tools |
| POST | `/api/studio/tools/{tool_id}` | Invoke Studio Tool |
| GET | `/api/studio/veya/capabilities` | Get Veya Capabilities |
| GET | `/api/studio/veya/jobs/{job_id}` | Get Veya Job |
| POST | `/api/studio/veya/produce` | Post Veya Produce |
| GET | `/api/studio/voices` | Get Studio Voices |

## style-packs

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/style-packs` | Create Style Pack |
| POST | `/api/style-packs/draft-from-reference` | Draft Style Pack From Reference |
| GET | `/api/style-packs/{pack_id}` | Get Style Pack |
| PATCH | `/api/style-packs/{pack_id}` | Update Style Pack |
| GET | `/api/style-packs/{pack_id}/resolve` | Resolve Style Pack |

## subjects

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/subjects` | List Subjects |
| POST | `/api/subjects` | Create Subject |
| POST | `/api/subjects/from-photo` | Create Subject From Photo |
| DELETE | `/api/subjects/{subject_id}` | Delete Subject |
| GET | `/api/subjects/{subject_id}` | Get Subject |
| PATCH | `/api/subjects/{subject_id}` | Update Subject |
| GET | `/api/subjects/{subject_id}/image` | Get Subject Image |
| POST | `/api/subjects/{subject_id}/reference` | Upload Subject Reference |
| PUT | `/api/subjects/{subject_id}/reference-role` | Set Subject Reference Role |
| POST | `/api/subjects/{subject_id}/references` | Upload Subject References Batch |
| PUT | `/api/subjects/{subject_id}/references` | Reorder Subject References |
| POST | `/api/subjects/{subject_id}/voice` | Upload Subject Voice |
| POST | `/api/subjects/{subject_id}/wardrobe` | Upload Subject Wardrobe |

## tasks

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/tasks` | List Tasks |
| POST | `/api/tasks` | Create Task Alias |
| POST | `/api/tasks/estimate` | Estimate Task Credits |
| POST | `/api/tasks/longvideo` | ⚠️ 兼容 · Create Longvideo Task |
| GET | `/api/tasks/{task_id}` | Get Task Details |
| GET | `/api/tasks/{task_id}/audio` | Get Task Audio |
| POST | `/api/tasks/{task_id}/cancel` | Cancel Task |
| GET | `/api/tasks/{task_id}/checkpoint` | Get Task Checkpoint |
| GET | `/api/tasks/{task_id}/continuity-report` | Get Continuity Report |
| GET | `/api/tasks/{task_id}/cover` | Get Task Cover |
| GET | `/api/tasks/{task_id}/dub` | Dub Task Video |
| GET | `/api/tasks/{task_id}/export` | Export Task Video |
| GET | `/api/tasks/{task_id}/progress` | Stream Task Progress |
| POST | `/api/tasks/{task_id}/regenerate` | Regenerate Task Shots |
| POST | `/api/tasks/{task_id}/resume` | Resume Task |
| GET | `/api/tasks/{task_id}/shots` | List Task Shots |
| GET | `/api/tasks/{task_id}/shots/preparation` | Get Shots Preparation |
| PATCH | `/api/tasks/{task_id}/shots/{shot_index}/action_beats` | Update Shot Action Beats |
| PATCH | `/api/tasks/{task_id}/shots/{shot_index}/candidates/{candidate_id}` | Confirm Shot Candidate |
| GET | `/api/tasks/{task_id}/video` | Get Task Video |
| GET | `/api/tasks/{task_id}/video-url` | Get Task Video Url |

## templates

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/templates` | List Templates |
| POST | `/api/templates` | Create Template |
| DELETE | `/api/templates/{template_id}` | Delete Template |
| GET | `/api/templates/{template_id}` | Get Template |
| POST | `/api/templates/{template_id}/apply` | Apply Template |

## tongjian

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/tongjian/run` | Start Run |
| GET | `/api/tongjian/runs` | List Runs |
| GET | `/api/tongjian/runs/{run_id}` | Get Run |
| POST | `/api/tongjian/runs/{run_id}/regenerate` | Regenerate Script |
| POST | `/api/tongjian/runs/{run_id}/resume` | Resume Run |
| GET | `/api/tongjian/runs/{run_id}/script` | Get Run Script |
| PUT | `/api/tongjian/runs/{run_id}/script` | Update Run Script |
| GET | `/api/tongjian/runs/{run_id}/video` | Download Run Video |

## untagged

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | Health |
| GET | `/api/health/live` | Health Live |
| GET | `/api/health/ready` | Health Ready |
| GET | `/metrics` | Metrics |

## voice-platform

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/voice-studio/platform/audiobook/plan` | Audiobook Plan |
| POST | `/api/voice-studio/platform/batch` | Batch |
| GET | `/api/voice-studio/platform/diagnostics` | Diagnostics |
| POST | `/api/voice-studio/platform/dictation/plan` | Dictation Plan |
| POST | `/api/voice-studio/platform/dubbing/plan` | Dubbing Plan |
| GET | `/api/voice-studio/platform/models` | Models |
| POST | `/api/voice-studio/platform/models/register` | Register |
| DELETE | `/api/voice-studio/platform/models/{model_id}` | Unregister |
| POST | `/api/voice-studio/platform/route` | Route |
| GET | `/api/voice-studio/platform/voices` | Voices |
| GET | `/api/voice-studio/platform/voices/gallery` | Gallery |
| POST | `/api/voice-studio/platform/voices/gallery` | Create Gallery |
| DELETE | `/api/voice-studio/platform/voices/gallery/{profile_id}` | Remove Gallery |
| POST | `/api/voice-studio/platform/watermark/plan` | Watermark Plan |

## voice-platform-openai

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/v1/.well-known/voicestudio-speech` | Discovery |
| POST | `/v1/audio/speech` | Speech |
| POST | `/v1/audio/speech/stream` | Speech Stream |
| POST | `/v1/audio/transcriptions` | Transcriptions |
| GET | `/v1/audio/voices` | Openai Voices |

## voice-studio

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/voice-studio/batch/plan` | Speech Batch Plan |
| GET | `/api/voice-studio/catalog` | Speech Catalog |
| POST | `/api/voice-studio/config/validate` | Validate Config |
| GET | `/api/voice-studio/diagnostics` | Speech Diagnostics Endpoint |
| GET | `/api/voice-studio/effects/presets` | List Effects |
| POST | `/api/voice-studio/effects/preview` | Preview Effect |
| GET | `/api/voice-studio/personality/presets` | List Personality |
| POST | `/api/voice-studio/personality/rewrite` | Rewrite Personality |
| GET | `/api/voice-studio/profiles` | Speech Profiles |
| POST | `/api/voice-studio/tts/compare` | Compare Tts |
| GET | `/api/voice-studio/tts/engines` | List Engines |
| POST | `/api/voice-studio/tts/synthesize` | Synthesize |
