export type HookProps = {
  title: string;
  subtitle: string;
  items: { emoji: string; label: string; cost?: string }[];
};

export type DefinitionProps = {
  question: string;
  formulaHead: string;
  formulaLines: string[];
  sinkEmojis: string[];
  splitLeft: { emoji: string; title: string; sub: string };
  splitRight: { emoji: string; title: string; sub: string };
};

export type CardsProps = {
  header: string;
  cards: { emoji: string; title: string; desc: string }[];
};

export type ReasonProps = {
  question: string;
  brainLine: string;
  bubbleText: string;
  leftLabel: { title: string; sub: string };
  rightLabel: { title: string; sub: string };
};

export type MethodProps = {
  header: string;
  points: { num: string; title: string; sub: string }[];
};

export type OutroProps = {
  setupLine1: string;
  setupLine2: string;
  quoteLine1: string;
  quoteLine2: string;
  ctaEmojis: string[];
  ctaText: string;
  byline: string;
};

export type SceneProps =
  | HookProps
  | DefinitionProps
  | CardsProps
  | ReasonProps
  | MethodProps
  | OutroProps;

export type SceneType = "hook" | "definition" | "cards" | "reason" | "method" | "outro";

export type CaptionCue = { text: string; start: number; end: number };

export type ManifestSegment = {
  id: string;
  sceneType: SceneType;
  props: SceneProps;
  keywords: string[];
  audioFile: string;
  durationSec: number;
  startSec: number;
  captions: CaptionCue[];
};

export type RunManifest = ManifestSegment[];
