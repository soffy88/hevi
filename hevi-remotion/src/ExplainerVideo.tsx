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
import { DynamicChartSegment } from "./ExplainerVideo/DynamicChartSegment";
import { HeyGenAvatarSegment } from "./ExplainerVideo/HeyGenAvatarSegment";
import { WordSubtitle, type SubtitleLine } from "./ExplainerVideo/WordSubtitle";
import type {
  RunManifest,
  SceneProps,
  SceneType,
} from "./types";

const typedManifest = manifest as unknown as RunManifest;

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
    return (
      <div style={{ position: "absolute", right: 48, top: 48, width: 260, height: 260, overflow: "hidden", borderRadius: "50%", border: "2px solid rgba(255,255,255,.28)" }}>
        <HeyGenAvatarSegment src={assetSrc ?? undefined} circle presenterName={presenterName} />
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
          objectFit: "cover",
          borderRadius: visualType === "heygen_avatar" && visualConfig?.circle_avatar_mask !== false ? "50%" : 24,
          border: "2px solid rgba(255,255,255,.28)",
        }}
      />
    );
  }
  const labels: Record<string, string> = {
    heygen_avatar: "数字人 · 自动出镜",
    broll_news: "B-ROLL · 新闻素材",
    broll_stock: "B-ROLL · 素材",
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

  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      {typedManifest.map((seg, i) => {
        const from = frameStarts[i];
        const durationInFrames = frameStarts[i + 1] - from;
        const Scene = SCENE_COMPONENTS[seg.sceneType];
        return (
          <Sequence
            key={seg.id}
            from={from}
            durationInFrames={durationInFrames}
            layout="none"
          >
            <Scene durationInFrames={durationInFrames} props={seg.props} />
            <VisualOverlay visualType={seg.visualType} visualConfig={seg.visualConfig} />
            <Audio src={staticFile(seg.audioFile)} />
          </Sequence>
        );
      })}

      <Captions />
    </AbsoluteFill>
  );
};
