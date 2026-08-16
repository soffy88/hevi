/**
 * EmbraceGallery 回归测试 — 3O 内化画廊
 * 数据源为静态 JSON(public/embrace/*.json),mock 全局 fetch 返回样例。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { EmbraceGallery } from './EmbraceGallery';

const pushMock = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: pushMock }) }));

const CARD = {
  name: 'spotlight-hero-card',
  category: 'opening',
  purpose: '开场单主角完整动作弧:聚光→推近→悬浮→归位',
  energy: 'high',
  suggested_duration_s: 3.0,
  params: { hold_s: 1.0, arc: 'focus-float-settle' },
  implementation_notes: '单卡结构定型后不要再动',
  known_pitfalls: ['多元素并舞撑不起开场', '弧线未收尾就切镜'],
  demo_ref: 'template/src/aifl/live/HeroCard.tsx',
};

const RULE = {
  code: 'R1',
  rule: '关键信息落定后必须呼吸:静止 ≥1s 再切镜',
  precedent: '用户:"第一个标题打出来之后停留一秒"。',
  self_check: '每个"想让观众记住的画面"是否有完整静止时刻?',
  allow_violation: false,
};

const FAILURE = {
  code: 'bad_hands',
  layer: 'action',
  description: '手部畸形/多余手指',
  negative_clause: '手部结构正常,五根手指,无畸形无多指',
  keywords: ['手', '手指'],
};

function mockFetch() {
  vi.stubGlobal('fetch', vi.fn(async (url: RequestInfo | URL) => {
    const u = String(url);
    const body = u.includes('cards.json') ? [CARD]
      : u.includes('canon.json') ? [RULE]
      : u.includes('failure_modes.json') ? [FAILURE]
      : [];
    return {
      ok: true,
      status: 200,
      json: async () => body,
    } as Response;
  }));
}

beforeEach(() => { mockFetch(); });

describe('EmbraceGallery 3O 内化画廊', () => {
  it('渲染三切签并默认展示镜头配方卡', async () => {
    render(<EmbraceGallery />);
    expect(await screen.findByText('🎴 镜头配方卡')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '📜 审美准则' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '🩹 失败模式' })).toBeInTheDocument();
    // 卡片数据渲染
    expect(await screen.findByText('spotlight-hero-card')).toBeInTheDocument();
    expect(screen.getByText(/开场单主角完整动作弧/)).toBeInTheDocument();
  });

  it('展开卡片详情展示参数与已知坑', async () => {
    const user = (await import('@testing-library/user-event')).default;
    render(<EmbraceGallery />);
    const cardName = await screen.findByText('spotlight-hero-card');
    await user.click(cardName);
    expect(screen.getByText(/hold_s/)).toBeInTheDocument();
    expect(screen.getByText(/弧线未收尾就切镜/)).toBeInTheDocument();
    expect(screen.getByText(/单卡结构定型后不要再动/)).toBeInTheDocument();
  });

  it('切到审美准则显示判例与自检', async () => {
    const user = (await import('@testing-library/user-event')).default;
    render(<EmbraceGallery />);
    await user.click(await screen.findByRole('button', { name: '📜 审美准则' }));
    expect(await screen.findByText('R1')).toBeInTheDocument();
    expect(screen.getByText(/判例:/)).toBeInTheDocument();
    expect(screen.getByText(/自检:/)).toBeInTheDocument();
  });

  it('切到失败模式显示负向子句', async () => {
    const user = (await import('@testing-library/user-event')).default;
    render(<EmbraceGallery />);
    await user.click(await screen.findByRole('button', { name: '🩹 失败模式' }));
    expect(await screen.findByText('bad_hands')).toBeInTheDocument();
    expect(screen.getByText(/负向子句: 手部结构正常/)).toBeInTheDocument();
  });

  it('搜索过滤卡片', async () => {
    const user = (await import('@testing-library/user-event')).default;
    render(<EmbraceGallery />);
    await screen.findByText('spotlight-hero-card');
    const input = screen.getByPlaceholderText(/搜索卡名/);
    await user.type(input, '不存在的卡');
    expect(screen.queryByText('spotlight-hero-card')).not.toBeInTheDocument();
    expect(screen.getByText(/没有匹配的卡/)).toBeInTheDocument();
  });

  it('「用此卡出片」暂存卡并跳转导演台', async () => {
    const user = (await import('@testing-library/user-event')).default;
    render(<EmbraceGallery />);
    const btn = await screen.findByRole('button', { name: '🎬 用此卡出片' });
    await user.click(btn);
    const raw = window.sessionStorage.getItem('hevi.recipe-card.pick.v1');
    expect(raw).not.toBeNull();
    expect(JSON.parse(raw as string).name).toBe('spotlight-hero-card');
    expect(pushMock).toHaveBeenCalledWith('/director');
  });
});
