/**
 * novel2video 单元测试 — Frontend SPEC v6.0 §2.2
 * Novel2Video 长文本解析:章节/节拍切分 + 角色提取 + 分集规划。
 */
import { describe, expect, it } from 'vitest';
import { parseNovel, extractCharacters, episodeText } from './novel2video';

const NOVEL = `第一章 雪夜

林七裹紧大衣走进酒馆。
小二问道:"客官要些什么?"
林七说:"一壶热酒。"
林七叹了口气,望向窗外的大雪。

第二章 追踪

赵四在巷口等着林七。
林七问:"找到他了吗?"
赵四摇了摇头:"没有。"
林七攥紧了拳头,眼中闪过一丝寒光。

尾声 决裂

林七与赵四背对而立。
林七说:"从今日起,你我恩断义绝。"
赵四沉默良久,转身离去。`;

describe('Novel2Video 手稿解析(SPEC v6.0 §2.2)', () => {
  it('按章节标题切分(第一章/第二章/尾声)', () => {
    const r = parseNovel(NOVEL, 2);
    expect(r.chapters.length).toBe(3);
    expect(r.chapters[0]!.title).toContain('第一章');
    expect(r.totalBeats).toBeGreaterThan(0);
  });

  it('角色提取:对白发言人 + 「」人名,主角按提及次数区分', () => {
    const chars = extractCharacters(NOVEL, parseNovel(NOVEL, 1).chapters);
    const linQi = chars.find(c => c.name === '林七');
    expect(linQi).toBeDefined();
    expect(linQi!.role).toBe('main');
    expect(chars.some(c => c.name === '小二')).toBe(true);
    expect(chars.every(c => !/^(他|她|你|我|你们)$/.test(c.name))).toBe(true);
  });

  it('分集规划:按目标集数把章节均摊,并给出每集字数预算', () => {
    const r = parseNovel(NOVEL, 2);
    expect(r.episodePlan).toHaveLength(2);
    const first = r.episodePlan[0]!;
    expect(first.chapters.length).toBeGreaterThan(0);
    expect(first.wordCount).toBeGreaterThan(0);
    // 集数上限 6
    expect(parseNovel(NOVEL, 12).episodePlan).toHaveLength(6);
  });

  it('无章节标题时按段落分章兜底', () => {
    const r = parseNovel('段落一。\n\n段落二。\n\n段落三。', 1);
    expect(r.chapters.length).toBeGreaterThan(0);
    expect(r.chapters[0]!.title).toContain('段');
  });

  it('episodeText 拼接章节标题与节拍供派发', () => {
    const r = parseNovel(NOVEL, 2);
    const text = episodeText(r.episodePlan[0]!);
    expect(text).toContain('第一章');
    expect(text).toContain('林七');
  });
});
