import { AbsoluteFill } from "remotion";

export type SubtitleLine = { startMs: number; endMs: number; text: string; words?: unknown[] };
export const WordSubtitle: React.FC<{ lines: SubtitleLine[] }> = ({ lines }) => <AbsoluteFill style={{ alignItems: "center", justifyContent: "flex-end", paddingBottom: 180, pointerEvents: "none" }}><div style={{ color: "white", fontSize: 52, fontWeight: 700, textShadow: "0 3px 10px black" }}>{lines[0]?.text ?? ""}</div></AbsoluteFill>;
