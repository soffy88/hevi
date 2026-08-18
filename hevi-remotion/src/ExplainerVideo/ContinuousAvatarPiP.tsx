/** Continuous avatar: 300×300 circle, bottom-left. Production usually
composites this after Remotion; this component is for stamped studio/preview. */

import { OffthreadVideo } from "remotion";
import { AVATAR_PIP_MARGIN, AVATAR_PIP_SIZE } from "../theme";

interface ContinuousAvatarPiPProps {
  src?: string;
  /** Kept for callers; both modes are the reserved 300 circle. */
  layoutMode?: "fullscreen" | "broll_pip";
}

export const ContinuousAvatarPiP: React.FC<ContinuousAvatarPiPProps> = ({
  src,
}) => {
  if (!src) return null;

  return (
    <div
      style={{
        position: "absolute",
        left: AVATAR_PIP_MARGIN,
        bottom: AVATAR_PIP_MARGIN,
        width: AVATAR_PIP_SIZE,
        height: AVATAR_PIP_SIZE,
        zIndex: 10,
        borderRadius: "50%",
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
