/**
 * PresenterLibrary 回归测试 — Frontend SPEC v5.0 §2.3
 * 数字人页面新增应用模式:卡片1 出镜视频渲染 / 卡片2 实时数字人直播
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { PresenterLibrary } from './PresenterLibrary';

const hoisted = vi.hoisted(() => ({
  isAuthed: vi.fn().mockReturnValue(true),
  presenterList: vi.fn().mockResolvedValue([
    { id: 'p1', name: '晓言', performance: 'presenter', motion: 'talking_head', lipsync: 'none', subject_id: null, voice_profile_id: null, delivery: {}, description: '主播' },
  ]),
  livestreamCapabilities: vi.fn().mockResolvedValue({ can_start: true, provider: 'rtmp', message: '就绪', setup: null }),
  livestreamStart: vi.fn().mockResolvedValue({ session_id: 's1', status: 'started', stream_url: 'rtmp://x' }),
  livestreamStop: vi.fn().mockResolvedValue({ status: 'stopped' }),
}));

vi.mock('@/lib/auth-store', () => ({ isAuthenticated: () => hoisted.isAuthed() }));
vi.mock('@/lib/api-client', () => ({
  presenterApi: {
    list: hoisted.presenterList,
    create: vi.fn(), update: vi.fn(), test: vi.fn(),
  },
  proStudioApi: {
    livestreamCapabilities: hoisted.livestreamCapabilities,
    livestreamStart: hoisted.livestreamStart,
    livestreamStop: hoisted.livestreamStop,
  },
}));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

describe('数字人应用模式(SPEC v5.0 §2.3)', () => {
  it('渲染应用模式:出镜视频渲染卡片 + 实时数字人直播卡片', async () => {
    render(<PresenterLibrary />);
    expect(await screen.findByText('应用模式')).toBeInTheDocument();
    expect(screen.getByText('出镜视频渲染 (Video Render)')).toBeInTheDocument();
    expect(screen.getByText('实时数字人直播 (Livestreaming)')).toBeInTheDocument();
    // 直播配置:推流地址 / 互动脚本 / 直播预检
    expect(screen.getByText('推流地址 (stream_url, 可选)')).toBeInTheDocument();
    expect(screen.getByText('互动脚本')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '▶ 直播预检并开播' })).toBeInTheDocument();
    // 渲染跳转入口
    expect(screen.getByRole('button', { name: /去解说中心使用/ })).toBeInTheDocument();
  });

  it('启动直播会话', async () => {
    const user = (await import('@testing-library/user-event')).default;
    render(<PresenterLibrary />);
    expect((await screen.findAllByText('晓言')).length).toBeGreaterThanOrEqual(1);
    await user.selectOptions(screen.getByLabelText('数字人预设'), 'p1');
    const script = screen.getByPlaceholderText(/开场白、互动话术/);
    await user.type(script, '欢迎来到直播间');
    await user.click(screen.getByRole('button', { name: '▶ 直播预检并开播' }));
    expect(await screen.findByText(/直播会话已启动: s1/)).toBeInTheDocument();
    expect(hoisted.livestreamStart).toHaveBeenCalledWith({
      presenter_id: 'p1', scene: undefined, script: '欢迎来到直播间',
    });
  });
});
