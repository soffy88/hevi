import { AbsoluteFill, OffthreadVideo } from "remotion";

export const BrowserBrollSegment: React.FC<{ src?: string; zoomEffect?: boolean }> = ({ src, zoomEffect = true }) => (
  src ? (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <OffthreadVideo
        src={src}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
          transform: zoomEffect ? "scale(1.03)" : undefined,
        }}
      />
    </AbsoluteFill>
  ) : null
);
