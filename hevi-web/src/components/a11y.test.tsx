/**
 * D7-C: accessibility contract tests for the critical product surfaces.
 *
 * The stack has no axe-core dependency, so these are deterministic DOM/ARIA
 * contract tests over the real components: accessible names, labels, live
 * regions and explicit paid-action wording.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { CharacterLibrary } from '@/components/characters/CharacterLibrary';
import { ContinuityCheckPanel } from '@/components/continuity/ContinuityCheckPanel';
import { ProductionIssuesPanel } from '@/components/repair/ProductionIssuesPanel';
import { ProjectHealthPanel } from '@/components/production/ProjectHealthPanel';
import { QuickStart } from '@/components/onboarding/QuickStart';

const hoisted = vi.hoisted(() => ({
  list: vi.fn(),
  create: vi.fn(),
  bind: vi.fn(),
  inspect: vi.fn(),
  upgrade: vi.fn(),
  archive: vi.fn(),
  summary: vi.fn(),
  gate: vi.fn(),
  listProduct: vi.fn(),
  confirm: vi.fn(),
  refuse: vi.fn(),
  timeline: vi.fn(),
  projectHealth: vi.fn(),
  metrics: vi.fn(),
}));

vi.mock('@/lib/api-client', () => ({
  identityApi: {
    list: hoisted.list, create: hoisted.create, bind: hoisted.bind,
    inspect: hoisted.inspect, upgrade: hoisted.upgrade, archive: hoisted.archive,
  },
  continuityApi: { projectSummary: hoisted.summary, gate: hoisted.gate },
  incidentApi: {
    listProduct: hoisted.listProduct, confirm: hoisted.confirm,
    refuse: hoisted.refuse, timeline: hoisted.timeline,
  },
  productApi: { projectHealth: hoisted.projectHealth, metrics: hoisted.metrics },
}));

const identity = {
  identity_id: 'i1', canonical_name: 'Anna', aliases: [], kind: 'character',
  identity_version: 1, archived: false, upgrade_available: false,
  appearance_count: 0, appearances: [], voice_id: 'v', binding_count: 0,
  projects_using: [], linked_subjects: [],
};

describe('D7-C accessibility contracts', () => {
  it('character library: labelled search + named buttons', async () => {
    hoisted.list.mockResolvedValue([identity]);
    render(<CharacterLibrary projectId="p" />);
    await screen.findByText('Anna');
    expect(screen.getByLabelText('搜索角色')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '用于当前项目' })).toBeInTheDocument();
    expect(screen.getByRole('list', { name: '角色列表' })).toBeInTheDocument();
  });

  it('continuity BLOCK exposes an alert-like state and no proceed button', async () => {
    hoisted.summary.mockResolvedValue({
      project_id: 'p', verdict: 'block', gate_ready: false, binding_count: 1, facts: [],
      issues: [{ severity: 'block', code: 'X', detail: 'conflict' }],
    });
    render(<ContinuityCheckPanel projectId="p" />);
    expect(await screen.findByTestId('continuity-blocked-note')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '仍然继续生成' })).not.toBeInTheDocument();
  });

  it('paid repair has explicit cost wording and a named confirm action', async () => {
    hoisted.listProduct.mockResolvedValue({
      incidents: [{
        incident_id: 'in1', production_run_id: 'r', node_key: 'n', status: 'open',
        root_cause: 'paid_regeneration_needed', failure_code: 'X', diagnosis: 'd',
        needs_agent: false, policy: 'confirm_required', requires_confirmation: true,
        estimated_cost_usd: 3, preserved_artifact_ids: [], preserved_intact: true,
        attempts: 0, verification_result: {},
      }],
    });
    render(<ProductionIssuesPanel productionRunId="r" />);
    expect(await screen.findByText(/预计新增费用/)).toBeInTheDocument();
    expect(screen.getByTestId('confirm-hint-in1')).toHaveTextContent('重新生成相关素材');
    const confirm = screen.getByRole('button', { name: '确认修复' });
    expect(confirm).toBeInTheDocument();
    // No bare "Retry" that hides billing.
    expect(screen.queryByRole('button', { name: /^Retry$/i })).not.toBeInTheDocument();
  });

  it('project health next action is a named button', async () => {
    hoisted.projectHealth.mockResolvedValue({
      project_id: 'p', status: 'READY', task_status: '', currency: { available: false, counts: {} },
      continuity: null, incidents: [], next_action: { kind: 'continue', label: '继续制作' },
    });
    render(<ProjectHealthPanel projectId="p" />);
    expect(await screen.findByRole('button', { name: /继续制作/ })).toBeInTheDocument();
  });

  it('quick start has labelled inputs and a non-required advanced section', () => {
    const { container } = render(<QuickStart />);
    expect(screen.getByLabelText('项目类型')).toBeInTheDocument();
    expect(screen.getByLabelText('素材')).toBeInTheDocument();
    expect(screen.getByLabelText('目标输出')).toBeInTheDocument();
    expect(container.querySelector('details')?.open).toBe(false);
  });
});
