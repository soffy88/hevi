/**
 * 配方卡桥接回归测试 — recipe-card-bridge 纯函数 + DirectorConsole 消费横幅
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { ShotRecipeCard } from '@/types/embrace';
import {
  consumePickedCard,
  recipeCardToDirectorHints,
  storePickedCard,
} from '@/lib/recipe-card-bridge';

const CARD: ShotRecipeCard = {
  name: 'orbit-closeup',
  category: 'camera',
  purpose: '物件特写四件套:侧面倾斜角+可感知高度+orbit 环绕',
  energy: 'medium',
  suggested_duration_s: 2.4,
  params: { orbit: 360 },
  implementation_notes: '',
  known_pitfalls: ['无体积高度的堆叠'],
  demo_ref: '',
};

const OPENING: ShotRecipeCard = {
  ...CARD,
  name: 'spotlight-hero-card',
  category: 'opening',
  suggested_duration_s: 3.0,
  params: { hold_s: 1.0 },
  known_pitfalls: [],
};

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock('@/lib/api-client', () => ({
  directorApi: { plan: vi.fn(), render: vi.fn(), createEpisode: vi.fn() },
  subjectApi: { list: vi.fn().mockResolvedValue([]), fromPhoto: vi.fn() },
}));

describe('recipe-card-bridge 纯函数', () => {
  it('camera 卡 → prompt_camera;opening 卡 → prompt_style', () => {
    const cam = recipeCardToDirectorHints(CARD);
    expect(cam.prompt_camera).toContain('orbit');
    expect(cam.prompt_camera).toContain('360');
    expect(cam.note).toContain('单镜 2.4s'); // 单镜时长只进 note,不进剧集时长

    const op = recipeCardToDirectorHints(OPENING);
    expect(op.prompt_style).toContain('hold 1s');
    expect(op.note).toContain('单镜 3s');
  });

  it('store/consume 往返(sessionStorage 单次消费)', () => {
    window.sessionStorage.clear();
    storePickedCard(CARD);
    const got = consumePickedCard();
    expect(got?.name).toBe('orbit-closeup');
    expect(consumePickedCard()).toBeNull(); // 已消费
  });
});

describe('DirectorConsole · 配方卡导入(3O 内化 wire)', () => {
  beforeEach(() => window.sessionStorage.clear());

  it('消费配方卡 → 应用提示字段 + 显示横幅', async () => {
    const { DirectorConsole } = await import('@/components/director/DirectorConsole');
    storePickedCard(CARD);
    render(<DirectorConsole />);
    // 横幅展示卡名
    expect(await screen.findByText(/已应用配方卡/)).toBeInTheDocument();
    expect(screen.getByText(/orbit-closeup/)).toBeInTheDocument();
    // 清除按钮存在
    expect(screen.getByRole('button', { name: /清除/ })).toBeInTheDocument();
  });

  it('无配方卡时不显示横幅', async () => {
    const { DirectorConsole } = await import('@/components/director/DirectorConsole');
    render(<DirectorConsole />);
    expect(screen.queryByText(/已应用配方卡/)).not.toBeInTheDocument();
  });
});
