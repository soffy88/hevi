import { Video } from "@remotion/media";
import { Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";

export const HeyGenAvatarSegment: React.FC<{
  src?: string;
  circle?: boolean;
  presenterName?: string;
}> = ({ src, circle = false, presenterName = "HEVI 数字人" }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  if (src) {
    return <Video src={src} objectFit="cover" style={{ width: "100%", height: "100%", borderRadius: circle ? "50%" : 0 }} />;
  }

  const cycle = frame % Math.max(1, fps * 2);
  const glowOpacity = interpolate(cycle, [0, fps, fps * 2], [0.28, 0.68, 0.28], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <div style={{
      width: "100%",
      height: "100%",
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      justifyContent: "center",
      gap: 12,
      overflow: "hidden",
      borderRadius: circle ? "50%" : 0,
      color: "white",
      background: "radial-gradient(circle at 50% 30%, #4655d8 0%, #171a46 48%, #090b1f 100%)",
      scale: interpolate(frame, [0, Math.round(fps * 0.45)], [0.88, 1], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
        easing: Easing.bezier(0.16, 1, 0.3, 1),
      }),
    }}>
      <div style={{
        position: "absolute",
        width: 210,
        height: 210,
        borderRadius: "50%",
        border: "5px solid #8ea2ff",
        opacity: glowOpacity,
        scale: interpolate(cycle, [0, fps, fps * 2], [0.9, 1.04, 0.9]),
      }} />
      <div style={{ width: 72, height: 72, borderRadius: "50%", background: "linear-gradient(145deg, #f6d2bc, #bc7c70)", boxShadow: "0 10px 28px rgba(0,0,0,.28)" }} />
      <div style={{ width: 132, height: 72, marginTop: -10, borderRadius: "70px 70px 24px 24px", background: "linear-gradient(145deg, #7f8cff, #3c48b8)", boxShadow: "0 12px 28px rgba(0,0,0,.3)" }} />
      <div style={{ maxWidth: 200, padding: "6px 12px", overflow: "hidden", borderRadius: 999, color: "#fff", background: "rgba(7,9,27,.72)", fontSize: 26, fontWeight: 800, lineHeight: 1.1, textAlign: "center", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {presenterName}
      </div>
    </div>
  );
};
