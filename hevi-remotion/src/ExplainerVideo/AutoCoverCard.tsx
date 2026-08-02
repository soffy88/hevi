import { AbsoluteFill } from "remotion";

export const AutoCoverCard: React.FC<{ title: string; subtitle?: string }> = ({ title, subtitle }) => <AbsoluteFill style={{ background: "#111827", color: "white", alignItems: "center", justifyContent: "center", padding: 80, textAlign: "center" }}><div style={{ fontSize: 80, fontWeight: 900 }}>{title}</div><div style={{ marginTop: 24, fontSize: 32 }}>{subtitle}</div></AbsoluteFill>;
