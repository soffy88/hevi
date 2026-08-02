/**
 * §6.2 UX 回归 —— 首页 → 导演控制台带参平滑跳转(§3.1/§3.2)。
 * 校验点:首页以 16:9 + 刘备角色 + 通鉴适配器跳转后,导演控制台
 * ① 立意(剧情/时长/画幅/叙事钩子)、② 角色(锁脸勾选)、⑧ 生产(执行预设)
 * 已自动填充;通鉴渠道默认国风水墨风格(§3.2 带参带入增强)。
 */
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

vi.mock('@/lib/api-client', () => ({
  directorApi: {
    plan: vi.fn(),
    render: vi.fn(),
    createEpisode: vi.fn(),
  },
  subjectApi: {
    list: vi.fn().mockResolvedValue([
      { subject_id: 'char-liubei', name: '刘备' },
      { subject_id: 'char-zhaoyun', name: '赵云' },
    ]),
    fromPhoto: vi.fn(),
  },
}));

import { prefillDirector } from '@/lib/director-prefill';
import { DirectorConsole } from './DirectorConsole';

describe('导演控制台 · 带参预填充(§6.2 flow 2)', () => {
  beforeEach(() => window.sessionStorage.clear());

  it('首页 prefill → 立意/角色/生产表单已自动填充(16:9 + 刘备 + 极速档)', async () => {
    prefillDirector({
      prompt: '长坂坡,赵云七进七出救阿斗',
      adapterMode: 'tongjian',
      duration: '5-15min',
      aspectRatio: '16:9',
      characters: ['char-liubei'],
      presetLevel: 'fast',
    });

    render(<DirectorConsole />);

    // ① 立意:剧情 + 叙事钩子(prompt 同时带进两处,§3.2 prompt → ① 立意)
    const filled = await screen.findAllByDisplayValue('长坂坡,赵云七进七出救阿斗');
    expect(filled).toHaveLength(2);
    // 时长 / 画幅
    expect(screen.getByLabelText('时长')).toHaveValue('5-15min');
    const aspect16x9 = screen.getByRole('button', { name: '横 16:9' });
    expect(aspect16x9).toHaveAttribute('data-on', 'true');
    // ② 角色:刘备已勾选锁脸
    const liubei = screen.getByLabelText(/刘备/);
    expect(liubei).toBeChecked();
    // ④ 视觉风格:通鉴渠道默认国风水墨
    expect(screen.getByLabelText('整体风格预设')).toHaveValue('国风水墨');
    // ⑧ 生产:执行预设 = 极速
    expect(screen.getByLabelText('执行预设')).toHaveValue('fast');
  });

  it('无 prefill 数据 → 表单保持默认(不误填充)', async () => {
    render(<DirectorConsole />);
    expect(screen.getByLabelText('时长')).toHaveValue('1-5min');
    expect(screen.getByLabelText('执行预设')).toHaveValue('');
  });
});
