/**
 * Backlot 分镜联系表审批门 + REPLAY 回放 前端测试。
 *
 * fetch 打桩到后端真实契约形状, 断言三件最容易出事的地方:
 *  1. 未量测的维度不显示成一个健康的分数
 *  2. 否决没有理由时前端不发请求(后端也会 400, 但不该靠后端兜)
 *  3. 未量测片段在回放里显式标黄, 不会悄悄补一段假画面
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import ContactSheetPanel from './ContactSheetPanel';
import PlaybackPanel from './PlaybackPanel';

function jsonResponse(body: unknown, ok = true) {
  return {
    ok,
    status: ok ? 200 : 400,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

const shot = (over: Record<string, unknown> = {}) => ({
  scene_id: 's1',
  index: 0,
  title: 'B-roll',
  prompt: 'earth limb from orbit',
  thumbnail: 's1_thumb.png',
  source_path: '/tmp/s1.mp4',
  duration_s: 14,
  cost_usd: 0.4,
  status: 'pending',
  quality: {
    score: 0.92,
    partial_score: 0.92,
    components: { exposure: 1, contrast: 0.61, motion: 1 },
    unmeasured: [],
    notes: [],
  },
  declared_score: null,
  decisions: [],
  ...over,
});

const summary = (over: Record<string, unknown> = {}) => ({
  run_id: 'r1',
  total: 1,
  approved: 0,
  rejected: 0,
  pending: 1,
  total_cost_usd: 0.4,
  approved_cost_usd: 0,
  rejected_cost_usd: 0,
  quality_scored: 1,
  quality_unmeasured: 0,
  mean_quality: 0.92,
  gate: 'awaiting_review',
  ...over,
});

describe('分镜联系表审批门', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn(async (url: string) => {
      if (url.endsWith('/shots')) return jsonResponse({ shots: [shot()], summary: summary() });
      if (url.endsWith('/contact-sheet')) return jsonResponse({ ...summary(), sheet: { path: 'x' } });
      return jsonResponse({ ok: true });
    });
    vi.stubGlobal('fetch', fetchMock);
  });

  it('显示实测质量分与成本', async () => {
    render(<ContactSheetPanel run_id="r1" />);
    expect(await screen.findByText(/实测质量 0\.92/)).toBeInTheDocument();
    expect(screen.getByText(/成本 \$0\.40/)).toBeInTheDocument();
  });

  it('自报分与实测分分开显示', async () => {
    fetchMock.mockImplementation(async (url: string) => {
      if (url.endsWith('/shots')) {
        return jsonResponse({
          shots: [shot({ declared_score: 0.1 })],
          summary: summary(),
        });
      }
      if (url.endsWith('/contact-sheet')) return jsonResponse({ ...summary(), sheet: null });
      return jsonResponse({ ok: true });
    });
    render(<ContactSheetPanel run_id="r1" />);
    expect(await screen.findByText(/自报 0\.10\(不参与判定\)/)).toBeInTheDocument();
  });

  it('未量测的维度不给总分, 且写明缺哪一维', async () => {
    fetchMock.mockImplementation(async (url: string) => {
      if (url.endsWith('/shots')) {
        return jsonResponse({
          shots: [
            shot({
              quality: {
                score: null,
                partial_score: 0.71,
                components: { exposure: 1, contrast: 0.61, motion: null },
                unmeasured: ['motion'],
                notes: ['静帧素材: 无运动可量'],
              },
            }),
          ],
          summary: summary({ mean_quality: null, quality_scored: 0, quality_unmeasured: 1 }),
        });
      }
      if (url.endsWith('/contact-sheet')) return jsonResponse({ ...summary(), sheet: null });
      return jsonResponse({ ok: true });
    });
    render(<ContactSheetPanel run_id="r1" />);
    expect(await screen.findByText(/未给总分\(部分 0\.71\)/)).toBeInTheDocument();
    expect(screen.getByText(/未量测: motion/)).toBeInTheDocument();
    expect(screen.getByText('未量测')).toBeInTheDocument(); // 均分格子
  });

  it('否决必须先写理由', async () => {
    render(<ContactSheetPanel run_id="r1" />);
    await screen.findByText(/实测质量/);
    fireEvent.click(screen.getByText('否决'));
    expect(await screen.findByText('否掉一个镜头必须写理由')).toBeInTheDocument();
    const decisions = fetchMock.mock.calls.filter((c) => String(c[0]).includes('/decision'));
    expect(decisions).toHaveLength(0);
  });

  it('写了理由才发裁决请求', async () => {
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (String(url).endsWith('/decision')) {
        const body = JSON.parse(String(init?.body)) as Record<string, string>;
        expect(body.decision).toBe('rejected');
        expect(body.reason).toBe('构图偏空');
        return jsonResponse({ ok: true, shot: shot({ status: 'rejected' }), summary: summary() });
      }
      if (url.endsWith('/shots')) return jsonResponse({ shots: [shot()], summary: summary() });
      if (url.endsWith('/contact-sheet')) return jsonResponse({ ...summary(), sheet: null });
      return jsonResponse({ ok: true });
    });
    render(<ContactSheetPanel run_id="r1" />);
    await screen.findByText(/实测质量/);
    fireEvent.change(screen.getByPlaceholderText(/裁决备注|改稿/), {
      target: { value: '构图偏空' },
    });
    fireEvent.click(screen.getByText('否决'));
    await waitFor(() => {
      const calls = fetchMock.mock.calls.filter((c) => String(c[0]).includes('/decision'));
      expect(calls.length).toBe(1);
    });
  });

  it('通过按钮直接提交(可带空理由)', async () => {
    fetchMock.mockImplementation(async (url: string) => {
      if (url.endsWith('/shots')) return jsonResponse({ shots: [shot()], summary: summary() });
      if (url.endsWith('/contact-sheet')) return jsonResponse({ ...summary(), sheet: null });
      return jsonResponse({ ok: true });
    });
    render(<ContactSheetPanel run_id="r1" />);
    await screen.findByText(/实测质量/);
    fireEvent.click(screen.getByText('通过'));
    await waitFor(() => {
      const calls = fetchMock.mock.calls.filter((c) => String(c[0]).includes('/decision'));
      expect(calls.length).toBe(1);
      expect(JSON.parse(String(calls[0][1]?.body)).decision).toBe('approved');
    });
  });
});

describe('REPLAY 回放', () => {
  beforeEach(() => {
    const fetchMock = vi.fn(async (url: string) => {
      if (url.includes('/replay?')) {
        return jsonResponse({
          run_id: 'r1',
          include: 'approved',
          segments: [
            {
              kind: 'shot',
              scene_id: 's1',
              index: 0,
              title: 'B-roll',
              status: 'approved',
              at_s: 0,
              duration_s: 14,
              cost_usd: 0.4,
              quality_score: 0.92,
            },
            {
              kind: 'decision_card',
              scene_id: 's1',
              decision: 'approved',
              reason: '运动达标',
              reviewer: 'web',
              ts: '2026-10-11T00:00:00+00:00',
              at_s: 14,
              duration_s: 1.5,
            },
            {
              kind: 'unmeasured',
              scene_id: 'ghost',
              at_s: 15.5,
              duration_s: null,
            },
          ],
          total_s: 15.5,
          segment_count: 3,
          unmeasured: [{ scene_id: 'ghost', reason: 'no readable media' }],
          renderable: false,
          summary: { approved: 1, rejected: 0, pending: 0 },
        });
      }
      return jsonResponse({ ok: true });
    });
    vi.stubGlobal('fetch', fetchMock);
  });

  it('时间线按实测时长排布, 裁决卡跟在镜头后面', async () => {
    render(<PlaybackPanel run_id="r1" />);
    expect(await screen.findByText(/共 3 段 \/ 15\.50s/)).toBeInTheDocument();
    expect(screen.getByText(/裁决 · approved · web/)).toBeInTheDocument();
    expect(screen.getByText(/未量测片段 · ghost/)).toBeInTheDocument();
  });

  it('有未量测片段时禁用渲染按钮', async () => {
    render(<PlaybackPanel run_id="r1" />);
    const btn = await screen.findByText('渲染回放片');
    expect(btn).toBeDisabled();
    expect(screen.getByText(/1 个片段没有可读的真实媒体/)).toBeInTheDocument();
  });
});
