import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";

export const DynamicChartSegment: React.FC<{ values?: number[]; labels?: string[] }> = ({ values = [], labels = [] }) => {
  const frame = useCurrentFrame();
  const max = Math.max(...values, 1);
  return <AbsoluteFill style={{ justifyContent: "center", padding: 80, gap: 16 }}>{values.map((value, index) => <div key={labels[index] ?? index} style={{ display: "flex", alignItems: "center", gap: 12, color: "white" }}><span style={{ width: 72 }}>{labels[index] ?? index + 1}</span><div style={{ height: 36, width: `${interpolate(frame, [0, 30], [0, value / max * 70], { extrapolateRight: "clamp" })}%`, background: "#f59e0b", borderRadius: 8 }} /></div>)}</AbsoluteFill>;
};
