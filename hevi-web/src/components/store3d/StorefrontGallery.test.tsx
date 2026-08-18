/**
 * StorefrontGallery 组件测试:数据加载 / 空货架 / 详情浮层 / 播放浮层。
 * 3D 场景被 mock 成"触发 onSelect 的按钮",从而端到端验证 DOM 交互链路;
 * 真实 three 渲染由浏览器冒烟覆盖。
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { Episode, GalleryItem, Series } from '@/types/api';
import { StorefrontGallery } from './StorefrontGallery';
import { isVideoUrl } from './PlaybackOverlay';

const hoisted = vi.hoisted(() => {
  const TAPE: GalleryItem = {
    item_id: 't1',
    category: 'long_video',
    title: '宇宙的尺度',
    description: '从地球到可观测宇宙的震撼之旅',
    prompt: '科普长片',
    media_url: 'https://cdn.example.com/space.mp4',
    thumbnail_url: 'https://cdn.example.com/space.jpg',
    gen_params: { category: 'long_video' },
  };
  return {
    TAPE,
    pickItem: TAPE,
    galleryList: vi.fn(),
    seriesList: vi.fn(),
    seriesEpisodes: vi.fn(),
  };
});

vi.mock('@/lib/api-client', () => ({
  galleryApi: { list: hoisted.galleryList, create: vi.fn() },
  seriesApi: { list: hoisted.seriesList, episodes: hoisted.seriesEpisodes },
  USE_MOCK: false,
}));

// mock 3D 场景:渲染一个按钮,点击即调用 onSelect(等价于用户点击货架上的盒子);
// 同时透出 mode 供断言模式切换。
vi.mock('./StorefrontScene', () => ({
  StorefrontScene: ({
    onSelect,
    mode,
  }: {
    onSelect: (item: GalleryItem) => void;
    mode: string;
  }) => (
    <div data-testid="store-scene-mock">
      <span data-testid="scene-mode">{mode}</span>
      <button onClick={() => onSelect(hoisted.pickItem)}>mock 点选盒子</button>
    </div>
  ),
}));

describe('StorefrontGallery 3D 店面', () => {
  it('加载失败展示错误文案', async () => {
    hoisted.galleryList.mockRejectedValue(new Error('boom'));
    hoisted.seriesList.mockResolvedValue([]);
    render(<StorefrontGallery />);
    expect(await screen.findByText(/作品加载失败/)).toBeInTheDocument();
  });

  it('空货架展示空态文案', async () => {
    hoisted.galleryList.mockResolvedValue([]);
    hoisted.seriesList.mockResolvedValue([]);
    render(<StorefrontGallery />);
    expect(await screen.findByText(/货架空空如也/)).toBeInTheDocument();
  });

  it('有数据时渲染 3D 场景与操作提示', async () => {
    hoisted.galleryList.mockResolvedValue([hoisted.TAPE]);
    hoisted.seriesList.mockResolvedValue([]);
    render(<StorefrontGallery />);
    expect(await screen.findByTestId('store-scene-mock')).toBeInTheDocument();
    expect(screen.getByText(/点选录像带查看作品/)).toBeInTheDocument();
    expect(screen.getByTestId('scene-mode')).toHaveTextContent('orbit');
  });

  it('Series 剧集并入货架并计入统计', async () => {
    const series: Series = { id: 's1', name: '边境缉凶', style_preset: '赛博犯罪' };
    const ep: Episode = {
      id: 'task-9',
      status: 'completed',
      episode_index: 1,
      topic: '雨夜追车',
      result_video_path: '/data/media/out.mp4',
    };
    hoisted.galleryList.mockResolvedValue([hoisted.TAPE]);
    hoisted.seriesList.mockResolvedValue([series]);
    hoisted.seriesEpisodes.mockResolvedValue([ep]);
    render(<StorefrontGallery />);
    await screen.findByTestId('store-scene-mock');
    expect(screen.getByTestId('store-stat')).toHaveTextContent('货架 2 部作品');
    expect(screen.getByTestId('store-stat')).toHaveTextContent('含 1 部剧集');
  });

  it('Series 接口失败时静默跳过,不阻塞货架', async () => {
    hoisted.galleryList.mockResolvedValue([hoisted.TAPE]);
    hoisted.seriesList.mockRejectedValue(new Error('401'));
    render(<StorefrontGallery />);
    await screen.findByTestId('store-scene-mock');
    expect(screen.getByTestId('store-stat')).toHaveTextContent('货架 1 部作品');
    expect(screen.getByTestId('store-stat')).not.toHaveTextContent('剧集');
  });

  it('模式切换:行走/2.5D 透传 scene 并显示提示', async () => {
    const user = userEvent.setup();
    hoisted.galleryList.mockResolvedValue([hoisted.TAPE]);
    hoisted.seriesList.mockResolvedValue([]);
    render(<StorefrontGallery />);
    await screen.findByTestId('store-scene-mock');

    await user.click(screen.getByRole('button', { name: /行走/ }));
    expect(screen.getByTestId('scene-mode')).toHaveTextContent('walk');
    expect(screen.getByText(/点击画面进入行走/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /2\.5D/ }));
    expect(screen.getByTestId('scene-mode')).toHaveTextContent('25d');
    expect(screen.getByText(/固定机位/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /浏览/ }));
    expect(screen.getByTestId('scene-mode')).toHaveTextContent('orbit');
  });

  it('主题按钮循环切换(auto → 各主题 → auto)', async () => {
    const user = userEvent.setup();
    hoisted.galleryList.mockResolvedValue([hoisted.TAPE]);
    hoisted.seriesList.mockResolvedValue([]);
    render(<StorefrontGallery />);
    await screen.findByTestId('store-scene-mock');
    expect(screen.getByRole('button', { name: /自动主题/ })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /自动主题/ }));
    expect(screen.getByRole('button', { name: /九十年代/ })).toBeInTheDocument();
  });

  it('点选盒子 → 详情浮层 → 播放浮层全链路', async () => {
    const user = userEvent.setup();
    hoisted.galleryList.mockResolvedValue([hoisted.TAPE]);
    hoisted.seriesList.mockResolvedValue([]);
    render(<StorefrontGallery />);
    await screen.findByTestId('store-scene-mock');

    // 初始无浮层
    expect(screen.queryByRole('dialog', { name: /作品详情/ })).not.toBeInTheDocument();

    // 点选盒子 → 详情浮层出现,含标题/分区/描述
    await user.click(screen.getByRole('button', { name: 'mock 点选盒子' }));
    const detail = await screen.findByRole('dialog', { name: /作品详情:宇宙的尺度/ });
    expect(detail).toHaveTextContent('长视频');
    expect(detail).toHaveTextContent('从地球到可观测宇宙的震撼之旅');

    // 点播放 → 播放浮层出现(video)
    await user.click(screen.getByRole('button', { name: /播放/ }));
    const play = await screen.findByRole('dialog', { name: /播放:宇宙的尺度/ });
    expect(play.querySelector('video')).not.toBeNull();
    expect(play.querySelector('video')?.getAttribute('src')).toBe('https://cdn.example.com/space.mp4');

    // 关闭播放浮层
    await user.click(screen.getByRole('button', { name: '关闭播放' }));
    await screen.findByText(/点选录像带查看作品/);
    expect(screen.queryByRole('dialog', { name: /播放:/ })).not.toBeInTheDocument();
  });

  it('无 media_url 的作品详情不显示播放按钮', async () => {
    const user = userEvent.setup();
    const noMedia = { ...hoisted.TAPE, item_id: 't2', media_url: undefined };
    hoisted.pickItem = noMedia;
    hoisted.galleryList.mockResolvedValue([noMedia]);
    hoisted.seriesList.mockResolvedValue([]);
    render(<StorefrontGallery />);
    await screen.findByTestId('store-scene-mock');
    await user.click(screen.getByRole('button', { name: 'mock 点选盒子' }));
    await screen.findByRole('dialog', { name: /作品详情:宇宙的尺度/ });
    expect(screen.queryByRole('button', { name: /播放/ })).not.toBeInTheDocument();
  });
});

describe('isVideoUrl 播放类型判定', () => {
  it('视频扩展名(含查询串)判为视频,其余判为图片', () => {
    expect(isVideoUrl('https://x.com/a.mp4')).toBe(true);
    expect(isVideoUrl('https://x.com/v.webm?token=1')).toBe(true);
    expect(isVideoUrl('https://x.com/a.m3u8')).toBe(true);
    expect(isVideoUrl('https://x.com/a.jpg')).toBe(false);
    expect(isVideoUrl('https://x.com/poster.png')).toBe(false);
  });
});
