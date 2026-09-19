/**
 * D6-D 制作问题 tests — auto-recovered, confirm gate, timeline.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ProductionIssuesPanel } from './ProductionIssuesPanel';

const hoisted = vi.hoisted(() => ({
  listProduct: vi.fn(),
  confirm: vi.fn(),
  refuse: vi.fn(),
  timeline: vi.fn(),
}));

vi.mock('@/lib/api-client', () => ({
  incidentApi: {
    listProduct: hoisted.listProduct,
    confirm: hoisted.confirm,
    refuse: hoisted.refuse,
    timeline: hoisted.timeline,
  },
}));

function incident(overrides: Record<string, unknown> = {}) {
  return {
    incident_id: 'in1',
    production_run_id: 'r1',
    node_key: 'task.run',
    status: 'open',
    root_cause: 'provider_temp_unavailable',
    failure_code: 'PROVIDER_FAILURE',
    diagnosis: 'provider temporarily unavailable',
    needs_agent: false,
    policy: 'auto_safe',
    requires_confirmation: false,
    estimated_cost_usd: 0,
    preserved_artifact_ids: [],
    preserved_intact: true,
    attempts: 0,
    verification_result: {},
    ...overrides,
  };
}

describe('制作问题', () => {
  it('AUTO_SAFE 显示已恢复', async () => {
    hoisted.listProduct.mockResolvedValue({
      incidents: [incident({ status: 'resolved', policy: 'auto_safe' })],
    });
    render(<ProductionIssuesPanel productionRunId="r1" />);
    expect(await screen.findByTestId('recovered-in1')).toHaveTextContent('HEVI 已恢复制作');
  });

  it('CONFIRM_REQUIRED 显示费用并需确认', async () => {
    hoisted.listProduct.mockResolvedValue({
      incidents: [
        incident({
          policy: 'confirm_required',
          requires_confirmation: true,
          estimated_cost_usd: 2.5,
        }),
      ],
    });
    hoisted.confirm.mockResolvedValue({});
    const user = (await import('@testing-library/user-event')).default;
    render(<ProductionIssuesPanel productionRunId="r1" />);
    expect(await screen.findByTestId('confirm-box-in1')).toBeInTheDocument();
    expect(screen.getByText(/预计新增费用 \$2.50/)).toBeInTheDocument();
    await user.setup().click(screen.getByRole('button', { name: '确认修复' }));
    expect(hoisted.confirm).toHaveBeenCalledWith('in1', true);
  });

  it('MANUAL_ONLY 提示需要处理', async () => {
    hoisted.listProduct.mockResolvedValue({
      incidents: [
        incident({ policy: 'manual_only', status: 'escalated_manual', diagnosis: '缺少素材引用' }),
      ],
    });
    render(<ProductionIssuesPanel productionRunId="r1" />);
    expect(await screen.findByTestId('manual-in1')).toHaveTextContent('需要你处理');
  });

  it('时间线展开显示人类可读标签', async () => {
    hoisted.listProduct.mockResolvedValue({ incidents: [incident()] });
    hoisted.timeline.mockResolvedValue({
      incident_id: 'in1',
      events: [
        { seq: 0, event: 'detected', at: 1, detail: 'PROVIDER_FAILURE' },
        { seq: 1, event: 'verified_resolved', at: 2, detail: 'resolved' },
      ],
    });
    const user = (await import('@testing-library/user-event')).default;
    render(<ProductionIssuesPanel productionRunId="r1" />);
    await screen.findByTestId('issue-in1');
    await user.setup().click(screen.getByRole('button', { name: '处理过程' }));
    expect(await screen.findByTestId('timeline-in1')).toHaveTextContent('发现问题');
    expect(screen.getByTestId('timeline-in1')).toHaveTextContent('已验证恢复');
  });

  it('空状态', async () => {
    hoisted.listProduct.mockResolvedValue({ incidents: [] });
    render(<ProductionIssuesPanel />);
    expect(await screen.findByTestId('issues-empty')).toBeInTheDocument();
  });
});
