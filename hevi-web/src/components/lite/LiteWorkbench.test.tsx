import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { LiteWorkbench } from './LiteWorkbench';

const hoisted = vi.hoisted(() => ({
  assemble: vi.fn(),
  createRun: vi.fn(),
  getRun: vi.fn(),
  patchScript: vi.fn(),
  confirm: vi.fn(),
  push: vi.fn(),
}));

vi.mock('@/lib/api-client', () => ({
  liteApi: {
    assemble: hoisted.assemble,
    createRun: hoisted.createRun,
    getRun: hoisted.getRun,
    patchScript: hoisted.patchScript,
    confirm: hoisted.confirm,
    reloop: vi.fn(),
  },
}));
vi.mock('@/lib/auth-store', () => ({ syncAuthToken: vi.fn() }));
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: hoisted.push, prefetch: vi.fn() }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  hoisted.assemble.mockResolvedValue({ task_id: 'lite-abc-1', status: 'pending', progress: 0 });
  hoisted.createRun.mockResolvedValue({
    run_id: 'run-1',
    status: 'drafting',
    topic: '波尔兹曼方程极简推导',
    progress: 5,
  });
  hoisted.getRun.mockResolvedValue({
    run_id: 'run-1',
    status: 'awaiting_confirm',
    topic: '波尔兹曼方程极简推导',
    progress: 50,
    draft: {
      topic: '波尔兹曼方程极简推导',
      title: '波尔兹曼',
      hook: '钩子',
      cues: [
        { index: 0, narration: '先别背公式，抓住概率流。' },
        { index: 1, narration: '中段讲清碰撞项在做什么。' },
        { index: 2, narration: '所以记住：方程是守恒的语言。' },
      ],
    },
    loop: {
      draft: {
        topic: '波尔兹曼方程极简推导',
        title: '波尔兹曼',
        hook: '钩子',
        cues: [],
      },
      passed: true,
      rounds: 1,
      verdicts: [
        {
          passed: true,
          score: 0.9,
          issues: [],
          summary: 'ok',
          round: 0,
          source: 'deterministic',
        },
      ],
      decision_trail: [],
    },
  });
  hoisted.confirm.mockResolvedValue({
    run_id: 'run-1',
    status: 'rendering',
    topic: '波尔兹曼方程极简推导',
    progress: 60,
    task_id: 'task-9',
  });
});

describe('LiteWorkbench', () => {
  it('选题模式: 创建 run 触发 createRun', async () => {
    const user = userEvent.setup();
    render(<LiteWorkbench />);
    await user.type(screen.getByLabelText(/选题 Topic/), '波尔兹曼方程极简推导');
    await user.click(screen.getByRole('button', { name: /出文案并 veya 审核/ }));
    await waitFor(() => expect(hoisted.createRun).toHaveBeenCalledTimes(1));
    const payload = hoisted.createRun.mock.calls[0][0];
    expect(payload.topic).toBe('波尔兹曼方程极简推导');
    expect(payload.target_cues).toBe(5);
  });

  it('手写直出: 切换 tab 后 assemble 并跳转大盘', async () => {
    const user = userEvent.setup();
    render(<LiteWorkbench />);
    await user.click(screen.getByRole('tab', { name: /手写旁白直出/ }));
    await user.type(screen.getByLabelText(/选题 Topic/), '波尔兹曼方程极简推导');
    await user.click(screen.getByRole('button', { name: /跳过审稿，直接生成/ }));
    await waitFor(() => expect(hoisted.assemble).toHaveBeenCalledTimes(1));
    expect(hoisted.push).toHaveBeenCalledWith('/dashboard?task=lite-abc-1');
  });

  it('空主题 → 前端拦截, 不提交', async () => {
    const user = userEvent.setup();
    render(<LiteWorkbench />);
    await user.click(screen.getByRole('button', { name: /出文案并 veya 审核/ }));
    expect(hoisted.createRun).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toBeTruthy();
  });
});
