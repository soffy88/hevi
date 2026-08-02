/**
 * prompt-enhancer 单元测试 — Frontend SPEC v6.0 §2.1
 * Idea2Video Prompt Enhancer:一句话创意 → 分镜拆分 + 风格润色。
 */
import { describe, expect, it } from 'vitest';
import { enhanceIdea, splitIdeaScenes, IDEA_STYLES } from './prompt-enhancer';

describe('Idea2Video Prompt Enhancer(SPEC v6.0 §2.1)', () => {
  it('按标点把一句话创意拆分为分镜场景', () => {
    const scenes = splitIdeaScenes('深夜的实验室。白大褂青年抬头。墙上的影子动了。', 3);
    expect(scenes).toHaveLength(3);
    expect(scenes[0]).toContain('实验室');
  });

  it('场景数超上限时按比例合并', () => {
    const scenes = splitIdeaScenes('a。b。c。d。e。', 2);
    expect(scenes).toHaveLength(2);
    expect(scenes.join('')).toContain('a');
    expect(scenes.join('')).toContain('e');
  });

  it('enhanceIdea 输出含分镜编号与风格指令', () => {
    const idea = '一个孤独的旅行者穿越沙漠';
    const out = enhanceIdea({ idea, style: 'cinematic', aspectRatio: '16:9', maxScenes: 4 });
    expect(out.prompt).toContain('[创意视频]');
    expect(out.prompt).toContain('1.');
    expect(out.prompt).toContain(idea);
    expect(out.prompt).toContain('cinematic');
    expect(out.prompt).toContain('16:9');
    expect(out.scenes.length).toBeGreaterThan(0);
  });

  it('未知风格回落到写实', () => {
    const out = enhanceIdea({ idea: 'x', style: 'noir', aspectRatio: '9:16', maxScenes: 2 });
    expect(out.styleDirective).toContain('film noir');
  });

  it('风格表覆盖五档(写实/电影/动漫/黑色/水墨)', () => {
    expect(IDEA_STYLES.map(s => s.id)).toEqual(['realistic', 'cinematic', 'anime', 'noir', 'inkwash']);
  });
});
