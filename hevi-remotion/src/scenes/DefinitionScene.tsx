import { interpolate, useCurrentFrame } from "remotion";
import { colors, headingFont, bodyFont, emojiFont } from "../theme";
import type { DefinitionProps } from "../types";
import { FadeUp, IconCircle, SceneShell, Typewriter, useScaledSize } from "./common";

const QUESTION_OUT_R = 0.16;
const FORMULA_IN_R = 0.16;
const SINK_START_R = 0.44;
const SPLIT_R = 0.758;
const LINE_STAGGER_FRAMES = 75;

export const DefinitionScene: React.FC<{ durationInFrames: number; props: DefinitionProps }> = ({
  durationInFrames: D,
  props,
}) => {
  const frame = useCurrentFrame();
  const s = useScaledSize();

  const questionOutAt = Math.round(D * QUESTION_OUT_R);
  const formulaInAt = Math.round(D * FORMULA_IN_R);
  const sinkStart = Math.round(D * SINK_START_R);
  const splitAt = Math.round(D * SPLIT_R);

  const questionOut = interpolate(frame, [questionOutAt - 9, questionOutAt + 3], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const formulaIn = interpolate(frame, [formulaInAt, formulaInAt + 12], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const sinkProgress = interpolate(frame, [sinkStart, sinkStart + 70], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const splitIn = interpolate(frame, [splitAt, splitAt + 18], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const showQuestion = frame < questionOutAt + 3;
  const showFormula = frame >= formulaInAt && frame < splitAt;
  const showSplit = frame >= splitAt;

  return (
    <SceneShell durationInFrames={D}>
      {showQuestion && (
        <FadeUp
          delay={4}
          distance={20}
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <div
            style={{
              opacity: questionOut,
              fontFamily: headingFont,
              fontSize: s(96),
              color: colors.text,
              textAlign: "center",
              padding: `0 ${s(80)}px`,
            }}
          >
            {props.question}
          </div>
        </FadeUp>
      )}

      {showFormula && (
        <div
          style={{
            position: "absolute",
            inset: 0,
            opacity: formulaIn,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            gap: s(56),
            padding: `0 ${s(70)}px`,
          }}
        >
          <div
            style={{
              fontFamily: bodyFont,
              fontWeight: 900,
              fontSize: s(58),
              color: colors.text,
              textAlign: "center",
              lineHeight: 1.5,
            }}
          >
            <span style={{ color: colors.accent }}>{props.formulaHead}</span>
            {props.formulaLines.map((line, i) => (
              <span key={i}>
                <Typewriter
                  text={line}
                  delay={formulaInAt + 6 + i * LINE_STAGGER_FRAMES}
                  charsPerSecond={9}
                />
                {i < props.formulaLines.length - 1 && <br />}
              </span>
            ))}
          </div>

          <div
            style={{
              display: "flex",
              gap: s(90),
              opacity: interpolate(frame, [sinkStart - 10, sinkStart], [0, 1], {
                extrapolateLeft: "clamp",
                extrapolateRight: "clamp",
              }),
            }}
          >
            {props.sinkEmojis.map((emoji, i) => (
              <div
                key={emoji}
                style={{
                  translate: `0px ${sinkProgress * s(60)}px`,
                  scale: 1 - sinkProgress * 0.5,
                  opacity: 1 - sinkProgress,
                  rotate: `${sinkProgress * (i % 2 === 0 ? 180 : -180)}deg`,
                }}
              >
                <IconCircle emoji={emoji} size={s(120)} />
              </div>
            ))}
          </div>
        </div>
      )}

      {showSplit && (
        <div style={{ position: "absolute", inset: 0, display: "flex", opacity: splitIn }}>
          <div
            style={{
              flex: 1,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              gap: s(20),
              background: "rgba(255,255,255,0.02)",
            }}
          >
            <div style={{ fontSize: s(80), fontFamily: emojiFont }}>{props.splitLeft.emoji}</div>
            <div style={{ fontFamily: headingFont, fontSize: s(46), color: colors.textMuted }}>
              {props.splitLeft.title}
            </div>
            <div style={{ fontFamily: bodyFont, fontSize: s(30), color: colors.textMuted }}>
              {props.splitLeft.sub}
            </div>
          </div>
          <div style={{ width: 2, background: "rgba(255,255,255,0.12)" }} />
          <div
            style={{
              flex: 1,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              gap: s(20),
            }}
          >
            <div style={{ fontSize: s(80), fontFamily: emojiFont }}>{props.splitRight.emoji}</div>
            <div style={{ fontFamily: headingFont, fontSize: s(46), color: colors.accent }}>
              {props.splitRight.title}
            </div>
            <div style={{ fontFamily: bodyFont, fontSize: s(30), color: colors.text }}>
              {props.splitRight.sub}
            </div>
          </div>
        </div>
      )}
    </SceneShell>
  );
};
