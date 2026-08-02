/**
 * ShowcaseWall 回归测试 — Frontend SPEC v5.0 §2.2
 * /gallery 接收素材搜索能力:云端素材检索(Pexels/Pixabay/Videvo)切签
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ShowcaseWall } from './ShowcaseWall';

const hoisted = vi.hoisted(() => ({
  galleryList: vi.fn().mockResolvedValue([]),
  stockSearch: vi.fn().mockResolvedValue({
    clips: [{ title: 'sunset beach', provider: 'pexels', duration_s: 8, url: 'https://x/v.mp4' }],
  }),
}));

vi.mock('@/lib/api-client', () => ({
  galleryApi: { list: hoisted.galleryList, create: vi.fn() },
  proStudioApi: { stockSearch: hoisted.stockSearch },
  USE_MOCK: false,
}));

describe('数字资产 /gallery 素材搜索(SPEC v5.0 §2.2)', () => {
  it('提供云端素材检索切签并按关键词检索', async () => {
    const user = (await import('@testing-library/user-event')).default;
    render(<ShowcaseWall />);
    expect(screen.getByRole('button', { name: '🔍 云端素材检索' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '🔍 云端素材检索' }));
    const input = screen.getByPlaceholderText(/关键词 \/ 风格包/);
    await user.type(input, 'sunset');
    await user.click(screen.getByRole('button', { name: '🔍 检索' }));
    expect(await screen.findByText(/sunset beach/)).toBeInTheDocument();
    expect(hoisted.stockSearch).toHaveBeenCalledWith({ query: 'sunset', provider: 'pexels' });
  });
});
