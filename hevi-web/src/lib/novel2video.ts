/**
 * novel2video — Novel2Video 长文本小说解析引擎 (Frontend SPEC v6.0 §2.2)
 *
 * 前端编排:小说原文 ➔ 角色提取 ➔ 章节/节拍规划 ➔ 季预算校验 ➔ 派发生成。
 * 复用既有 works 端点逐集自动锁定(后端无季派发端点,v4.0 约束),本模块只做
 * 纯前端文本解析(角色/章节/节拍抽取 + 分集规划),零后端依赖。
 */

export interface NovelCharacter {
  name: string;
  mentions: number;
  firstAppearance: number;   // 出现的最早章节序号(0-based)
  role: 'main' | 'supporting';
}

export interface NovelChapter {
  index: number;
  title: string;
  start: number;   // 原文起始字符偏移
  end: number;     // 原文结束字符偏移(不含)
  beats: string[]; // 节拍(按段落/转折切分)
}

export interface NovelParseResult {
  chapters: NovelChapter[];
  characters: NovelCharacter[];
  totalChars: number;
  totalBeats: number;
  /** 每集对应的章节分配(planEpisodes 产物) */
  episodePlan: Array<{ ep: number; chapters: NovelChapter[]; charCount: number; wordCount: number }>;
}

const CN_NUM = '一二三四五六七八九十百千万零〇两';
const CHAPTER_RE = new RegExp(`^[\\s\\n]*(?:第[${CN_NUM}\\d]+[章回节卷集部篇]|(?:序章|楔子|尾声|终章))[\\s：:、.．]*[^\\n]{0,40}$`, 'gm');

/** 章节/节拍切分:优先按"第X章"标题,无标题则按空行分段。 */
function splitChapters(text: string): Array<{ title: string; start: number; end: number; beats: string[] }> {
  const matches = [...text.matchAll(CHAPTER_RE)];
  if (matches.length >= 2) {
    const blocks = matches.map((m, i) => ({
      title: m[0].trim().slice(0, 40),
      start: m.index ?? 0,
      end: i + 1 < matches.length ? (matches[i + 1]!.index ?? text.length) : text.length,
    }));
    return blocks.map(b => ({
      ...b,
      beats: text.slice(b.start, b.end).split(/\n\s*\n/).filter(p => p.trim().length > 0).slice(0, 20),
    }));
  }
  // 无章节标题:按空行分段,每 3 段合成一章(上限 12 章)
  const paras = text.split(/\n\s*\n/).filter(p => p.trim());
  if (paras.length === 0) return [];
  const size = Math.max(1, Math.ceil(paras.length / 12));
  const blocks: Array<{ title: string; start: number; end: number; beats: string[] }> = [];
  let offset = 0;
  for (let i = 0; i < paras.length; i += size) {
    const chunk = paras.slice(i, i + size);
    const start = text.indexOf(chunk[0]!, offset);
    const end = i + size < paras.length ? text.indexOf(paras[i + size]!, offset) : text.length;
    blocks.push({ title: `第${CN_NUM[blocks.length] ?? blocks.length + 1}段`, start, end, beats: chunk });
    offset = end;
  }
  return blocks;
}

const DIALOG_RE = /([\u4e00-\u9fa5A-Za-z·]{2,8}?)(?:说|道|问|答|喊|叫|嚷|笑|叹|哭|怒|轻声道|低声道|大声道|自言自语)/g;

/** 角色提取:对白发言人 + 「」引号内人名 + 高频专有名词(启发式)。 */
export function extractCharacters(text: string, chapters: NovelChapter[]): NovelCharacter[] {
  const counts = new Map<string, number>();
  const firstSeen = new Map<string, number>();
  for (let ci = 0; ci < chapters.length; ci++) {
    const seg = text.slice(chapters[ci]!.start, chapters[ci]!.end);
    for (const m of seg.matchAll(DIALOG_RE)) {
      const name = m[1]!.trim();
      if (name.length < 2 || name.length > 8) continue;
      // 过滤常见虚词
      if (/^(他|她|它|你|我|你们|我们|他们|大家|众人|有人|某人|那人|属下|老奴)$/.test(name)) continue;
      counts.set(name, (counts.get(name) ?? 0) + 1);
      if (!firstSeen.has(name)) firstSeen.set(name, ci);
    }
    // 「」引号内的人名(如 "「林七」")——仅当不在对话引号内时粗取
    for (const m of seg.matchAll(/「([\u4e00-\u9fa5A-Za-z·]{2,8})」/g)) {
      const name = m[1]!;
      counts.set(name, (counts.get(name) ?? 0) + 1);
      if (!firstSeen.has(name)) firstSeen.set(name, ci);
    }
  }
  return [...counts.entries()]
    .map(([name, mentions]) => ({
      name,
      mentions,
      firstAppearance: firstSeen.get(name) ?? 0,
      role: mentions >= 4 ? 'main' as const : 'supporting' as const,
    }))
    .sort((a, b) => b.mentions - a.mentions)
    .slice(0, 12);
}

/** 解析小说原文:章节/节拍 + 角色提取 + 分集规划(按季预算均摊)。 */
export function parseNovel(text: string, episodeCount = 1): NovelParseResult {
  const chapters = splitChapters(text).map((c, i) => ({ index: i, ...c }));
  const characters = extractCharacters(text, chapters);
  const totalBeats = chapters.reduce((n, c) => n + c.beats.length, 0);
  // 分集规划:章节按序均摊到各集(尽量均衡字数)
  const n = Math.max(1, Math.min(episodeCount, 6));
  const episodePlan: NovelParseResult['episodePlan'] = [];
  if (chapters.length === 0) {
    for (let ep = 0; ep < n; ep++) {
      episodePlan.push({ ep: ep + 1, chapters: [], charCount: characters.length, wordCount: 0 });
    }
  } else {
    const per = Math.ceil(chapters.length / n);
    for (let ep = 0; ep < n; ep++) {
      const seg = chapters.slice(ep * per, (ep + 1) * per);
      const wordCount = seg.reduce((w, c) => w + (c.end - c.start), 0);
      episodePlan.push({ ep: ep + 1, chapters: seg, charCount: characters.length, wordCount });
    }
  }
  return { chapters, characters, totalChars: text.length, totalBeats, episodePlan };
}

/** 把某集规划渲染为派发用的手稿文本(章节标题拼接 + 节拍)。 */
export function episodeText(plan: NovelParseResult['episodePlan'][number]): string {
  return plan.chapters
    .map(c => `${c.title}\n${c.beats.join('\n\n')}`)
    .join('\n\n');
}
