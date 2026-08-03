import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ExplainerWorkbench } from './ExplainerWorkbench';

const hoisted = vi.hoisted(() => ({
  list: vi.fn().mockResolvedValue([]),
  ensureDefault: vi.fn().mockResolvedValue({
    id: 'p-default',
    name: 'HEVI 默认解说数字人',
    performance: 'presenter',
    motion: 'picture_in_picture',
    lipsync: 'none',
    delivery: { provider: 'remotion', variant: 'generated' },
  }),
  research: vi.fn().mockResolvedValue({
    topic_or_url: '测试主题',
    research_summary: '摘要',
    facts: [],
    hooks: [{
      hook_id: 'H1',
      title: '灾难的根源',
      narrative_function: 'opening_suspense',
      suggested_placement_s: 0,
      text: '为什么经典力学在 BBGKY 方程这里彻底失效？',
      associated_concepts: ['BBGKY 方程'],
    }, {
      hook_id: 'H2',
      title: '拓扑树与重碰撞',
      narrative_function: 'mid_conflict',
      suggested_placement_s: 90,
      text: '这里的核心死结，就是这张拓扑树上的重碰撞',
      associated_concepts: ['拓扑树'],
    }, {
      hook_id: 'H3',
      title: '调和分析突破',
      narrative_function: 'climax_breakthrough',
      suggested_placement_s: 180,
      text: '而邓煜引入的调和分析，正是解开死结的钥匙',
      associated_concepts: ['调和分析'],
    }],
    hook_details: [],
    scripts: [{
      id: 'A',
      title: '版本 A',
      viewpoint: '数据',
      hook: '抓手',
      cues: [{
        time_range: '00:00-05.0s',
        visual_type: 'heygen_avatar',
        text: '数字人开场',
        time_estimate_s: 5,
      }],
    }],
    script_versions: [],
    provider: 'test',
    decision_trail: [],
  }),
  assemble: vi.fn(),
}));

vi.mock('@/lib/api-client', () => ({
  presenterApi: {
    list: hoisted.list,
    ensureDefault: hoisted.ensureDefault,
  },
  explainerApi: {
    research: hoisted.research,
    assemble: hoisted.assemble,
    researchCache: vi.fn(),
  },
  taskApi: {
    get: vi.fn(),
    videoUrl: vi.fn(),
  },
}));

vi.mock('@/lib/auth-store', () => ({ syncAuthToken: vi.fn() }));

beforeEach(() => {
  // 确稿台快照落 sessionStorage;测试间必须清空,避免串场。
  window.sessionStorage.clear();
  vi.clearAllMocks();
});

/** 走到确稿台(阶段二):输入主题→启动联网调研→等待 Hook 矩阵渲染。 */
async function reachReview(user: ReturnType<typeof userEvent.setup>) {
  render(<ExplainerWorkbench />);
  await user.type(screen.getByPlaceholderText(/输入一句话主题/), '邓煜突破 BBGKY 方程');
  await user.click(screen.getByRole('button', { name: /启动联网调研与脚本生成/ }));
  await screen.findByText('Hook 组合策略');
}

describe('ExplainerWorkbench presenter automation', () => {
  it('creates, selects, and exposes a default presenter in stage two', async () => {
    const user = userEvent.setup();
    render(<ExplainerWorkbench />);

    await waitFor(() => expect(hoisted.ensureDefault).toHaveBeenCalledOnce());
    expect(screen.getByRole('option', { name: 'HEVI 默认解说数字人' })).toBeInTheDocument();

    await user.type(screen.getByPlaceholderText(/输入一句话主题/), '测试主题');
    await user.click(screen.getByRole('button', { name: /启动联网调研与脚本生成/ }));

    const stageTwoSelect = await screen.findByLabelText('第二步出镜数字人');
    expect(stageTwoSelect).toHaveValue('p-default');
    expect(screen.queryByText(/请先选择数字人/)).not.toBeInTheDocument();
  });
});

describe('ExplainerWorkbench Hook 策略矩阵 (v9)', () => {
  it('renders a multi-select matrix with narrative function tags', async () => {
    const user = userEvent.setup();
    await reachReview(user);

    const checkboxes = screen.getAllByRole('checkbox', { name: /Hook/ });
    expect(checkboxes).toHaveLength(3);
    // 默认全选(链式)且展示叙事功能档位标签
    checkboxes.forEach(checkbox => expect(checkbox).toBeChecked());
    expect(screen.getByText('开场总悬念')).toBeInTheDocument();
    expect(screen.getByText('中段转折/冲突')).toBeInTheDocument();
    expect(screen.getByText('高潮解答')).toBeInTheDocument();
    expect(screen.getByText('BBGKY 方程')).toBeInTheDocument();
    // 串联导览按时间递进展示
    expect(screen.getByText(/Hook Chain Preview/)).toBeInTheDocument();
    expect(screen.getByText(/\[00:00-01:30\]/)).toBeInTheDocument();
  });

  it('supports unselecting hooks and toggling fusion mode', async () => {
    const user = userEvent.setup();
    await reachReview(user);

    const checkboxes = screen.getAllByRole('checkbox', { name: /Hook/ });
    await user.click(checkboxes[2]);
    expect(checkboxes[2]).not.toBeChecked();
    expect(screen.getByText('2/3 已选')).toBeInTheDocument();

    await user.click(screen.getByRole('radio', { name: /融合成单一开场/ }));
    expect(screen.getByText(/Fusion Preview/)).toBeInTheDocument();
    expect(screen.getByText(/浓缩为一段 30 秒的开场悬念/)).toBeInTheDocument();
  });

  it('sends selected_hooks and hook_combination to the assembly boundary', async () => {
    const user = userEvent.setup();
    await reachReview(user);

    hoisted.assemble.mockResolvedValueOnce({
      task_id: 'task-1',
      status: 'processing',
      estimated_seconds: 30,
      sse_channel: '',
      production_source: 'explainer',
      engine_version: 'v9',
      adapter_version: 'v9.0',
    });
    await user.click(screen.getByRole('button', { name: /确认文案与脚手架/ }));

    await waitFor(() => expect(hoisted.assemble).toHaveBeenCalledOnce());
    const body = hoisted.assemble.mock.calls[0][0];
    expect(body.selected_hooks).toHaveLength(3);
    expect(body.selected_hooks[0]).toContain('BBGKY 方程');
    expect(body.hook_combination).toBe('chain');
    expect(body.selected_hook).toContain('BBGKY 方程');
  });
});

describe('ExplainerWorkbench 断点续传与重试', () => {
  it('refresh 后从 sessionStorage 瞬时恢复确稿台,绝不重跑研究', async () => {
    const user = userEvent.setup();
    const first = render(<ExplainerWorkbench />);
    await user.type(screen.getByPlaceholderText(/输入一句话主题/), '邓煜突破 BBGKY 方程');
    await user.click(screen.getByRole('button', { name: /启动联网调研与脚本生成/ }));
    await screen.findByText('Hook 组合策略');
    first.unmount();

    // 模拟刷新:重新挂载(jsdom sessionStorage 保留快照),研究不再触发。
    hoisted.research.mockClear();
    render(<ExplainerWorkbench />);
    await screen.findByText('Hook 组合策略');
    await waitFor(() =>
      expect(screen.getByText('已从本地缓存恢复确稿台(无需重跑研究)')).toBeInTheDocument(),
    );
    expect(hoisted.research).not.toHaveBeenCalled();
  });

  it('阶段三装配失败时显示 [🔄 重新提交装配] 并用当前状态重发', async () => {
    const user = userEvent.setup();
    await reachReview(user);

    hoisted.assemble.mockRejectedValueOnce(new Error('网络抖动'));
    await user.click(screen.getByRole('button', { name: /确认文案与脚手架/ }));
    const retry = await screen.findByRole('button', { name: /🔄 重新提交装配/ });
    expect(screen.getByRole('alert')).toHaveTextContent('网络抖动');

    hoisted.assemble.mockResolvedValueOnce({
      task_id: 'task-2',
      status: 'processing',
      estimated_seconds: 30,
      sse_channel: '',
      production_source: 'explainer',
      engine_version: 'v9',
      adapter_version: 'v9.0',
    });
    await user.click(retry);
    await waitFor(() => expect(hoisted.assemble).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole('button', { name: /🔄 重新提交装配/ })).not.toBeInTheDocument();
  });
});
