import { OffthreadVideo } from "remotion";

export const HeyGenAvatarSegment: React.FC<{ src?: string; circle?: boolean }> = ({ src, circle = false }) => (
  src ? <OffthreadVideo src={src} style={{ width: "100%", height: "100%", objectFit: "cover", borderRadius: circle ? "50%" : 0 }} /> : null
);
