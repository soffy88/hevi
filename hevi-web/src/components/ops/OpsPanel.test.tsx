/**
 * OpsPanel 回归测试 — D3-D
 * 身份/连续性/修复三区只消费 canonical API,不做本地状态推导。
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { OpsPanel } from './OpsPanel';

const hoisted = vi.hoisted(() => ({
  isAuthed: vi.fn().mockReturnValue(true),
  identityList: vi.fn().mockResolvedValue([
    {
      identity_id: 'i1', canonical_name: 'Anna', kind: 'character',
      identity_version: 2, appearance_count: 2, voice_id: 'v-anna',
      binding_count: 1, linked_subjects: [],
    },
  ]),
  facts: vi.fn().mockResolvedValue({
    identity_id: 'i1',
    facts: [{
      fact_id: 'f1', identity_id: 'i1', category: 'location',
      statement: 'harbor city', episode: 'ep1', scene: '', shot: '',
      revision: '', source_artifact_id: 'a1', provenance: 'canon',
    }],
  }),
  incidentList: vi.fn().mockResolvedValue({
    incidents: [{
      incident_id: 'in1', production_run_id: 'r1', node_key: 'task.run',
      artifact_id: '', root_cause: 'provider_temp_unavailable', failure_code: 'PROVIDER_FAILURE',
      evidence: {}, diagnosis: '', candidate_actions: [], selected_action: null,
      needs_agent: false, status: 'open', attempts: 0, verification_result: {},
    }],
  }),
  confirm: vi.fn().mockResolvedValue({ approved: true }),
  refuse: vi.fn().mockResolvedValue({ status: 'escalated_manual' }),
  bind: vi.fn().mockResolvedValue({ binding_id: 'b1', pinned_identity_version: 2 }),
}));

vi.mock('@/lib/auth-store', () => ({ isAuthenticated: () => hoisted.isAuthed() }));
vi.mock('@/lib/api-client', () => ({
  identityApi: {
    list: hoisted.identityList,
    bind: hoisted.bind,
  },
  continuityApi: { facts: hoisted.facts },
  incidentApi: {
    list: hoisted.incidentList,
    confirm: hoisted.confirm,
    refuse: hoisted.refuse,
  },
}));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

describe('生产运维面板(D3-D)', () => {
  it('渲染身份/事件列表,不做本地推导', async () => {
    render(<OpsPanel />);
    expect(await screen.findByTestId('ops-panel')).toBeInTheDocument();
    expect(await screen.findByText(/Anna v2/)).toBeInTheDocument();
    expect(screen.getByText(/provider_temp_unavailable/)).toBeInTheDocument();
    // canonical 调用发生
    expect(hoisted.identityList).toHaveBeenCalled();
    expect(hoisted.incidentList).toHaveBeenCalled();
  });

  it('查看连续性展示 provenance', async () => {
    const user = (await import('@testing-library/user-event')).default;
    render(<OpsPanel />);
    await screen.findByText(/Anna v2/);
    await user.setup().click(screen.getByRole('button', { name: '查看连续性' }));
    expect(await screen.findByText(/harbor city/)).toBeInTheDocument();
    expect(screen.getByText(/canon/)).toBeInTheDocument();
  });

  it('确认与拒绝调用 canonical 接口', async () => {
    const user = (await import('@testing-library/user-event')).default;
    render(<OpsPanel />);
    await screen.findByText(/provider_temp_unavailable/);
    const actor = user.setup();
    await actor.click(screen.getByRole('button', { name: '确认修复' }));
    expect(hoisted.confirm).toHaveBeenCalledWith('in1', true);
    await actor.click(screen.getByRole('button', { name: '拒绝' }));
    expect(hoisted.refuse).toHaveBeenCalledWith('in1');
  });
});
