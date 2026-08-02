/**
 * ExplainerConsole 回归测试 — Frontend SPEC v4.0 §2.3 解说双配方
 * short_explainer(图文解说) / digital_presenter(数字人口播) 二选一卡片
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ExplainerConsole } from './ExplainerConsole';

const hoisted = vi.hoisted(() => ({
  startRun: vi.fn().mockResolvedValue({ run_id: 'run-abc', status: 'PENDING' }),
  getStatus: vi.fn().mockResolvedValue({ status: 'PENDING' }),
  list: vi.fn().mockResolvedValue([{ id: 'p1', name: '晓言', performance: 'presenter' }]),
  generate: vi.fn().mockResolvedValue({ task_id: 'task-1', status: 'pending', percent: 5 }),
}));

vi.mock('@/lib/api-client', () => ({
  explainerApi: {
    startRun: hoisted.startRun,
    getStatus: hoisted.getStatus,
  },
  presenterApi: { list: hoisted.list },
  productionApi: { generate: hoisted.generate },
  taskApi: { get: vi.fn().mockResolvedValue({ task_id: 'task-1', status: 'pending', percent: 5 }) },
}));

vi.mock('@/lib/auth-store', () => ({ syncAuthToken: () => {} }));

describe('解说中心双配方(SPEC v4.0 §2.3)', () => {
  it('渲染双配方卡片:图文解说 + 数字人口播,默认图文解说', () => {
    render(<ExplainerConsole />);
    expect(screen.getByText(/图文解说 · short_explainer/)).toBeInTheDocument();
    expect(screen.getByText(/数字人口播 · digital_presenter/)).toBeInTheDocument();
    const short = screen.getByRole('button', { name: /图文解说 · short_explainer/ });
    expect(short).toHaveAttribute('data-on', 'true');
    expect(screen.getByText(/E0 选题→文案分镜/)).toBeInTheDocument();
  });

  it('切到数字人口播配方:显示数字人下拉 + 时长档/执行档位/画幅', async () => {
    const user = (await import('@testing-library/user-event')).default;
    render(<ExplainerConsole />);
    await user.click(screen.getByRole('button', { name: /数字人口播 · digital_presenter/ }));
    // presenterApi.list() 异步返回后渲染进下拉
    expect(await screen.findByText('晓言')).toBeInTheDocument();
    expect(screen.getByLabelText('数字人（出镜口播）')).toBeInTheDocument();
    expect(screen.getByLabelText('单集时长档')).toBeInTheDocument();
    expect(screen.getByLabelText('执行档位')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '▶ 开始数字人口播' })).toBeInTheDocument();
  });

  it('代码解说配方(SPEC v5.0 §2.4):Remotion 动态代码渲染输入区', async () => {
    const user = (await import('@testing-library/user-event')).default;
    render(<ExplainerConsole />);
    expect(screen.getByText(/代码解说 · Remotion 动态渲染/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /代码解说 · Remotion 动态渲染/ }));
    expect(screen.getByLabelText('语言')).toBeInTheDocument();
    expect(screen.getByLabelText('讲解深度')).toBeInTheDocument();
    expect(screen.getByLabelText(/代码片段/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '▶ 生成代码解说视频' })).toBeInTheDocument();
    // Agent 编排底座
    expect(screen.getByText(/Agent 编排底座/)).toBeInTheDocument();
  });
});
