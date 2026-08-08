import { Audio } from "@remotion/media";
import { AbsoluteFill, Img, Sequence, staticFile, useVideoConfig } from "remotion";
import { Captions } from "./captions/Captions";
import manifest from "./data/run_manifest.json";
import { CardsScene } from "./scenes/CardsScene";
import { DefinitionScene } from "./scenes/DefinitionScene";
import { HookScene } from "./scenes/HookScene";
import { MethodScene } from "./scenes/MethodScene";
import { OutroScene } from "./scenes/OutroScene";
import { ReasonScene } from "./scenes/ReasonScene";
import { BrowserBrollSegment } from "./ExplainerVideo/BrowserBrollSegment";
import { CodeHighlightSegment } from "./ExplainerVideo/CodeHighlightSegment";
import { ContinuousAvatarPiP } from "./ExplainerVideo/ContinuousAvatarPiP";
import { DynamicChartSegment } from "./ExplainerVideo/DynamicChartSegment";
import { HeyGenAvatarSegment } from "./ExplainerVideo/HeyGenAvatarSegment";
import { TitleCardSequence } from "./ExplainerVideo/TitleCardSequence";
import { WordSubtitle, type SubtitleLine } from "./ExplainerVideo/WordSubtitle";
import type {
  RunManifest,
  SceneProps,
  SceneType,
} from "./types";

const typedManifest = manifest as unknown as RunManifest;

function resolvePackaging(): {
  mainTitle: string;
  subtitle: string;
  backgroundImageUrl?: string;
  presenterImageUrl?: string;
} {
  const firstSeg = typedManifest[0];
  if (firstSeg?.visualConfig?.packaging && typeof firstSeg.visualConfig.packaging === "object") {
    const pkg = firstSeg.visualConfig.packaging as Record<string, unknown>;
    return {
      mainTitle: String(pkg.main_title ?? pkg.mainTitle ?? ""),
      subtitle: String(pkg.subtitle ?? ""),
      backgroundImageUrl: pkg.theme_image_query ? String(pkg.theme_image_query) : undefined,
      presenterImageUrl: pkg.presenter_image_url ? String(pkg.presenter_image_url) : undefined,
    };
  }
  return {
    mainTitle: typedManifest.some((s) => s.sceneType === "hook") ? "探索 · 深度解说" : "HEVI",
    subtitle: "",
  };
}

function resolveContinuousAvatar(): string | null {
  const candidates = [
    "continuous_avatar/continuous_avatar_p.mp4",
    "continuous_avatar/continuous_avatar_l.mp4",
    "avatar/continuous.mp4",
  ];
  return candidates[0];
}

/** Whether the current manifest indicates an avatar was produced. */
function hasAvatarTrack(): boolean {
  const packaging = resolvePackaging();
  return !!packaging.presenterImageUrl;
}

type SceneComponent = React.FC<{ durationInFrames: number; props: SceneProps }>;

const SCENE_COMPONENTS: Record<SceneType, SceneComponent> = {
  hook: HookScene as unknown as SceneComponent,
  definition: DefinitionScene as unknown as SceneComponent,
  cards: CardsScene as unknown as SceneComponent,
  reason: ReasonScene as unknown as SceneComponent,
  method: MethodScene as unknown as SceneComponent,
  outro: OutroScene as unknown as SceneComponent,
};

const VisualOverlay: React.FC<{
  visualType?: string;
  visualConfig?: Record<string, unknown>;
}> = ({ visualType, visualConfig }) => {
  if (!visualType || visualType === "voiceover") return null;
  const asset = visualConfig?.assetUrl;
  const assetSrc = typeof asset === "string"
    ? asset.startsWith("http") ? asset : staticFile(asset.replace(/^\//, ""))
    : null;
  if (visualType === "browser_broll") {
    return <BrowserBrollSegment src={assetSrc ?? undefined} />;
  }
  if (visualType === "heygen_avatar") {
    const presenterName = typeof visualConfig?.presenter_name === "string"
      ? visualConfig.presenter_name
      : "HEVI 数字人";
    const circle = visualConfig?.circle_avatar_mask !== false;
    return (
      <div style={{ position: "absolute", right: 48, top: 48, width: 260, height: 260, overflow: "hidden", borderRadius: circle ? "50%" : 20, border: "2px solid rgba(255,255,255,.28)" }}>
        <HeyGenAvatarSegment src={assetSrc ?? undefined} circle={circle} presenterName={presenterName} />
      </div>
    );
  }
  if (visualType === "remotion_chart") {
    const chart = visualConfig?.chart_data;
    const chartValues = Array.isArray(chart)
      ? chart
      : chart && typeof chart === "object" && "values" in chart
        ? (chart as { values?: unknown }).values
        : [];
    const values = Array.isArray(chartValues)
      ? chartValues.filter((item): item is number => typeof item === "number")
      : [];
    const labels = chart && typeof chart === "object" && "labels" in chart
      ? (chart as { labels?: unknown }).labels
      : [];
    return <DynamicChartSegment values={values} labels={Array.isArray(labels) ? labels.map(String) : []} />;
  }
  if (visualType === "remotion_code") {
    return <CodeHighlightSegment codeText={typeof visualConfig?.code_text === "string" ? visualConfig.code_text : ""} language={typeof visualConfig?.language === "string" ? visualConfig.language : "text"} />;
  }
  const subtitleLines = visualConfig?.subtitle_lines;
  if (Array.isArray(subtitleLines)) {
    return <WordSubtitle lines={subtitleLines as SubtitleLine[]} />;
  }
  if (assetSrc) {
    return (
      <Img
        src={assetSrc}
        style={{
          position: "absolute",
          right: 48,
          top: 48,
          width: visualType === "heygen_avatar" ? 220 : 420,
          height: visualType === "heygen_avatar" ? 220 : 250,
          objectFit: "cover" as const,
          borderRadius: visualType === "heygen_avatar" && visualConfig?.circle_avatar_mask !== false ? "50%" : 24,
          border: "2px solid rgba(255,255,255,.28)",
        }}
      />
    );
  }
  const labels: Record<string, string> = {
    heygen_avatar: "数字人 · 自动出镜",
    broll_news: "B-ROLL · 新闻素材",
    stock_broll: "B-ROLL · 精选素材",
    data_screenshot: "DATA · 来源截图",
    remotion_chart: "REMOTION · 数据图表",
    remotion_code: "REMOTION · 代码动画",
  };
  return (
    <div style={{ position: "absolute", right: 48, top: 48, width: 360, minHeight: 120, padding: 24, borderRadius: 20, background: "rgba(14,14,18,.82)", border: "1px solid rgba(255,255,255,.16)", color: "#fff", fontSize: 20, letterSpacing: ".04em" }}>
      {labels[visualType] ?? visualType}
    </div>
  );
};

export const computeFrameStarts = (fps: number): number[] => {
  let cumulativeSec = 0;
  const starts = [0];
  for (const seg of typedManifest) {
    cumulativeSec += seg.durationSec;
    starts.push(Math.round(cumulativeSec * fps));
  }
  return starts;
};

export const getTotalDurationInFrames = (fps: number): number => {
  const starts = computeFrameStarts(fps);
  return starts[starts.length - 1];
};

export const ExplainerVideo: React.FC = () => {
  const { fps } = useVideoConfig();
  const frameStarts = computeFrameStarts(fps);
  const packaging = resolvePackaging();
  const avatarPath = resolveContinuousAvatar();
  const titleCardDuration = Math.max(90, fps * 3); // min 3 seconds at 30fps

  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      
      {/* ═══════ ① TITLE CARD SEQUENCE (Frame 0) ═══════ */}
      <Sequence from={0} durationInFrames={titleCardDuration} layout="none">
        <TitleCardSequence
          title={packaging.mainTitle}
          subtitle={packaging.subtitle}
          backgroundImageUrl={packaging.backgroundImageUrl}
          totalDurationInFrames={titleCardDuration}
        />
      </Sequence>

      {/* ═══════ ② CONTINUOUS AVATAR TRACK (full video, z-index 1) ═══════ */}
      {hasAvatarTrack() && (
        <Sequence from={titleCardDuration} layout="none">
          {avatarPath ? (
            <ContinuousAvatarPiP src={staticFile(avatarPath)} layoutMode="fullscreen" />
          ) : (
            <div style={{ position: "absolute", zIndex: 1 }} />
          )}
        </Sequence>
      )}

      {/* ═══════ ③ PER-SEGMENT CUES (z-index 2+) ═══════ */}
      {typedManifest.map((seg, i) => {
        const from = titleCardDuration + frameStarts[i];
        const durationInFrames = frameStarts[i + 1] - frameStarts[i];
        
        const Scene = SCENE_COMPONENTS[seg.sceneType];
        const vCfg = seg.visualConfig as Record<string, unknown> | undefined;
        const showPiP = seg.visualType === "browser_broll" || seg.visualType === "remotion_chart" || seg.visualType === "stock_broll";

        return (
          <Sequence key={seg.id} from={from} durationInFrames={durationInFrames} layout="none">
            <div style={{ position: "relative", zIndex: 5 }}>
              <Scene durationInFrames={durationInFrames} props={seg.props} />
              <VisualOverlay visualType={seg.visualType} visualConfig={vCfg} />
            </div>
            <Audio src={staticFile(seg.audioFile)} />
            {showPiP && hasAvatarTrack() && avatarPath && (
              <Sequence from={from} durationInFrames={durationInFrames} layout="none">
                <ContinuousAvatarPiP src={staticFile(avatarPath)} layoutMode="broll_pip" />
              </Sequence>
            )}
          </Sequence>
        );
      })}

      <Captions />
    </AbsoluteFill>
  );
};
