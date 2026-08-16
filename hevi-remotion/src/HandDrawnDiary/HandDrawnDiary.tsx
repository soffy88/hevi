/**
 * HandDrawnDiary — 手绘日记漫画组合(3O 内化 Round 3g,补齐渲染器侧欠账)
 *
 * 对齐 story-to-handdrawn 渲染契约(hevi-remotion/RENDER-CONTRACT.md):
 *   - 1080×1440 竖屏,contain 不 cover,字幕上安全区,默认静音画面轨
 *   - cut 模式:文字→(黑白线稿→彩色插画 由素材侧提供)左→右揭示 + 落定 hold
 *   - page-flip 模式:保留母版页,左→右卷动 + 纸背淡化(3D 卷页为原版特性,轻量版以
 *     确定性横移+淡化近似)
 * props:
 *   beats: [{text?, image?}] 一拍一个;image 给出时走图片拍
 *   transition: "cut" | "page-flip"
 */
import React from 'react';
import { AbsoluteFill, Easing, Img, interpolate, Sequence, useCurrentFrame } from 'remotion';

export interface HandDrawnBeat {
  text?: string;
  image?: string;
}

export interface HandDrawnDiaryProps {
  beats?: HandDrawnBeat[];
  title?: string;
  transition?: 'cut' | 'page-flip';
  fps?: number;
  accentColor?: string;
  paperColor?: string;
  inkColor?: string;
}

const BEAT_SECONDS = 4.4;
const REVEAL_SECONDS = 1.2;
const HOLD_SECONDS = 1.0;
const PAGE_FLIP_SECONDS = 0.7;

function LeftToRightReveal({ children }: { children: React.ReactNode }) {
  const frame = useCurrentFrame();
  const pct = interpolate(frame, [0, 30], [0, 1], {
    extrapolateRight: 'clamp',
    easing: Easing.inOut(Easing.ease),
  });
  return (
    <div style={{ width: '100%', height: '100%', clipPath: `inset(0 ${(1 - pct) * 100}% 0 0)` }}>
      {children}
    </div>
  );
}

function TextBeat({ text, inkColor }: { text: string; inkColor: string }) {
  return (
    <AbsoluteFill style={{ justifyContent: 'center', alignItems: 'center', padding: 60 }}>
      <LeftToRightReveal>
        <p
          style={{
            color: inkColor,
            fontSize: 52,
            lineHeight: 1.7,
            textAlign: 'left',
            maxWidth: 880,
            margin: 0,
            fontFamily: '"STKaiti", "KaiTi", "Kaiti SC", serif',
            letterSpacing: '0.05em',
          }}
        >
          {text}
        </p>
      </LeftToRightReveal>
    </AbsoluteFill>
  );
}

function ImageBeat({ src, transition }: { src: string; transition: 'cut' | 'page-flip' }) {
  const frame = useCurrentFrame();
  const fade = interpolate(frame, [0, 15], [0, 1], { extrapolateRight: 'clamp' });
  const shift = transition === 'page-flip'
    ? interpolate(frame, [0, Math.round(PAGE_FLIP_SECONDS * 30)], [40, 0], { extrapolateRight: 'clamp' })
    : 0;
  return (
    <AbsoluteFill style={{ justifyContent: 'center', alignItems: 'center', opacity: fade, padding: 40 }}>
      <Img
        src={src}
        style={{
          maxWidth: '90%',
          maxHeight: '88%',
          objectFit: 'contain', // 渲染契约:contain 不 cover
          transform: `translateX(${shift}px)`,
          boxShadow: '0 12px 40px rgba(0,0,0,0.18)',
        }}
      />
    </AbsoluteFill>
  );
}

export const HandDrawnDiary: React.FC<HandDrawnDiaryProps> = ({
  beats = [],
  title = '',
  transition = 'cut',
  fps = 30,
  accentColor = '#b45309',
  paperColor = '#fdf6ec',
  inkColor = '#3a2f24',
}) => {
  const beatFrames = Math.round(BEAT_SECONDS * fps);
  return (
    <AbsoluteFill style={{ background: paperColor, fontFamily: 'system-ui' }}>
      <Sequence from={0} durationInFrames={Math.round(fps)}>
        <AbsoluteFill style={{ justifyContent: 'center', alignItems: 'center' }}>
          <p style={{ color: accentColor, fontSize: 40, fontWeight: 800, letterSpacing: '0.2em' }}>
            {title || '手绘日记'}
          </p>
        </AbsoluteFill>
      </Sequence>
      {beats.map((beat, i) => (
        <Sequence
          key={i}
          from={Math.round(fps) + i * beatFrames}
          durationInFrames={beatFrames}
        >
          {beat.image ? (
            <ImageBeat src={beat.image} transition={transition} />
          ) : (
            <TextBeat text={beat.text ?? ''} inkColor={inkColor} />
          )}
          {/* 落定 hold(呼吸纪律 R1):揭示完成后保持静止 */}
          <Sequence from={Math.round((REVEAL_SECONDS + HOLD_SECONDS) * fps)}>
            <div style={{ width: 0, height: 0 }} />
          </Sequence>
        </Sequence>
      ))}
      {/* 安全区底部占位(字幕轨留给后期,画面轨静音) */}
      <div style={{ position: 'absolute', left: 48, right: 48, bottom: 40, height: 2, background: accentColor, opacity: 0.25 }} />
    </AbsoluteFill>
  );
};

export const getHandDrawnDuration = (beats: HandDrawnBeat[], fps = 30): number =>
  Math.round(fps) + Math.max(beats.length, 1) * Math.round(4.4 * fps);
