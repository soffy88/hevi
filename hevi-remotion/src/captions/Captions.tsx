import { useMemo } from "react";
import {
  AbsoluteFill,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import manifest from "../data/run_manifest.json";
import { bodyFont, colors, scaled } from "../theme";

type Cue = {
  absStart: number;
  absEnd: number;
  text: string;
  keywords: string[];
};

const CUES: Cue[] = manifest.flatMap((seg) =>
  seg.captions.map((c) => ({
    absStart: seg.startSec + c.start,
    absEnd: seg.startSec + c.end,
    text: c.text,
    keywords: seg.keywords,
  })),
);

function splitKeywords(
  text: string,
  keywords: string[],
): { text: string; hl: boolean }[] {
  const matches: { start: number; end: number }[] = [];
  for (const kw of keywords) {
    if (!kw) continue;
    let from = 0;
    for (;;) {
      const idx = text.indexOf(kw, from);
      if (idx === -1) break;
      matches.push({ start: idx, end: idx + kw.length });
      from = idx + kw.length;
    }
  }
  matches.sort((a, b) => a.start - b.start);
  const parts: { text: string; hl: boolean }[] = [];
  let cursor = 0;
  for (const m of matches) {
    if (m.start < cursor) continue;
    if (m.start > cursor)
      parts.push({ text: text.slice(cursor, m.start), hl: false });
    parts.push({ text: text.slice(m.start, m.end), hl: true });
    cursor = m.end;
  }
  if (cursor < text.length) parts.push({ text: text.slice(cursor), hl: false });
  return parts;
}

export const Captions: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, width } = useVideoConfig();
  const t = frame / fps;

  const active = useMemo(
    () => CUES.find((c) => t >= c.absStart && t < c.absEnd),
    [t],
  );

  if (!active) return null;

  const cueFrame = (t - active.absStart) * fps;
  const cueDurationFrames = (active.absEnd - active.absStart) * fps;
  const opacity = interpolate(
    cueFrame,
    [0, 4, Math.max(cueDurationFrames - 4, 5), cueDurationFrames],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );
  const translateY = interpolate(cueFrame, [0, 6], [scaled(width, 14), 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const parts = splitKeywords(active.text, active.keywords);

  return (
    <AbsoluteFill
      style={{
        alignItems: "center",
        justifyContent: "flex-end",
        paddingBottom: scaled(width, 190),
      }}
    >
      <div
        style={{
          opacity,
          translate: `0px ${translateY}px`,
          maxWidth: "88%",
          textAlign: "center",
          fontFamily: bodyFont,
          fontWeight: 700,
          fontSize: scaled(width, 56),
          lineHeight: 1.35,
          color: colors.text,
          WebkitTextStroke: `${scaled(width, 8)}px rgba(0,0,0,0.55)`,
          paintOrder: "stroke fill",
          textShadow: "0 6px 18px rgba(0,0,0,0.55)",
        }}
      >
        {parts.map((p, i) => (
          <span key={i} style={{ color: p.hl ? colors.accent : colors.text }}>
            {p.text}
          </span>
        ))}
      </div>
    </AbsoluteFill>
  );
};
