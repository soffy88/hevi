/**
 * tapeCover 测试:标题截断 / 调色 / canvas 封面与标牌生成(jsdom 下 mock 2D context)。
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import {
  truncateTitle,
  shadeHex,
  wrapText,
  makeTapeCoverCanvas,
  makeSpineCanvas,
  makeSignCanvas,
  makeBackCoverCanvas,
} from './tapeCover';

function mockCanvas2d() {
  const ctx = {
    createLinearGradient: () => ({ addColorStop: vi.fn() }),
    fillRect: vi.fn(),
    fillText: vi.fn(),
    strokeRect: vi.fn(),
    beginPath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    stroke: vi.fn(),
    measureText: (s: string) => ({ width: [...s].length * 10 }),
  };
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(
    (() => ctx) as unknown as typeof HTMLCanvasElement.prototype.getContext,
  );
  return ctx;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('truncateTitle', () => {
  it('短标题原样返回(去首尾空白)', () => {
    expect(truncateTitle(' 黑洞的秘密 ', 16)).toBe('黑洞的秘密');
  });

  it('超长标题按码点截断并加省略号', () => {
    expect(truncateTitle('一二三四五六七八九十', 5)).toBe('一二三四五…');
  });

  it('emoji 等代理对按码点截断不劈裂', () => {
    expect(truncateTitle('a😀b😀c', 3)).toBe('a😀b…');
  });
});

describe('shadeHex', () => {
  it('调暗/调亮并保持 #rrggbb 格式', () => {
    expect(shadeHex('#808080', -40)).toBe('#585858');
    expect(shadeHex('#000000', 40)).toBe('#282828');
  });

  it('非法输入原样返回', () => {
    expect(shadeHex('red', -10)).toBe('red');
    expect(shadeHex('#12345', -10)).toBe('#12345');
  });
});

describe('canvas 生成(jsdom mock)', () => {
  it('getContext 可用时产出画布,尺寸正确', () => {
    mockCanvas2d();
    const canvas = makeTapeCoverCanvas({ title: '宇宙的尺度', color: '#1e40af', icon: '▶' });
    expect(canvas).not.toBeNull();
    expect(canvas!.width).toBe(512);
    expect(canvas!.height).toBe(768);
  });

  it('无 2D context(jsdom 原生)时降级返回 null', () => {
    const canvas = makeTapeCoverCanvas({ title: 'x', color: '#000', icon: '▶' });
    expect(canvas).toBeNull();
  });

  it('书脊与标牌同样可生成 / 可降级', () => {
    mockCanvas2d();
    expect(makeSpineCanvas('黑洞的秘密', '#1e40af')).not.toBeNull();
    expect(makeSignCanvas({ label: '长视频', icon: '▶', color: '#1e40af' })).not.toBeNull();
    expect(makeSpineCanvas('黑洞的秘密', '#1e40af')).not.toBeNull();
  });
});

describe('wrapText 多行换行', () => {
  const fakeCtx = { measureText: (s: string) => ({ width: [...s].length * 10 }) } as unknown as CanvasRenderingContext2D;

  it('按最大宽度折行', () => {
    const lines = wrapText(fakeCtx, '从地球出发逐级放大到可观测宇宙边缘', 60);
    expect(lines.length).toBeGreaterThan(1);
    for (const ln of lines) expect([...ln].length * 10).toBeLessThanOrEqual(60);
  });

  it('短文本单行返回', () => {
    expect(wrapText(fakeCtx, '短句', 100)).toEqual(['短句']);
  });

  it('显式换行符分段', () => {
    expect(wrapText(fakeCtx, '第一段\n第二段', 200)).toEqual(['第一段', '第二段']);
  });

  it('空串返回空数组', () => {
    expect(wrapText(fakeCtx, '', 200)).toEqual([]);
  });
});

describe('makeBackCoverCanvas 背封', () => {
  it('mock context 下可生成', () => {
    mockCanvas2d();
    const canvas = makeBackCoverCanvas({ title: '宇宙的尺度', description: '从地球到宇宙', color: '#1e40af', icon: '▶' });
    expect(canvas).not.toBeNull();
    expect(canvas!.width).toBe(512);
    expect(canvas!.height).toBe(768);
  });

  it('无 2D context 时降级 null', () => {
    expect(makeBackCoverCanvas({ title: 'x', color: '#000', icon: '▶' })).toBeNull();
  });
});
