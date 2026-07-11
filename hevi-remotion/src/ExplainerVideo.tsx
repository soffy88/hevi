import { Audio } from "@remotion/media";
import { AbsoluteFill, Sequence, staticFile, useVideoConfig } from "remotion";
import { Captions } from "./captions/Captions";
import manifest from "./data/run_manifest.json";
import { CardsScene } from "./scenes/CardsScene";
import { DefinitionScene } from "./scenes/DefinitionScene";
import { HookScene } from "./scenes/HookScene";
import { MethodScene } from "./scenes/MethodScene";
import { OutroScene } from "./scenes/OutroScene";
import { ReasonScene } from "./scenes/ReasonScene";
import type {
  CardsProps,
  DefinitionProps,
  HookProps,
  MethodProps,
  OutroProps,
  ReasonProps,
  RunManifest,
  SceneType,
} from "./types";

const typedManifest = manifest as unknown as RunManifest;

const SCENE_COMPONENTS: Record<
  SceneType,
  React.FC<{ durationInFrames: number; props: any }>
> = {
  hook: HookScene as React.FC<{ durationInFrames: number; props: HookProps }>,
  definition: DefinitionScene as React.FC<{
    durationInFrames: number;
    props: DefinitionProps;
  }>,
  cards: CardsScene as React.FC<{
    durationInFrames: number;
    props: CardsProps;
  }>,
  reason: ReasonScene as React.FC<{
    durationInFrames: number;
    props: ReasonProps;
  }>,
  method: MethodScene as React.FC<{
    durationInFrames: number;
    props: MethodProps;
  }>,
  outro: OutroScene as React.FC<{
    durationInFrames: number;
    props: OutroProps;
  }>,
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
            <Audio src={staticFile(seg.audioFile)} />
          </Sequence>
        );
      })}

      <Captions />
    </AbsoluteFill>
  );
};
