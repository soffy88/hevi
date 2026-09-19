/**
 * D6-E/F 制作状态 + Quick Start tests.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ProjectHealthPanel } from './ProjectHealthPanel';
import { QuickStart } from '@/components/onboarding/QuickStart';

const hoisted = vi.hoisted(() => ({
  projectHealth: vi.fn(),
  create: vi.fn(),
}));

vi.mock('@/lib/api-client', () => ({
  productApi: { projectHealth: hoisted.projectHealth },
  identityApi: { create: hoisted.create },
}));

describe('制作状态', () => {
  it('渲染服务端状态与下一步动作', async () => {
    hoisted.projectHealth.mockResolvedValue({
      project_id: 'p',
      status: 'NEEDS_ATTENTION',
      task_status: 'completed',
      currency: { available: true, counts: { stale: 1 }, stale: 1 },
      continuity: null,
      incidents: [],
      next_action: { kind: 'review', label: '处理问题' },
    });
    render(<ProjectHealthPanel projectId="p" />);
    expect(await screen.findByTestId('project-health')).toHaveAttribute('data-status', 'NEEDS_ATTENTION');
    expect(screen.getByTestId('health-next-action')).toHaveTextContent('处理问题');
    expect(screen.getByTestId('health-stale')).toHaveTextContent('1');
  });

  it('不自行推断状态（直接渲染服务端值）', async () => {
    hoisted.projectHealth.mockResolvedValue({
      project_id: 'p',
      status: 'BLOCKED',
      task_status: 'running',
      currency: { available: false, counts: {} },
      continuity: { verdict: 'block', issues: [] },
      incidents: [],
      next_action: { kind: 'manual_fix', label: '需要你处理' },
    });
    render(<ProjectHealthPanel projectId="p" />);
    expect(await screen.findByText('已阻塞')).toBeInTheDocument();
  });
});

describe('快速开始', () => {
  it('高级选项默认折叠且非必需', () => {
    const { container } = render(<QuickStart />);
    const details = container.querySelector('details');
    expect(screen.getByText('高级选项（可选）')).toBeInTheDocument();
    expect(details).not.toBeNull();
    expect((details as HTMLDetailsElement).open).toBe(false);
  });

  it('基本输入即可创建', async () => {
    const user = (await import('@testing-library/user-event')).default;
    render(<QuickStart />);
    await user.setup().click(screen.getByRole('button', { name: '开始创建' }));
    expect(screen.getByTestId('quickstart-message')).toBeInTheDocument();
  });

  it('示例项目标记为演示', async () => {
    hoisted.create.mockResolvedValue({});
    const onDemo = vi.fn();
    const user = (await import('@testing-library/user-event')).default;
    render(<QuickStart onDemoProject={onDemo} />);
    await user.setup().click(screen.getByRole('button', { name: '示例项目' }));
    expect(screen.getByTestId('demo-badge')).toHaveTextContent('演示');
    expect(onDemo).toHaveBeenCalledWith('demo-project');
  });
});
