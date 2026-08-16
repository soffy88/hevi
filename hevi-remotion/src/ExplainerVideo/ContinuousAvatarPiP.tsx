/** 🚨 v9.0: Continuous Avatar PiP Segment —— 全时段数字人画中画。

Renders the full-length talking face video, scaling to corner PiP
position when layout_mode === "broll_pip", or fullscreen otherwise.
Degrades gracefully (renders nothing) when src is empty / file missing.
*/

import { OffthreadVideo } from "remotion";

interface ContinuousAvatarPiPProps {
  src?: string;
  /** Current layout mode from timeline cue */
  layoutMode?: "fullscreen" | "broll_pip";
}

export const ContinuousAvatarPiP: React.FC<ContinuousAvatarPiPProps> = ({
  src,
  layoutMode = "fullscreen",
}) => {
  if (!src) return null;

  if (layoutMode === "fullscreen") {
    return (
      <div style={{ position: "absolute", zIndex: 1 }}>
        <OffthreadVideo
          src={src}
          style={{ width: "100%", height: "100%", objectFit: "cover" as const }}
        />
        <div
          style={{
            position: "absolute",
            inset: 0,
            pointerEvents: "none" as const,
            boxShadow: "inset 0 0 60px rgba(108,99,255,0.08)",
          }}
        />
      </div>
    );
  }

  // broll_pip — presenter in bottom-right corner
  return (
    <div
      style={{
        position: "absolute",
        right: 24,
        bottom: 24,
        width: "clamp(200px, 25vw, 280px)",
        aspectRatio: "9/16",
        zIndex: 10,
        borderRadius: 20,
        overflow: "hidden",
        border: "2px solid rgba(108,99,255,0.35)",
        boxShadow: "0 8px 32px rgba(0,0,0,0.5), 0 0 40px rgba(108,99,255,0.12)",
      }}
    >
      <OffthreadVideo
        src={src}
        style={{ width: "100%", height: "100%", objectFit: "cover" as const }}
      />
    </div>
  );
};
