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

## credits

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/credits/balance` | Get Balance |
| POST | `/api/credits/estimate` | Estimate Credits |
| POST | `/api/credits/topup` | Manual Topup |
| GET | `/api/credits/transactions` | List Transactions |

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
| POST | `/api/director-pipeline/works/{work_id}/design-list` | Regenerate Design List |
| POST | `/api/director-pipeline/works/{work_id}/design-list/lock` | Lock Design List |
| POST | `/api/director-pipeline/works/{work_id}/dispatch-season` | Dispatch Industrial Season |
| GET | `/api/director-pipeline/works/{work_id}/preparation-overview` | Preparation Overview |
| POST | `/api/director-pipeline/works/{work_id}/produce` | Produce Work |
| POST | `/api/director-pipeline/works/{work_id}/screenplay` | Regenerate Screenplay |
| POST | `/api/director-pipeline/works/{work_id}/screenplay/lock` | Lock Screenplay |
| POST | `/api/director-pipeline/works/{work_id}/shot-list` | Regenerate Shot List |
| POST | `/api/director-pipeline/works/{work_id}/shot-list/lock` | Lock Shot List |
| POST | `/api/director-pipeline/works/{work_id}/shots/{shot_id}/candidates/{candidate_id}/confirm` | Confirm Shot Candidate |
| POST | `/api/director-pipeline/works/{work_id}/shots/{shot_id}/extract` | Extract Shot Candidates |
| GET | `/api/director-pipeline/works/{work_id}/shots/{shot_id}/preparation-state` | Get Shot Preparation State |
| PATCH | `/api/director-pipeline/works/{work_id}/shots/{shot_id}/readiness` | Patch Shot Readiness |

## explainer

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/explainer/run` | Start Run |
| GET | `/api/explainer/runs` | List Runs |
| GET | `/api/explainer/runs/{run_id}` | Get Run |

## gallery

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/gallery` | List Gallery |
| POST | `/api/gallery` | Create Gallery Item |
| GET | `/api/gallery/{item_id}` | Get Gallery Item |

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
| GET | `/api/production/v2/recipes` | List Recipes |
| GET | `/api/production/v2/recipes/{name}` | Get Recipe |
| POST | `/api/production/v2/recipes/{name}/execute` | Execute Recipe |
| POST | `/api/production/v2/seedance/generate` | Seedance |

## providers

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/providers/presets` | List Provider Presets |
| GET | `/api/providers/presets/{name}` | Get Provider Preset |

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
| GET | `/api/tasks/{task_id}/continuity-report` | Get Continuity Report |
| GET | `/api/tasks/{task_id}/cover` | Get Task Cover |
| GET | `/api/tasks/{task_id}/dub` | Dub Task Video |
| GET | `/api/tasks/{task_id}/export` | Export Task Video |
| GET | `/api/tasks/{task_id}/progress` | Stream Task Progress |
| POST | `/api/tasks/{task_id}/regenerate` | Regenerate Task Shots |
| POST | `/api/tasks/{task_id}/resume` | Resume Task |
| GET | `/api/tasks/{task_id}/shots` | List Task Shots |
| GET | `/api/tasks/{task_id}/video` | Get Task Video |

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
| GET | `/metrics` | Metrics |

## voice-studio

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/voice-studio/config/validate` | Validate Config |
| GET | `/api/voice-studio/effects/presets` | List Effects |
| POST | `/api/voice-studio/effects/preview` | Preview Effect |
| GET | `/api/voice-studio/personality/presets` | List Personality |
| POST | `/api/voice-studio/personality/rewrite` | Rewrite Personality |
| GET | `/api/voice-studio/tts/engines` | List Engines |
| POST | `/api/voice-studio/tts/synthesize` | Synthesize |
