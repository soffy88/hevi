/**
 * PaperPromo — 已验证产品宣传片模板(3O 内化 Round 3g,Ink Press 模式复刻为 hevi 版)
 *
 * 结构按 promo-energy-arc 序列模式:①品牌开场(hold ≥1s)→ ②单主角立传 → ③功能爬升
 * (功能卡 + 呼吸字卡交替)→ ④发布会收场(合影 + hold)。纸墨琥珀风格(纸底/墨字/琥珀强调)。
 *
 * 替换玩法(TEMPLATE.md):换 productName/features/pages 截图即可复现同等质感。
 * 渲染契约:2.5D 页面相机为 shotcraft PageCam 特性,本模板用平面 + 轻推近(确定性,
 * 无文字糊风险),大字卡 hold ≥1s。
 */
import React from 'react';
import { AbsoluteFill, Easing, Img, interpolate, Sequence, useCurrentFrame } from 'remotion';

export interface PaperPromoProps {
  productName?: string;
  tagline?: string;
  features?: string[];
  pages?: string[]; // 产品页面截图(真实截图,替手搓)
  accentColor?: string;
  paperColor?: string;
  inkColor?: string;
  fps?: number;
}

const TITLE_SECONDS = 2.4;
const FEATURE_SECONDS = 3.2;
const BREATH_SECONDS = 1.8;
const OUTRO_SECONDS = 3.6;

function FadeIn({ children, delayFrames = 0 }: { children: React.ReactNode; delayFrames?: number }) {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [delayFrames, delayFrames + 12], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.inOut(Easing.ease),
  });
  return <div style={{ opacity }}>{children}</div>;
}

function TitleCard({ text, accent, ink }: { text: string; accent: string; ink: string }) {
  const frame = useCurrentFrame();
  const reveal = interpolate(frame, [0, 30], [0, 1], { extrapolateRight: 'clamp' });
  return (
    <AbsoluteFill style={{ justifyContent: 'center', alignItems: 'center', background: 'transparent' }}>
      <div style={{ clipPath: `inset(0 ${(1 - reveal) * 100}% 0 0)` }}>
        <h1
          style={{
            color: ink,
            fontSize: 64,
            fontWeight: 900,
            letterSpacing: '-0.02em',
            margin: 0,
            maxWidth: 860,
            textAlign: 'center',
            fontFamily: 'Georgia, "Songti SC", serif',
          }}
        >
          {text}
          <span style={{ color: accent }}>.</span>
        </h1>
      </div>
    </AbsoluteFill>
  );
}

function FeatureCard({ title, page, accent, ink }: { title: string; page?: string; accent: string; ink: string }) {
  return (
    <AbsoluteFill style={{ justifyContent: 'center', alignItems: 'center', padding: 56, gap: 24 }}>
      <FadeIn>
        <h2 style={{ color: ink, fontSize: 40, fontWeight: 800, margin: 0 }}>{title}</h2>
      </FadeIn>
      {page && (
        <FadeIn delayFrames={10}>
          <Img
            src={page}
            style={{
              maxWidth: 720,
              maxHeight: '62%',
              objectFit: 'contain',
              borderRadius: 14,
              border: '1px solid rgba(0,0,0,0.08)',
              boxShadow: '0 18px 50px rgba(0,0,0,0.2)',
            }}
          />
        </FadeIn>
      )}
      <div style={{ width: 90, height: 3, background: accent, borderRadius: 99 }} />
    </AbsoluteFill>
  );
}

export const PaperPromo: React.FC<PaperPromoProps> = ({
  productName = '示例产品',
  tagline = '一切研究,一处汇聚',
  features = [],
  pages = [],
  accentColor = '#b45309',
  paperColor = '#f2eee6',
  inkColor = '#2b2620',
  fps = 30,
}) => {
  const titleF = Math.round(TITLE_SECONDS * fps);
  const featureF = Math.round(FEATURE_SECONDS * fps);
  const breathF = Math.round(BREATH_SECONDS * fps);
  const outroF = Math.round(OUTRO_SECONDS * fps);
  const list = features.length > 0 ? features : ['核心功能一', '核心功能二'];
  let cursor = 0;
  const shots: { from: number; dur: number; node: React.ReactNode }[] = [];
  shots.push({
    from: cursor,
    dur: titleF,
    node: <TitleCard text={`${productName} — ${tagline}`} accent={accentColor} ink={inkColor} />,
  });
  cursor += titleF;
  shots.push({
    from: cursor,
    dur: featureF,
    node: (
      <FeatureCard
        title={list[0]}
        page={pages[0]}
        accent={accentColor}
        ink={inkColor}
      />
    ),
  });
  cursor += featureF;
  for (let i = 1; i < list.length; i++) {
    shots.push({
      from: cursor,
      dur: featureF,
      node: (
        <FeatureCard title={list[i]} page={pages[i]} accent={accentColor} ink={inkColor} />
      ),
    });
    cursor += featureF;
    if (i < list.length - 1) {
      shots.push({
        from: cursor,
        dur: breathF,
        node: <TitleCard text={tagline} accent={accentColor} ink={inkColor} />,
      });
      cursor += breathF;
    }
  }
  shots.push({
    from: cursor,
    dur: outroF,
    node: <TitleCard text={`${productName}`} accent={accentColor} ink={inkColor} />,
  });

  return (
    <AbsoluteFill style={{ background: paperColor, fontFamily: 'system-ui' }}>
      {shots.map((shot, i) => (
        <Sequence key={i} from={shot.from} durationInFrames={shot.dur}>
          {shot.node}
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};

export const getPaperPromoDuration = (
  features: string[],
  fps = 30,
): number => {
  const list = features.length > 0 ? features : ['核心功能一', '核心功能二'];
  const titleF = Math.round(2.4 * fps);
  const featureF = Math.round(3.2 * fps);
  const breathF = Math.round(1.8 * fps);
  const outroF = Math.round(3.6 * fps);
  return titleF + featureF + list.length * (featureF + breathF) - breathF + outroF;
};
