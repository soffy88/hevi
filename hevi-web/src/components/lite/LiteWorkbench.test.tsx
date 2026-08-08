import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { LiteWorkbench } from './LiteWorkbench';

const hoisted = vi.hoisted(() => ({
  assemble: vi.fn(),
  push: vi.fn(),
}));

vi.mock('@/lib/api-client', () => ({ liteApi: { assemble: hoisted.assemble } }));
vi.mock('@/lib/auth-store', () => ({ syncAuthToken: vi.fn() }));
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: hoisted.push, prefetch: vi.fn() }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  hoisted.assemble.mockResolvedValue({ task_id: 'lite-abc-1', status: 'pending', progress: 0 });
});

describe('LiteWorkbench', () => {
  it('多行文案按换行拆分为 cues(空行忽略, 自动编号)', async () => {
    render(<LiteWorkbench />);
    // 默认 4 行示例 → 4 个镜头预览。
    expect(document.querySelectorAll('.lite__cue').length).toBe(4);
    expect(document.querySelector('.lite__hint')?.textContent).toContain('4 个镜头');

    const textarea = screen.getByLabelText(/旁白文案/) as HTMLTextAreaElement;
    await userEvent.clear(textarea);
    await userEvent.type(textarea, '第一句\n\n第二句\n第三句');
    expect(document.querySelector('.lite__hint')?.textContent).toContain('3 个镜头');
    expect(screen.getByText('第二句')).toBeTruthy();
  });

  it('提交: POST /api/lite/assemble 带 topic+cues → 202 后跳转大盘', async () => {
    const user = userEvent.setup();
    render(<LiteWorkbench />);

    await user.type(screen.getByLabelText(/主题 Topic/), '波尔兹曼方程极简推导');
    await user.click(screen.getByRole('button', { name: /生成视频/ }));

    await waitFor(() => expect(hoisted.assemble).toHaveBeenCalledTimes(1));
    const payload = hoisted.assemble.mock.calls[0][0];
    expect(payload.topic).toBe('波尔兹曼方程极简推导');
    expect(payload.cues.length).toBe(4);
    expect(payload.cues[0]).toEqual({ index: 0, narration: '今天我们用三分钟，彻底讲清一个概念。' });
    expect(payload.cues[3].index).toBe(3);
    expect(hoisted.push).toHaveBeenCalledWith('/dashboard?task=lite-abc-1');
  });

  it('空主题 → 前端拦截, 不提交', async () => {
    const user = userEvent.setup();
    render(<LiteWorkbench />);
    await user.click(screen.getByRole('button', { name: /生成视频/ }));
    expect(hoisted.assemble).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toBeTruthy();
  });
});
