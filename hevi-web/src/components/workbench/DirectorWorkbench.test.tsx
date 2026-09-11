import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { DirectorWorkbench } from './DirectorWorkbench';

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  patchProject: vi.fn(),
  createDirectorSession: vi.fn(),
  directorMessage: vi.fn(),
  prepareShot: vi.fn(),
  tasks: vi.fn(),
  revisions: vi.fn(),
}));

vi.mock('@/lib/api-client', () => ({
  canonicalProductionApi: { ...mocks, approveShot: vi.fn(), lockShot: vi.fn(), generateShot: vi.fn(), regenerateShot: vi.fn() },
}));

const snapshot = {
  project: { id: 'project-1', user_id: 'user-1', title: 'Historical Gate', source_kind: 'historical', creative_brief: 'A tense crossing.', target_platform: '', aspect_ratio: '16:9', visual_style: 'documentary', production_mode: 'SHOT_REVIEW', status: 'active' },
  revision: { id: 'revision-2', project_id: 'project-1', revision_no: 2, actor: 'director', reason: 'test', locked: false },
  sources: [{ id: 'source-1' }], source_chunks: [], narrative: { events: [{ id: 'event-1', summary: 'The envoy arrives', temporal_order: 1, source_refs: [], plot_thread_ids: [], character_ids: [] }], edges: [], plot_threads: [] },
  adaptation_plans: [], adaptation_decisions: [], characters: [{ id: 'character-1' }], character_states: [], look_variants: [], locations: [], location_states: [], props: [], prop_states: [],
  episodes: [{ id: 'episode-1', number: 1, title: 'Dawn', narrative_event_ids: [] }], scenes: [{ id: 'scene-1', episode_id: 'episode-1', purpose: 'Crossing', dramatic_function: '', emotional_target: '', narrative_event_ids: [], character_ids: [], prop_ids: [] }], beats: [],
  shots: [{ id: 'shot-1', scene_id: 'scene-1', beat_ids: [], narrative_event_ids: [], character_ids: [], action_description: 'Crosses the gate', cinematography_notes: '', duration_target: 12, readiness_state: 'READY', camera: { shot_size: 'wide', movement: 'slow_push' }, keyframe_ids: [], continuity_constraint_ids: [], dialogue: [] }],
  keyframes: [], reference_bundles: [], continuity_constraints: [], readiness_results: [], director_sessions: [], director_decisions: [], revision_patches: [], production_plans: [], execution_plans: [], execution_attempts: [], provenance_links: [],
};

describe('DirectorWorkbench', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.get.mockResolvedValue(snapshot);
    mocks.patchProject.mockResolvedValue(snapshot);
    mocks.createDirectorSession.mockResolvedValue({ session: { id: 'session-1' }, revision: snapshot.revision });
    mocks.directorMessage.mockResolvedValue({ decision: { id: 'decision-1', session_id: 'session-1', project_id: 'project-1', decision_type: 'creative_revision', inputs: {}, rationale: 'Make it tense' }, revision: snapshot.revision });
    mocks.prepareShot.mockResolvedValue({ shot: snapshot.shots[0], readiness: { shot_id: 'shot-1', state: 'READY', passed: true, blockers: [], warnings: [], checks: {} }, revision: snapshot.revision });
    mocks.tasks.mockResolvedValue({ tasks: [], total: 0 });
    mocks.revisions.mockResolvedValue({ revisions: [snapshot.revision] });
  });

  it('reopens from the canonical snapshot and exposes shared project context', async () => {
    render(<DirectorWorkbench projectId="project-1" />);
    expect(await screen.findByTestId('director-workbench')).toBeInTheDocument();
    expect(screen.getByText('Historical Gate')).toBeInTheDocument();
    expect(screen.getByText('Revision 2 · revision')).toBeInTheDocument();
    expect(screen.getByText('Crosses the gate')).toBeInTheDocument();
    expect(mocks.get).toHaveBeenCalledWith('project-1');
  });

  it('uses canonical commands for readiness and persists Director decisions', async () => {
    render(<DirectorWorkbench projectId="project-1" />);
    await screen.findByTestId('director-workbench');
    fireEvent.click(screen.getByRole('button', { name: 'Run readiness' }));
    await waitFor(() => expect(mocks.prepareShot).toHaveBeenCalledWith('shot-1'));
    fireEvent.change(screen.getByPlaceholderText('例如：这一场更紧张一点。'), { target: { value: 'Make it tense' } });
    fireEvent.click(screen.getByRole('button', { name: '提出 Revision' }));
    await waitFor(() => expect(mocks.directorMessage).toHaveBeenCalled());
    expect(mocks.createDirectorSession).toHaveBeenCalledWith('project-1', 'Assist the director with canonical production revisions.');
  });
});
