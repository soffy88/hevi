/**
 * TongjianConsole 回归测试 — Frontend SPEC v4.0 §2.1「我在历史现场」
 * 主题重塑 + 演绎模式配置(演绎比例/视觉风格/讲解人/史实红线) + 出片规格 + 启动按钮
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { TongjianConsole } from './TongjianConsole';

const hoisted = vi.hoisted(() => ({
  startRun: vi.fn().mockResolvedValue({ run_id: 'run-abc', status: 'PENDING' }),
  listRuns: vi.fn().mockResolvedValue([]),
  getStatus: vi.fn().mockResolvedValue({ status: 'PENDING' }),
  videoUrl: vi.fn((id: string) => `/api/tongjian/runs/${id}/video`),
}));

vi.mock('@/lib/api-client', () => ({
  tongjianApi: {
    startRun: hoisted.startRun,
    listRuns: hoisted.listRuns,
    getStatus: hoisted.getStatus,
    videoUrl: hoisted.videoUrl,
  },
}));

vi.mock('@/lib/auth-store', () => ({ syncAuthToken: () => {} }));
vi.mock('./ScriptReviewPanel', () => ({ ScriptReviewPanel: () => null }));

describe('通鉴 · 【我在历史现场】(SPEC v4.0 §2.1)', () => {
  it('主题重塑:标题/讲解+演绎定位/L0-L8 徽标/重建历史现场按钮', async () => {
    render(<TongjianConsole />);
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('我在历史现场');
    expect(screen.getByText(/讲解（分析\/铺垫）\+ 现场高潮演绎/)).toBeInTheDocument();
    // 九层流水线徽标
    expect(screen.getByText('L0 史料')).toBeInTheDocument();
    expect(screen.getByText('L2 剧本')).toBeInTheDocument();
    expect(screen.getByText('L6 画面')).toBeInTheDocument();
    expect(screen.getByText('成片')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /重建历史现场/ })).toBeInTheDocument();
  });

  it('演绎模式配置:演绎比例三档 + 视觉风格四档 + 讲解人 + 史实红线默认开启', () => {
    render(<TongjianConsole />);
    expect(screen.getByText(/均衡 · 讲解70% \+ 现场演绎30%（默认）/)).toBeInTheDocument();
    expect(screen.getByText('🧸 儿童卡通动画（默认）')).toBeInTheDocument();
    expect(screen.getByText('🎨 国风水墨')).toBeInTheDocument();
    expect(screen.getByText('🎬 拟真电影感')).toBeInTheDocument();
    expect(screen.getByText('🖌️ 连环画/工笔')).toBeInTheDocument();
    expect(screen.getByText('📜 历史旁白·老张')).toBeInTheDocument();
    expect(screen.getByText('🎙️ 数字人出镜')).toBeInTheDocument();
    // 史实红线显式开关(默认勾选)
    const redline = screen.getByRole('checkbox', { name: /严格开启 CG2.5 台词出处校验/ });
    expect(redline).toBeChecked();
  });

  it('出片规格:16:9 横屏纪录片式默认 + 画质 1080P 默认', () => {
    render(<TongjianConsole />);
    const ar = screen.getByRole('button', { name: '16:9 横屏（纪录片式）' });
    expect(ar).toHaveAttribute('data-on', 'true');
    const res = screen.getByRole('button', { name: '1080P' });
    expect(res).toHaveAttribute('data-on', 'true');
  });
});
