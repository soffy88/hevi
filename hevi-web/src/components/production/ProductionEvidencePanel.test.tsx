import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ProductionEvidencePanel } from './ProductionEvidencePanel';

const hoisted = vi.hoisted(() => ({
  get: vi.fn(),
  checkpoint: vi.fn(),
  currency: vi.fn(),
  presentation: vi.fn(),
  incidents: vi.fn(),
}));

vi.mock('@/lib/api-client', () => ({
  taskApi: { get: hoisted.get, checkpoint: hoisted.checkpoint },
  artifactAuthorityApi: { currency: hoisted.currency, presentation: hoisted.presentation },
  incidentApi: { listProduct: hoisted.incidents },
}));

describe('ProductionEvidencePanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    hoisted.get.mockResolvedValue({
      task_id: 'task-1', status: 'completed', percent: 100,
      production_id: 'production-1', revision_id: 'revision-1', current_attempt_id: 'attempt-1',
      config_json: {
        quality_evaluation: { measurements: { black_frame_ratio: 0 }, policy: { decision: 'PASS' } },
        artifact_manifest: { production_id: 'production-1', revision_id: 'revision-1', artifacts: [
          { artifact_id: 'final-1', kind: 'video', logical_role: 'final_video', sha256: 'abc', parent_artifact_ids: ['timeline-1'] },
        ] },
      },
    });
    hoisted.checkpoint.mockResolvedValue({ task_id: 'task-1', has_checkpoint: true, attempt_id: 'attempt-1', stage: 'completed' });
    hoisted.currency.mockResolvedValue({ usable: 1, total: 1, evaluations: [{ artifact_id: 'final-1', currency: 'current' }] });
    hoisted.presentation.mockResolvedValue({ video: { artifact_id: 'final-1' } });
    hoisted.incidents.mockResolvedValue({ incidents: [] });
  });

  it('renders backend IDs, current currency, lineage, and quality evidence without recomputing them', async () => {
    render(<ProductionEvidencePanel taskId="task-1" onClose={vi.fn()} />);
    await waitFor(() => expect(screen.getByTestId('production-evidence')).toBeInTheDocument());
    expect(screen.getByText('production-1')).toBeInTheDocument();
    expect(screen.getByText('revision-1')).toBeInTheDocument();
    expect(screen.getByText(/currency：current/)).toBeInTheDocument();
    expect(screen.getAllByText(/timeline-1/).length).toBeGreaterThan(0);
    expect(screen.getByText(/black_frame_ratio/)).toBeInTheDocument();
  });
});
