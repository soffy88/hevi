import React from "react";
import { AbsoluteFill, Freeze, Sequence, useCurrentFrame, getRemotionEnvironment } from "remotion";
import type { ProjectData } from "../types";
import { CARDS } from "../cards/registry";
import { defaultsOf } from "../cards/types";

// hevi patch (2026-10-10): clips with props.__alpha=true render card-root-transparent over lower tracks.
/** 时间重映射：clip 本地帧 → 卡片源帧（inOffset + f × speed）。
 *  卡片全部是 frame 的纯函数（tween 均 clamp），因此变速/裁入/超时长定格都安全。
 *  不变速且不裁入时直通不包 Freeze——含 Audio/Video 的卡需要原生播放（Freeze 会掐掉声音）。 */
const TimeRemap: React.FC<{
  inOffset: number;
  speed: number;
  children: React.ReactNode;
}> = ({ inOffset, speed, children }) => {
  const frame = useCurrentFrame();
  if (speed === 1 && inOffset === 0) return <>{children}</>;
  return <Freeze frame={Math.max(0, inOffset + frame * speed)}>{children}</Freeze>;
};

/** 单 clip 报错只把这一格画红（实时看板下 agent 半成品是常态），其余 clip 照常。
 *  **只在 Player / Studio 里容错**：Remotion CLI 渲染（导出成片 / 透明导出）时原样抛出让任务失败——
 *  否则红色错误画面会被当成功产物交付（2026-09-13 审计 R3）。 */
class ClipBoundary extends React.Component<{ label: string; children: React.ReactNode }, { err: string | null }> {
  state = { err: null as string | null };
  static getDerivedStateFromError(e: unknown) {
    return { err: e instanceof Error ? e.message : String(e) };
  }
  componentDidUpdate(prev: { children: React.ReactNode }) {
    // 子树换了（HMR / props 改）就再试一次
    if (this.state.err && prev.children !== this.props.children) this.setState({ err: null });
  }
  render() {
    if (this.state.err) {
      if (getRemotionEnvironment().isRendering) throw new Error(`片段渲染出错 · ${this.props.label}：${this.state.err}`);
      return (
        <AbsoluteFill style={{ background: "rgba(90,20,24,0.92)", color: "#ffb4ad", padding: 36, fontFamily: "-apple-system, PingFang SC, sans-serif" }}>
          <div style={{ fontSize: 26, fontWeight: 600 }}>片段渲染出错 · {this.props.label}</div>
          <pre style={{ marginTop: 12, fontSize: 16, lineHeight: 1.5, whiteSpace: "pre-wrap", opacity: 0.85 }}>{this.state.err.slice(0, 400)}</pre>
        </AbsoluteFill>
      );
    }
    return this.props.children;
  }
}

/** 透明通道导出（右键片段 → 导出透明通道）时注入：
 *  108 张卡的根 AbsoluteFill 都画了不透明幕底（中性白 / 深底），透明导出要的是"动效本体"，
 *  所以把每个 clip 图层的直接子层（= 卡根层）背景去掉；人物剪影占位（HostSilhouette）与
 *  口播镜头卡的白底层（wb-shot-bg）、skill 工程镜头里的实拍底床（wb-bed：整幅 B-roll 是背景不是动效本体，2026-09-16 用户导出 s01 看到棋盘"背景图"）也一并去掉。只动根层与这几处标记层——卡内部的色块 / 底板 /
 *  转场色面是动效内容，不能动。样式表 !important 能压过 React 的 inline style（inline 没有 !important）。 */
const ALPHA_CSS = `
.wb-alpha > div { background: transparent !important; }
.wb-alpha .wb-shot-bg { background: transparent !important; }
.wb-alpha .wb-host-silhouette { display: none !important; }
.wb-alpha .wb-bed { display: none !important; }
`;

/** hevi patch (2026-10-10): talkcraft "one slow camera curve per shot".
 *  props.__push = extra scale reached at the clip's end (0.05 = 5% push-in),
 *  props.__driftX = horizontal drift in px over the clip; sine-eased, continuous,
 *  so a held card is never a frozen frame. 0/absent = original behaviour. */
const PushLayer: React.FC<{
  className?: string; opacity: number; x: number; y: number; scale: number;
  push: number; driftX: number; duration: number; children: React.ReactNode;
}> = ({ className, opacity, x, y, scale, push, driftX, duration, children }) => {
  const frame = useCurrentFrame();
  const p = Math.min(1, Math.max(0, frame / duration));
  const e = 0.5 - 0.5 * Math.cos(Math.PI * p);
  const s = scale * (1 + push * e);
  const dx = x + driftX * (e - 0.5);
  return (
    <AbsoluteFill className={className} style={{ opacity, transform: `translate(${dx}px, ${y}px) scale(${s})` }}>
      {children}
    </AbsoluteFill>
  );
};

export const MainComposition: React.FC<{ project: ProjectData; transparent?: boolean }> = ({
  project,
  transparent,
}) => {
  // UI 中 tracks[0] 是最上层轨 → 最后渲染（覆盖在上）
  const ordered = [...project.tracks].reverse();
  return (
    <AbsoluteFill style={{ background: transparent ? "transparent" : "#0e0e10" }}>
      {/* hevi: per-clip alpha (props.__alpha) needs the sheet even when the root is opaque */}
      <style>{ALPHA_CSS}</style>
      {ordered.map(
        (track) =>
          !track.hidden &&
          track.clips.map((clip) => {
            const card = CARDS[clip.cardId];
            if (!card) return null;
            const Comp = card.component;
            const props = { ...defaultsOf(card), ...clip.props };
            // 音频卡：裁入/变速交给卡内 <Audio trimBefore playbackRate>，
            // 不能包 Freeze（会掐死原生播放），也无需图层包裹
            const label = clip.label ?? card.name;
            if (card.kind === "audio") {
              return (
                <Sequence
                  key={clip.id}
                  from={clip.start}
                  durationInFrames={Math.max(1, Math.round(clip.duration))}
                >
                  <ClipBoundary label={label}>
                    <Comp {...props} inOffset={clip.inOffset} speed={clip.speed} />
                  </ClipBoundary>
                </Sequence>
              );
            }
            return (
              <Sequence
                key={clip.id}
                from={clip.start}
                durationInFrames={Math.max(1, Math.round(clip.duration))}
              >
                <PushLayer
                  className={transparent || clip.props?.__alpha ? "wb-alpha" : undefined}
                  opacity={clip.opacity}
                  x={clip.x}
                  y={clip.y}
                  scale={clip.scale}
                  push={Number(clip.props?.__push ?? 0)}
                  driftX={Number(clip.props?.__driftX ?? 0)}
                  duration={Math.max(1, Math.round(clip.duration))}
                >
                  <ClipBoundary label={label}>
                    {card.kind === "video" ? (
                      // 视频卡：同音频卡走原生播放通道，保留图层包裹
                      <Comp {...props} inOffset={clip.inOffset} speed={clip.speed} />
                    ) : (
                      <TimeRemap inOffset={clip.inOffset} speed={clip.speed}>
                        <Comp {...props} />
                      </TimeRemap>
                    )}
                  </ClipBoundary>
                </PushLayer>
              </Sequence>
            );
          }),
      )}
    </AbsoluteFill>
  );
};
