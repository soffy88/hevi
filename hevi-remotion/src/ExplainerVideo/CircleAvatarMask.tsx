import { AbsoluteFill, Img } from "remotion";

export const CircleAvatarMask: React.FC<{ avatarImg?: string; position?: "bottom-right" | "bottom-left" }> = ({ avatarImg, position = "bottom-right" }) => {
  if (!avatarImg) return null;
  return <AbsoluteFill style={{ alignItems: position === "bottom-right" ? "flex-end" : "flex-start", justifyContent: "flex-end", padding: 48, pointerEvents: "none" }}><Img src={avatarImg} style={{ width: 180, height: 180, borderRadius: "50%", objectFit: "cover", border: "4px solid white" }} /></AbsoluteFill>;
};
