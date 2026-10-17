# P1 Director Workbench Inventory

Status: implementation baseline for `product/director-workbench-vnext`.

This inventory records the existing product surfaces before the Workbench
extension. The Workbench is a projection and command surface over Studio API
v2; it does not introduce a second production store.

| PATH | COMPONENT | PURPOSE | DATA_SOURCE | STATE_AUTHORITY | REUSABLE | OVERLAP | P1_ACTION |
|---|---|---|---|---|---|---|---|
| `/studio` | `HeviCanvas` | Existing freeform canvas | `canvasApi` and React Flow | Canvas API for graph/UI layout; production API for semantics | Canvas shell, node primitives | Workbench canvas tab | EXTEND |
| `/projects` | `TaskDashboard`, `ProductionConsole` | Legacy task/project list | task and production APIs | backend task store | task rows, status presentation | Workbench Task Center | REWIRE |
| `/projects/[id]` | `ProjectDetailPage` | Legacy task detail and media result | `taskApi` | task store | media/status presentation | Workbench delivery/artifact view | KEEP |
| `/studio/timeline` | `TimelineEditor` | Timeline editing and preview | `studioApi` timeline endpoints | persisted timeline API | track/clip editor patterns | Workbench Timeline tab | EXTEND |
| `/director` | `DirectorConsole` | Existing creative/director interaction | director and production APIs | Director/product backend | director messaging patterns | Workbench Director panel | MERGE |
| `/director-pipeline` | `DirectorPipelineConsole` | Script-to-shot production flow | director pipeline API | pipeline backend | stage/status patterns | Workbench Story/Storyboard actions | KEEP |
| `/season-board` | `SeasonBoard` | Episode and shot board | season/task APIs | backend task/shot projection | shot card/status patterns | Workbench navigator/storyboard | REWIRE |
| `/assets` | `AssetLibrary` | Subject and asset browsing | subject/asset APIs | subject/asset backend | asset cards and upload states | Workbench Assets tab | EXTEND |
| `/app/canvas` components | `NodeInspector`, `NodeContextMenu`, `NodePalette` | Canvas node projection/editing | canvas API | canvas UI metadata plus canonical command API | node interactions | Workbench Canvas tab | EXTEND |
| `src/lib/api-client.ts` | REST client | Central API transport/auth | Studio, task, subject, canvas APIs | backend responses; no local domain authority | request/auth/error handling | all Workbench tabs | EXTEND |
| `src/types/api.ts` | shared DTOs | Existing API contracts | backend schemas | backend contract | typed client boundary | Workbench DTOs | EXTEND |
| `src/app/globals.css` | global styles | Existing design tokens and product styles | CSS variables | browser view state | tokens, buttons, responsive patterns | Workbench shell | EXTEND |
| `TopNav`, `RequireAuth`, `AuthProvider` | app chrome/auth | Navigation and auth lifecycle | auth API/store | auth backend/session | shell and auth | Workbench route | KEEP |

## P1 routing decisions

- Canonical Workbench route: `/studio/projects/{project_id}`.
- `/studio` remains the existing Canvas entrypoint and is not replaced.
- `/projects/[id]` remains compatible with legacy task IDs; canonical
  production project IDs resolve through the new Workbench route.
- Production entities are loaded from `GET /api/studio/projects/{id}` and
  related Studio API v2 projections. Mutations use revision-producing
  endpoints (`PATCH`, `prepare`, `approve`, `lock`, Director messages, and
  future typed patch commands).
- React state stores selection, tabs, loading, and panel state only. It does
  not become an authoritative production graph.

## Existing capability gaps recorded for P1

The current frontend has no canonical project Workbench shell, no unified
project navigator, and no dedicated projection for P0 DirectorSession,
RevisionPatch, ShotReadiness, ExecutionPlan, or artifact provenance. P1 adds
these views through the existing API client boundary and keeps provider/runtime
details in advanced diagnostics rather than ordinary user navigation.
