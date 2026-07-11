import { interpolate, useCurrentFrame } from "remotion";
import { colors, headingFont, bodyFont, emojiFont } from "../theme";
import type { ReasonProps } from "../types";
import { FadeUp, Pop, SceneShell, useScaledSize } from "./common";

const PHASE_B_R = 0.393;
const PHASE_C_R = 0.654;

export const ReasonScene: React.FC<{ durationInFrames: number; props: ReasonProps }> = ({
  durationInFrames: D,
  props,
}) => {
  const frame = useCurrentFrame();
  const s = useScaledSize();

  const phaseBAt = Math.round(D * PHASE_B_R);
  const phaseCAt = Math.round(D * PHASE_C_R);

  const phaseA = frame < phaseBAt;
  const phaseB = frame >= phaseBAt && frame < phaseCAt;
  const phaseC = frame >= phaseCAt;

  const brainPulse = 1 + Math.sin(frame * 0.25) * 0.06;
  const brainShake = phaseB ? Math.sin(frame * 0.7) * 6 : 0;

  const scaleTilt = interpolate(frame, [phaseCAt, phaseCAt + Math.round(D * 0.136)], [0, 14], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const stampScale = interpolate(
    frame,
    [phaseCAt + Math.round(D * 0.086), phaseCAt + Math.round(D * 0.126)],
    [2.2, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );
  const stampOpacity = interpolate(
    frame,
    [phaseCAt + Math.round(D * 0.086), phaseCAt + Math.round(D * 0.116)],
    [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );

  return (
    <SceneShell durationInFrames={D}>
      <FadeUp
        delay={4}
        distance={16}
        style={{
          position: "absolute",
          top: s(110),
          left: 0,
          right: 0,
          textAlign: "center",
          fontFamily: headingFont,
          fontSize: s(52),
          color: colors.text,
        }}
      >
        {props.question}
      </FadeUp>

      {(phaseA || phaseB) && (
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            gap: s(28),
          }}
        >
          <div
            style={{
              fontSize: s(190),
              fontFamily: emojiFont,
              scale: brainPulse,
              rotate: `${brainShake}deg`,
            }}
          >
            🧠
          </div>
          {phaseA && (
            <FadeUp delay={Math.round(D * 0.158)} distance={14}>
              <div style={{ fontFamily: bodyFont, fontWeight: 700, fontSize: s(42), color: colors.text }}>
                {props.brainLine}
              </div>
            </FadeUp>
          )}
          {phaseB && (
            <Pop delay={phaseBAt}>
              <div
                style={{
                  background: colors.bgSoft,
                  borderRadius: 24,
                  padding: `${s(20)}px ${s(36)}px`,
                  fontFamily: headingFont,
                  fontSize: s(44),
                  color: colors.danger,
                }}
              >
                {props.bubbleText}
              </div>
            </Pop>
          )}
        </div>
      )}

      {phaseC && (
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            gap: s(36),
          }}
        >
          <div style={{ position: "relative" }}>
            <div style={{ fontSize: s(220), fontFamily: emojiFont, rotate: `${scaleTilt}deg` }}>
              ⚖️
            </div>
            <div
              style={{
                position: "absolute",
                top: "8%",
                left: "-18%",
                opacity: stampOpacity,
                scale: stampScale,
                fontSize: s(140),
                color: colors.danger,
              }}
            >
              ✗
            </div>
          </div>

          <div style={{ display: "flex", gap: s(90) }}>
            <FadeUp delay={phaseCAt + Math.round(D * 0.027)} distance={10}>
              <div style={{ fontFamily: bodyFont, fontWeight: 700, fontSize: s(32), color: colors.danger, textAlign: "center" }}>
                {props.leftLabel.title}
                <br />
                <span style={{ fontSize: s(26), color: colors.textMuted }}>{props.leftLabel.sub}</span>
              </div>
            </FadeUp>
            <FadeUp delay={phaseCAt + Math.round(D * 0.052)} distance={10}>
              <div style={{ fontFamily: bodyFont, fontWeight: 700, fontSize: s(32), color: colors.success, textAlign: "center" }}>
                {props.rightLabel.title}
                <br />
                <span style={{ fontSize: s(26), color: colors.textMuted }}>{props.rightLabel.sub}</span>
              </div>
            </FadeUp>
          </div>
        </div>
      )}
    </SceneShell>
  );
};
