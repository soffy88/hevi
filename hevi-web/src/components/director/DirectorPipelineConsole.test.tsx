import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DirectorPipelineConsole } from './DirectorPipelineConsole';

const inspectionWork = {
  work_id: 'w1', work_name: '临高启明', status: 'inspection_ready', locked_through: 1,
  material_text: '众人穿越到明末。', target_episodes: 3, episode_duration: '1-5min',
  created_at: '2026-08-02T00:00:00Z', video_task_id: null, task_ids: [], series_id: null, error: null,
  production_config: { season_budget_usd: 150, video_provider: 'happyhorse_1_1_maas_lock', audio_provider: 'vibevoice' },
  concept: { theme: '工业与秩序', tone: '冷峻', style: '历史科幻', target_audience: '硬核观众', duration_archetype: '1-5min', quality_bar: '电影感' },
  screenplay: { scenes: [{ scene_no: 1, time: '黄昏', location: '海滩', characters_present: ['文德嗣'], narration: '众人登岸。', dialogue: [], event_summary: '穿越者确认时空。' }] },
  design_list: { characters: [{ name: '文德嗣', appearance: '中年知识分子', wardrobe: '明代布衣', hairstyle: '短发', personality: '冷静', is_lead: true, voice_hint: '沉稳', subject_id: null, voice_id: null }], scenes: [{ name: '海滩', environment: '礁石海岸', lighting: '黄昏', mood: '陌生', is_primary: true, subject_id: null }], props: [] },
  shot_list: null,
  story_graph: { meta: { source: '临高启明', char_count: 8, chapter_refs: [] }, characters: [], events: [], locations: [], quotes: [], relationships: [], arcs: [] },
  season_plan: { season_id: '', story_source: '临高启明', target_episodes: 3, stylepack_ref: null, subject_refs: [], continuity_constraints: [], episodes: [1, 2, 3].map(ep => ({ ep_number: ep, title: `第${ep}集`, event_ids: [`E${ep}`], beats: ['冲突'], characters_present: ['C1'], locations: ['海滩'], target_emotion_arc: '陌生→决断' })) },
  gate_report: { passed: true, score: .94, estimated_cost_usd: 32.5, identity_readiness: 1, errors: [], warnings: [], checks: [{ key: 'story_graph', label: '故事图谱完整度', passed: true, score: 1, detail: '1 个角色 · 3 个事件' }] },
  estimated_cost_usd: 32.5,
  decision_trail: [{ at: '2026-08-02T00:00:00Z', stage: 'storygraph_extraction', status: 'succeeded', detail: '抽取完成' }],
};

const api = vi.hoisted(() => ({
  parseWork: vi.fn(), dispatchSeason: vi.fn(), getWork: vi.fn(), taskGet: vi.fn(),
}));

vi.mock('@/lib/api-client', () => ({
  directorPipelineApi: {
    parseWork: api.parseWork,
    dispatchSeason: api.dispatchSeason,
    getWork: api.getWork,
  },
  taskApi: { get: api.taskGet, videoUrl: (id: string) => `/api/tasks/${id}/video` },
}));

describe('导演流水线工业化单流工作台', () => {
  it('冷启动只保留一个解析入口，不再展示三块割裂工具', () => {
    render(<DirectorPipelineConsole />);
    expect(screen.getByRole('heading', { name: '🎬 导演流水线' })).toBeInTheDocument();
    expect(screen.getByLabelText('作品名称')).toBeInTheDocument();
    expect(screen.getByLabelText('文本来源')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /启动 Agent 智能解析/ })).toBeInTheDocument();
    expect(screen.queryByText(/Agent 编排底座/)).not.toBeInTheDocument();
    expect(screen.queryByText(/全自动派发（手稿/)).not.toBeInTheDocument();
  });

  it('解析完成后在同一条流中展开分集、角色资产、门禁与派发配置', async () => {
    api.parseWork.mockResolvedValueOnce(inspectionWork);
    const user = userEvent.setup();
    render(<DirectorPipelineConsole />);
    await user.type(screen.getByLabelText('作品名称'), '临高启明');
    await user.type(screen.getByLabelText('文本来源'), '众人穿越到明末。');
    await user.click(screen.getByRole('button', { name: /启动 Agent 智能解析/ }));

    expect(await screen.findByRole('heading', { name: /导演审查台/ })).toBeInTheDocument();
    expect(screen.getByText(/剧本与分集规划/)).toBeInTheDocument();
    expect(screen.getByText(/Character Bible/)).toBeInTheDocument();
    expect(screen.getByText(/导演双环自批判门禁/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /确认资产并一键派发整季生成/ })).toBeInTheDocument();
    expect(api.parseWork).toHaveBeenCalledWith(expect.objectContaining({ target_episodes: 3 }));
  });
});
