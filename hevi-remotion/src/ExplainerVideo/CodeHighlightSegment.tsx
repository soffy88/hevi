import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";

export const CodeHighlightSegment: React.FC<{ codeText?: string; language?: string }> = ({ codeText = "", language = "text" }) => {
  const frame = useCurrentFrame();
  const visible = Math.floor(interpolate(frame, [0, 60], [0, codeText.length], { extrapolateRight: "clamp" }));
  return <AbsoluteFill style={{ padding: 64, color: "#d1fae5", background: "#111827", fontFamily: "monospace", fontSize: 28 }}><div style={{ color: "#f59e0b", marginBottom: 18 }}>{language}</div><pre>{codeText.slice(0, visible)}</pre></AbsoluteFill>;
};
