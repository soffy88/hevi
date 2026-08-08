import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TaskDashboard } from './TaskDashboard';

const hoisted = vi.hoisted(() => {
  const state = {
    listTasks: vi.fn(),
    getTask: vi.fn(),
    outputUrl: vi.fn(),
    // WS 状态融合 mock: seedTasks 写入、tasks 实时可读(函数引用稳定, 避免 effect 循环)。
    tasks: [] as Array<Record<string, unknown>>,
    seedTasks: vi.fn((next: Array<Record<string, unknown>>) => { state.tasks = next; }),
    appendTasks: vi.fn((older: Array<Record<string, unknown>>) => {
      state.tasks = [...state.tasks, ...older];
    }),
  };
  return state;
});

vi.mock('@/lib/api-client', () => ({
  dashboardApi: {
    listTasks: hoisted.listTasks,
    getTask: hoisted.getTask,
    outputUrl: hoisted.outputUrl,
  },
}));

vi.mock('@/lib/auth-store', () => ({ syncAuthToken: vi.fn() }));
vi.mock('@/hooks/useTaskWebSocket', () => ({
  useTaskWebSocket: () => ({
    connected: true,
    reconnecting: false,
    updates: {},
    lastError: null,
    tasks: hoisted.tasks,
    seedTasks: hoisted.seedTasks,
    appendTasks: hoisted.appendTasks,
  }),
}));

function makeTasks() {
  return {
    total: 3,
    limit: 20,
    offset: 0,
    status_counts: { running: 1, completed: 1 },
    items: [
      {
        id: 1,
        task_id: 'task-running-1',
        pipeline_type: 'main_remotion',
        status: 'running',
        progress: 42,
        error_log: null,
        state_json: { tts_status: 'done' },
        created_at: '2025-08-04T04:00:00Z',
        updated_at: '2025-08-04T04:01:00Z',
      },
      {
        id: 2,
        task_id: 'task-done-2',
        pipeline_type: 'lite_html',
        status: 'completed',
        progress: 100,
        error_log: null,
        result_video_path: '/tmp/x/portrait.mp4',
        state_json: { html_status: 'done', screen_capture_status: 'done' },
        created_at: '2025-08-03T04:00:00Z',
        updated_at: '2025-08-03T04:02:00Z',
      },
    ],
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  hoisted.tasks = [];
  hoisted.outputUrl.mockReturnValue('http://test/api/dashboard/tasks/task-done-2/output');
  hoisted.listTasks.mockResolvedValue(makeTasks());
});

describe('TaskDashboard', () => {
  it('加载并渲染任务列表(统计卡片 + 状态徽标 + 进度条 + step 芯片)', async () => {
    render(<TaskDashboard />);
    expect(await screen.findByText(/task-runni/)).toBeTruthy();
    expect(screen.getByText(/task-done-/)).toBeTruthy();
    // 顶部统计卡片:全部 / 进行中 / 已完成 / 失败。
    expect(screen.getByText('全部任务')).toBeTruthy();
    expect(screen.getAllByText('进行中').length).toBeGreaterThan(0);
    expect(screen.getByText('tts_status ✓')).toBeTruthy();
    expect(screen.getByText('html_status ✓')).toBeTruthy();
    // 已完成行提供预览/下载操作。
    expect(screen.getByRole('button', { name: '预览' })).toBeTruthy();
    expect(screen.getByRole('link', { name: '下载' })).toHaveProperty('href');
    expect(hoisted.listTasks).toHaveBeenCalledWith({ limit: 20, offset: 0 });
  });

  it('点击预览打开沉浸式放映室(原生 video 播放成片)', async () => {
    const user = userEvent.setup();
    render(<TaskDashboard />);
    await screen.findByText(/task-runni/);
    await user.click(screen.getByRole('button', { name: '预览' }));
    // 深色遮罩弹窗 + 内嵌 <video src=outputUrl>。
    expect(screen.getByRole('dialog', { name: /task-done-2 成片预览/ })).toBeTruthy();
    const video = document.querySelector('video.vmodal__video') as HTMLVideoElement | null;
    expect(video).not.toBeNull();
    expect(video?.getAttribute('src')).toContain('/api/dashboard/tasks/task-done-2/output');
    // ESC / 关闭按钮可关闭。
    await user.click(screen.getByRole('button', { name: '关闭预览' }));
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('状态过滤为客户端筛选:点「已完成」只剩完成行,不重新拉取 REST', async () => {
    const user = userEvent.setup();
    render(<TaskDashboard />);
    await screen.findByText(/task-runni/);
    await user.click(screen.getAllByRole('tab', { name: /已完成/ })[0]);
    expect(screen.queryByText(/task-runni/)).toBeNull();
    expect(screen.getByText(/task-done-/)).toBeTruthy();
    expect(hoisted.listTasks).toHaveBeenCalledTimes(1);
  });

  it('列表为空时展示引导文案', async () => {
    hoisted.listTasks.mockResolvedValue({ total: 0, limit: 20, offset: 0, items: [] });
    render(<TaskDashboard />);
    expect(await screen.findByText(/还没有生成任务/)).toBeTruthy();
  });

  it('加载更多把更早分页追加到队尾(去重)', async () => {
    const user = userEvent.setup();
    hoisted.listTasks
      .mockResolvedValueOnce(makeTasks())
      .mockResolvedValueOnce({
        total: 3, limit: 20, offset: 2,
        items: [{ id: 3, task_id: 'task-old-3', pipeline_type: 'main_remotion', status: 'completed', progress: 100, error_log: null, state_json: null, created_at: '2025-08-02T00:00:00Z', updated_at: '2025-08-02T00:00:00Z' }],
      });
    render(<TaskDashboard />);
    await screen.findByText(/task-runni/);
    await user.click(screen.getByRole('button', { name: /加载更早任务/ }));
    await waitFor(() => expect(screen.getByText(/task-old-3/)).toBeTruthy());
    expect(hoisted.listTasks).toHaveBeenLastCalledWith({ limit: 20, offset: 2 });
  });
});
