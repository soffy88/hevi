# HEVI production-domain inventory

Status: P0.0 baseline inventory  
Baseline: RC6 `0fcb65333ac5f6cd0860012fa569b6b050e22c6b`  
Branch: `architecture/production-graph-vnext`

This is the inventory required before introducing new canonical domain
objects.  “Authority” means the component that is allowed to decide the
meaning of the data today; a UI or runtime projection is explicitly not an
authority.  Persistence is reported as it exists at RC6, including in-memory
and JSON compatibility stores.

| MODULE | TYPE | PURPOSE | PERSISTENCE | AUTHORITY | CONSUMERS | OVERLAPS | TARGET_CANONICAL_TYPE | MIGRATION_ACTION |
|---|---|---|---|---|---|---|---|---|
| `hevi/tongjian/schemas.py` | `ChapterIR` | Chapter-scoped source extraction envelope | JSON artifact / task state | Tongjian extraction | Tongjian stages, historical production | `NovelEvent`, `NarrativeEvent` | `SourceDocument`, `SourceChunk`, `NarrativeGraph` | ADAPT |
| `hevi/tongjian/schemas.py` | `CharacterIR` | Source character identity and mentions | `ChapterIR` JSON | Source extraction | character bible, script | `KernelCharacter`, `CharacterBibleEntry` | `Character` + provenance | ADAPT |
| `hevi/tongjian/schemas.py` | `EventIR` | Historical event, actors, causes/effects, source span | `ChapterIR` JSON | Source extraction | constitution, script, provenance | `NovelEvent` | `NarrativeEvent` | CANONICALIZE |
| `hevi/tongjian/schemas.py` | `Script`, `ScriptLine` | Historical script and quote/dramatization trace | JSON artifact | Tongjian script stage | render and assembly | `ScreenplayScene`, `BeatDialogue` | `Scene`, `Beat` | ADAPT |
| `hevi/tongjian/schemas.py` | `Timeline`, `AudioSegment` | Narration/audio timing | JSON artifact | Tongjian audio stage | assembly | `ProductionPlan` audio intent | PROJECT |
| `hevi/tongjian/schemas.py` | `Shot`, `ShotCamera` | Historical shot-list DTO and action-beat hints | JSON artifact | Tongjian shot stage | frame/render bridge | `CineShot`, `ShotListItem` | `CanonicalShot`, `CameraSpec`, `Keyframe` | ADAPT |
| `hevi/tongjian/schemas.py` | `CharacterBible`, `CharacterBibleEntry` | Historical role/appearance/reference DTO | JSON artifact | Tongjian character-bible stage | Vault and render | `Vault Manifest`, `Character` | `Character`, `LookVariant`, `ReferenceBundle` | ADAPT |
| `hevi/tongjian/schemas.py` | `FrameManifest`, `ShotFrame` | Generated frame/clip result DTO | JSON artifact / task config | render adapter | assembly, QA | `ArtifactManifest` | PROJECT |
| `hevi/tongjian/chapter_ir.py` | extraction functions | Deterministic source-span resolution and ID assignment | persisted upstream artifact | Tongjian | `ChapterIR` consumers | narrative graph builder | `SourceDocument`/`NarrativeEvent` adapter | ADAPT |
| `hevi/tongjian/character_bible.py` | character-bible pipeline | Creates and audits identity candidates | Vault manifests and artifacts | Vault promotion gate | historical renderer | `IdentityPack`, `Subject` | `Character`→`IdentityPack` binding | ADAPT |
| `hevi/cinematic/schemas.py` | `Scene` | Film branch scene DTO | JSON task/document | Cinematic branch | shot planner | `ScreenplayScene`, `NovelScene` | `Scene` | ADAPT |
| `hevi/cinematic/schemas.py` | `Beat`, `BeatDialogue` | Film action/dialogue beat | JSON task/document | Cinematic branch | shot planner, QA | `SceneBeat`, `ScriptLine` | `Beat` | CANONICALIZE |
| `hevi/cinematic/schemas.py` | `CineShot`, `CineShotList` | Film shot plan and prompt DTO | JSON task/document | Cinematic planner | video generation, CG6 | Tongjian `Shot`, `ShotListItem` | `CanonicalShot` | ADAPT |
| `hevi/cinematic/schemas.py` | `CineShotCamera` | Basic size/movement camera DTO | nested JSON | Cinematic planner | `CineShot` | `ShotCamera`, `CameraSetup` | `CameraSpec` | ADAPT |
| `hevi/cinematic/shot_planning.py` | `plan_shots`, `gate_shotlist` | Deterministic clean-face, duration and prompt gates | no durable state | planner rules | Cinematic workflow | Director shot planning | `CanonicalShot` readiness inputs | ADAPT |
| `hevi/script2video/schemas.py` | `KernelCharacter` | Provider-neutral Script2Video character kernel | in-memory / JSON | Script2Video adapter | kernel workflows | `CharacterIR`, `CharacterBibleEntry` | `Character` | ADAPT |
| `hevi/script2video/schemas.py` | `KernelShot`, `ShotVisualPlan` | Normalized visual plan and first/last frame descriptions | in-memory / JSON | Script2Video kernel | image/video workflows | `Shot`, `Keyframe` | `CanonicalShot`, `Keyframe` | ADAPT |
| `hevi/script2video/schemas.py` | `CameraTree`, `CameraNode` | Camera dependency/generation ordering | in-memory / JSON | Script2Video kernel | reference and transition workflows | `CameraTree` in director | `CameraSpec` + plan dependencies | ADAPT |
| `hevi/script2video/schemas.py` | `PortraitRegistry`, `CharacterPortrait` | Three-view portrait compatibility registry | JSON registry / paths | Script2Video compatibility layer | reference selection | Vault IdentityPack | `Character`→`ReferenceBundle` | ADAPT |
| `hevi/script2video/adapter_schemas.py` | `NovelEvent` | Novel event compression DTO | in-memory / JSON | Novel2Video planner | novel workflow | `EventIR`, `NarrativeEvent` | `NarrativeEvent` | ADAPT |
| `hevi/script2video/adapter_schemas.py` | `NovelPlan` | Novel compression and scene plan | task/document JSON | Novel2Video planner | director workflow | `NarrativeGraph`, `AdaptationPlan` | `ProductionPlan` + graph | ADAPT |
| `hevi/script2video/adapter_schemas.py` | `NovelScene` | Novel scene script DTO | in-memory / JSON | Novel2Video planner | script2video kernel | Cinematic `Scene` | `Scene` | ADAPT |
| `hevi/script2video/adapter_schemas.py` | `NovelCharacterBook` | Cross-event active character tracking | in-memory / JSON | Novel2Video planner | continuity and scene planning | `CharacterState` | `CharacterState` | CANONICALIZE |
| `hevi/script2video/omodul/novel_plan.py` | `plan_novel2video` | Novel compression and event-to-scene planning | stage checkpoint | Novel2Video stage | production workflow | Tongjian adaptation | `AdaptationPlan` | ADAPT |
| `hevi/director/pipeline_schemas.py` | `Screenplay`, `ScreenplayScene` | Director screenplay DTO | `director_documents` JSONB | Director pipeline | design/stage/shot bridge | Tongjian `Script`, Cinematic `Scene` | `Scene`, `Beat` | ADAPT |
| `hevi/director/pipeline_schemas.py` | `DesignList`, design entities | Character/scene/prop design list | `director_documents` JSONB | Director pipeline | SceneStage, render | Vault and world assets | `Character`, `Location`, `Prop`, `LookVariant` | ADAPT |
| `hevi/director/pipeline_schemas.py` | `ShotListItem`, `ShotList` | Director shot list, blocking and camera hints | `director_documents` JSONB | Director pipeline | shot preparation/render | Cinematic and Tongjian shots | `CanonicalShot`, `CameraSpec` | ADAPT |
| `hevi/director/pipeline_schemas.py` | `SceneStage`, `SceneStageSet` | Blocking, axis, attention and coverage facts | `director_documents` JSONB | Director scene-stage gate | shot linking, camera continuity | `Scene`, `CameraSpec`, `ContinuityConstraint` | PROJECT |
| `hevi/director/novel2video.py` | `NovelEvent`, `NovelPlan`, `NovelScene` exports | Backward-compatible Director imports | no own store | compatibility module | API and old callers | Script2Video DTOs | canonical narrative adapters | DEPRECATE_LATER |
| `hevi/director/camera_tree.py` | camera/axis helpers | Camera orientation and continuity rules | no durable state | deterministic lint | SceneStage, shot planning | Script2Video CameraTree | `CameraSpec`, `ContinuityConstraint` | ADAPT |
| `hevi/director/agent.py` | Director loop | Producer→execution→Editor→targeted rework | task/checkpoint state | Director orchestration | director production route | `DirectorSession` | `DirectorSession`, `DirectorDecision` | ADAPT |
| `hevi/director/producer.py` | Producer planning | Feasibility and cost/provider selection | transient/task JSON | Producer loop | Director | `ProductionPlan` | `ProductionPlan` | ADAPT |
| `hevi/director/editor.py` | Editor/review | Post-generation review and rework suggestions | evaluation/task state | QA/editor loop | Director | `ShotReadinessResult`, constraints | `DirectorDecision`/QA projection | ADAPT |
| `hevi/vault/schemas.py` | `Manifest`, `ManifestFile` | Versioned identity/style/scene/voice asset manifest | Vault PostgreSQL + object store | Vault lifecycle/promotion | character and cinematic generation | `CharacterBibleEntry`, `Subject` | `ReferenceItem` pointing to artifact/pack | KEEP_AUTHORITY |
| `hevi/vault/schemas.py` | `Provenance`, `StabilityCheck` | Asset origin and stability evidence | Vault manifest JSONB | Vault | QA and identity selection | Artifact provenance | extended provenance chain | CANONICALIZE |
| `hevi/vault/service.py` | asset CRUD/promotion | Durable Vault asset lifecycle | Vault tables/object store | Vault | identity pack, API | subject/reference stores | `ReferenceBundle` binding | KEEP_AUTHORITY |
| `hevi/subjects/models.py` | `Subject` | Existing user-facing identity asset | `subjects` PostgreSQL table | Subjects/Vault boundary | account, director, providers | `Character`, `CharacterBible` | `Character` asset binding | ADAPT |
| `hevi/creative/reference_link.py` | reference links | Links creative records to selected assets | task/JSON projection | Creative service | assistants and generation | Vault refs, Canvas nodes | `ReferenceItem` | ADAPT |
| `hevi/canvas/graph_models.py` | `CanvasGraph` | Editable node/edge layout projection | `canvas_graphs.nodes_json/edges_json` | Canvas UI only | Canvas API/executor | every graph-like domain DTO | canonical IDs + projection | PROJECT |
| `hevi/canvas/graph_service.py` | graph service | Canvas CRUD and execution compatibility | PostgreSQL JSONB | Canvas projection | frontend, MCP | Studio/project state | Canvas projection of canonical graph | ADAPT |
| `hevi/studio/recipes.py` | `Recipe`, `SlotSpec` | YAML production-line contract | YAML files | Studio recipe catalog | Slate | production lines and plans | `ProductionPlan` policy | KEEP_AUTHORITY |
| `hevi/studio/slate.py` | `Slate`, `SlateResult` | Deterministic work-order boundary | checkpoint/task/artifact state | Slate execution | all recipes, API | TaskService/MPT | canonical ProductionPlan→Slate bridge | KEEP_AUTHORITY |
| `hevi/pipeline/manifest.py` | `PipelineManifest`, stages/checkpoints | Resumable deterministic pipeline execution | checkpoint store / files | runtime | Slate and workflows | MPT/task runtime | `ExecutionAttempt`/`TaskEnvelope` adapter | KEEP_AUTHORITY |
| `hevi/production/artifacts.py` | `Artifact`, `ArtifactManifest` | Integrity-checked output manifest | task JSON + ArtifactStore DB | Artifact layer | assembly, API, QA | `FrameManifest`, Vault files | existing artifact authority + provenance extension | KEEP_AUTHORITY |
| `hevi/artifact_store/repository.py` | `ArtifactRepository` | Content-addressed artifact metadata and relations | `artifacts`, `artifact_relations` | ArtifactStore | tasks, delivery, provenance | task artifact projection | existing ArtifactStore | KEEP_AUTHORITY |
| `hevi/execution/plan.py` | immutable `ExecutionPlan` | Insert-only plan version and hash | `execution_plans` JSONB | execution boundary | compiler/runtime/rework | production graph execution plan | canonical `ExecutionPlan` contract | CANONICALIZE |
| `hevi/execution/scheduler.py` | `ResourceSnapshot`, `SchedulingRequest` | Resource-aware task ranking | runtime observation | scheduler | task repository/worker | GPU guard and queue worker | `ExecutionProfile` | ADAPT |
| `hevi/tasks/models.py` | `VideoTask`, `ShotState` | Task and shot execution projection | PostgreSQL | TaskService | worker/API/dashboard | Slate, MPT, attempt history | `TaskEnvelope`, `ExecutionAttempt` projection | ADAPT |
| `hevi/tasks/attempt_repository.py` | `AttemptRepository`, checkpoints | Durable leases, retry and resume | `task_attempts`, `attempt_checkpoints` | task runtime | worker/scheduler | MPT/checkpoint runtime | `ExecutionAttempt`, `TaskEnvelope` | KEEP_AUTHORITY |
| `hevi/constraints/models.py` | `Constraint`, `ConstraintGraph` | Provider-neutral continuity/quality constraints | revision JSONB + normalized rows | constraint compiler | production graph/compiler/QA | SceneStage lint and prompt checks | `ContinuityConstraint` adapter | ADAPT |
| `hevi/db/alembic/versions/0a1b2c3d4e5f_create_production_graph.py` | `productions`, `production_revisions` | Existing durable production aggregate and snapshots | PostgreSQL | ProductionGraphRepository | director API/task service | requested `ProductionProject`, `ProductionRevision` | extend and reuse | CANONICALIZE |
| `hevi/db/alembic/versions/b8c9d0e1f234_create_execution_plans.py` | `execution_plans`, `execution_nodes` | Durable immutable execution plan storage | PostgreSQL | ExecutionPlanRepository | runtime and repair | requested compiler plan | KEEP_AUTHORITY |
| `hevi/db/alembic/versions/3d4e5f607182_create_artifact_provenance.py` | artifact tables | Durable artifact lineage and integrity | PostgreSQL/object store | ArtifactRepository | delivery/QA | requested provenance chain | extend, do not duplicate | KEEP_AUTHORITY |

## Findings frozen for P0

1. `hevi/production_graph` is the existing production aggregate owner.  P0
   extends it into the canonical graph; it does not add a second production
   repository.
2. `ChapterIR`, `NovelPlan`, Cinematic scene/shot DTOs, and Director documents
   remain compatibility inputs/projections during P0.  They are not deleted.
3. Vault remains the authority for binary identity-pack lifecycle.  Canonical
   `Character` and `ReferenceBundle` records carry stable semantic bindings to
   Vault/artifact IDs; they do not copy binary storage.
4. `CanvasGraph.nodes_json` and `edges_json` remain UI layout state.  A node
   must reference a canonical object ID for production meaning.
5. `run_slate()` and `AttemptRepository` remain the deterministic execution
   and durability boundary.  Director work is adapted into them through a
   typed production plan.
6. Existing `Artifact`/`ArtifactManifest` and `ArtifactRepository` remain the
   only artifact store.  Creative provenance is an extension of its metadata
   and relations.
