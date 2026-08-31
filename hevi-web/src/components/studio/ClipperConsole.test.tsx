/**
 * ClipperConsole 回归测试 — Frontend SPEC v5.0 §1/§3
 * 智能拆条由 /production-tools 独立为二创工具页 /studio/clipper
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ClipperConsole } from './ClipperConsole';

const hoisted = vi.hoisted(() => ({
  capabilities: vi.fn().mockResolvedValue({
    capabilities: [{ id: 'production_tools', name: 'Clipper', available: true, routes: [] }],
  }),
  clipVideo: vi.fn().mockResolvedValue({
    num_clips: 2, total_duration_s: 42,
    clips: [{ title: '高光片段', category: 'highlight', score: 92, start_time: 3, end_time: 9 }],
  }),
}));

vi.mock('@/lib/api-client', () => ({
  productionApi: { capabilities: hoisted.capabilities },
  productionV2Api: { clipVideo: hoisted.clipVideo },
}));

describe('智能拆条独立页(SPEC v5.0)', () => {
  it('渲染拆条表单并提交生成高光片段', async () => {
    const user = (await import('@testing-library/user-event')).default;
    render(<ClipperConsole />);
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('智能拆条');
    expect(screen.getByLabelText('视频路径')).toBeInTheDocument();
    expect(screen.getByLabelText('提取数量')).toBeInTheDocument();
    expect(screen.getByLabelText('目标比例')).toBeInTheDocument();
    await user.type(screen.getByLabelText('视频路径'), '/path/to/long.mp4');
    await user.click(screen.getByRole('button', { name: '开始拆条' }));
    expect((await screen.findAllByText(/高光片段/)).length).toBeGreaterThanOrEqual(1);
    expect(hoisted.clipVideo).toHaveBeenCalledWith({
      video_path: '/path/to/long.mp4', max_clips: 5, aspect_ratio: '9:16',
    });
  });

  it('不再包含 Seedance 2 独立生成表单', () => {
    render(<ClipperConsole />);
    expect(screen.queryByText('Seedance 2 视频生成')).not.toBeInTheDocument();
    expect(screen.queryByText('文生视频 (Text-to-Video)')).not.toBeInTheDocument();
  });
});
