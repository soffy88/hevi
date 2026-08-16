/**
 * WordCaptions — 词级字幕组件(3O 内化 Round 3,补"词级字幕 @remotion/captions"缺口)
 *
 * 用 @remotion/captions 的 parseSrt + ensureMaxCharactersPerLine 处理字幕 →
 * 词级逐字点亮(Remotion 原语实现,确定性)。
 *
 * props:
 *   srt: SRT 字幕文本(词级时间戳;缺省用句级 —— 组件按句显示)。
 *   width/height/fontSize/position: 排版参数。
 */
import React from 'react';
import { AbsoluteFill, Easing, interpolate, Sequence, useCurrentFrame } from 'remotion';
import { CaptionsInternals, parseSrt, type Caption } from '@remotion/captions';

export interface WordCaptionsProps {
  srt: string;
  width?: number;
  height?: number;
  fontSize?: number;
  fontFamily?: string;
  color?: string;
  highlightColor?: string;
  bottomOffsetPx?: number;
}

function Word({ word, startMs, endMs, color, highlightColor, fontSize }: {
  word: string;
  startMs: number;
  endMs: number;
  color: string;
  highlightColor: string;
  fontSize: number;
}) {
  const frame = useCurrentFrame();
  const ms = frame * (1000 / 30); // 默认 30fps;composition 应配 30fps
  const opacity = interpolate(ms, [startMs, startMs + 60, endMs - 60, endMs], [0.25, 1, 1, 0.25], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.inOut(Easing.ease),
  });
  const isActive = ms >= startMs && ms <= endMs;
  return (
    <span style={{ color: isActive ? highlightColor : color, opacity, fontSize, marginRight: '0.35em' }}>
      {word}
    </span>
  );
}

function CaptionLine({ words, top, fontSize, color, highlightColor }: {
  words: { word: string; startMs: number; endMs: number }[];
  top: number;
  fontSize: number;
  color: string;
  highlightColor: string;
}) {
  const first = words[0]?.startMs ?? 0;
  const last = words[words.length - 1]?.endMs ?? 0;
  return (
    <Sequence from={Math.floor(first / 33.33)} durationInFrames={Math.ceil((last - first) / 33.33) + 1}>
      <AbsoluteFill style={{ top, justifyContent: 'flex-start', alignItems: 'center' }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'center', maxWidth: '80%', padding: '8px 14px', borderRadius: 10, background: 'rgba(0,0,0,0.45)' }}>
          {words.map((w, i) => (
            <Word key={i} word={w.word} startMs={w.startMs} endMs={w.endMs}
              color={color} highlightColor={highlightColor} fontSize={fontSize} />
          ))}
        </div>
      </AbsoluteFill>
    </Sequence>
  );
}

export const WordCaptions: React.FC<WordCaptionsProps> = ({
  srt,
  width = 1080,
  height = 1920,
  fontSize = 46,
  fontFamily = 'sans-serif',
  color = '#e8eaf0',
  highlightColor = '#5ba0ff',
  bottomOffsetPx = 140,
}) => {
  let captions: Caption[];
  try {
    captions = parseSrt({ input: srt }).captions;
  } catch {
    return null; // 非法 SRT → 不渲染(确定性降级)
  }
  const { segments } = CaptionsInternals.ensureMaxCharactersPerLine({ captions, maxCharsPerLine: 12 });
  const top = height - bottomOffsetPx;
  return (
    <AbsoluteFill style={{ width, height, fontFamily, overflow: 'hidden' }}>
      {segments.map((line, i) => (
        <CaptionLine key={i}
          words={line.map(c => ({ word: c.text, startMs: c.startMs, endMs: c.endMs }))}
          top={top} fontSize={fontSize} color={color} highlightColor={highlightColor} />
      ))}
    </AbsoluteFill>
  );
};
