import { interpolate, useCurrentFrame } from "remotion";
import { colors, headingFont, bodyFont, emojiFont } from "../theme";
import type { OutroProps } from "../types";
import { FadeUp, SceneShell, useScaledSize } from "./common";

const SETUP_OUT_R = 0.341;
const QUOTE_R = 0.373;
const QUOTE_LINE2_R = 0.572;
const CTA_R = 0.724;
const CTA_TEXT_R = 0.772;
const BYLINE_R = 0.84;

export const OutroScene: React.FC<{ durationInFrames: number; props: OutroProps }> = ({
  durationInFrames: D,
  props,
}) => {
  const frame = useCurrentFrame();
  const s = useScaledSize();

  const setupOutAt = Math.round(D * SETUP_OUT_R);
  const quoteAt = Math.round(D * QUOTE_R);
  const quoteLine2At = Math.round(D * QUOTE_LINE2_R);
  const ctaAt = Math.round(D * CTA_R);
  const ctaTextAt = Math.round(D * CTA_TEXT_R);
  const bylineAt = Math.round(D * BYLINE_R);

  const setupOut = interpolate(frame, [setupOutAt - 12, setupOutAt], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const quoteGlow = 0.2 + Math.sin(frame * 0.12) * 0.08;

  return (
    <SceneShell durationInFrames={D} fadeOutFrames={30}>
      {frame < setupOutAt && (
        <FadeUp
          delay={4}
          distance={16}
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            opacity: setupOut,
            padding: `0 ${s(100)}px`,
          }}
        >
          <div style={{ fontFamily: bodyFont, fontWeight: 700, fontSize: s(42), color: colors.text, textAlign: "center", lineHeight: 1.6 }}>
            {props.setupLine1}
            <br />
            {props.setupLine2}
          </div>
        </FadeUp>
      )}

      {frame >= setupOutAt && frame < ctaAt && (
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            gap: s(28),
            padding: `0 ${s(80)}px`,
          }}
        >
          <FadeUp delay={quoteAt} distance={20}>
            <div
              style={{
                fontFamily: headingFont,
                fontSize: s(70),
                color: colors.accent,
                textAlign: "center",
                textShadow: `0 0 ${s(70)}px rgba(255,201,74,${quoteGlow})`,
              }}
            >
              {props.quoteLine1}
            </div>
          </FadeUp>
          <FadeUp delay={quoteLine2At} distance={20}>
            <div style={{ fontFamily: headingFont, fontSize: s(70), color: colors.text, textAlign: "center" }}>
              {props.quoteLine2}
            </div>
          </FadeUp>
        </div>
      )}

      {frame >= ctaAt && (
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            gap: s(34),
          }}
        >
          <FadeUp delay={ctaAt} distance={16}>
            <div style={{ display: "flex", gap: s(28), fontSize: s(52), fontFamily: emojiFont }}>
              {props.ctaEmojis.map((e, i) => (
                <span key={i}>{e}</span>
              ))}
            </div>
          </FadeUp>
          <FadeUp delay={ctaTextAt} distance={12}>
            <div style={{ fontFamily: bodyFont, fontWeight: 700, fontSize: s(38), color: colors.text }}>
              {props.ctaText}
            </div>
          </FadeUp>
          <FadeUp delay={bylineAt} distance={12}>
            <div style={{ fontFamily: headingFont, fontSize: s(44), color: colors.textMuted }}>
              {props.byline}
            </div>
          </FadeUp>
        </div>
      )}
    </SceneShell>
  );
};
