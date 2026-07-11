import { interpolate, useCurrentFrame } from "remotion";
import { colors, headingFont, bodyFont, emojiFont } from "../theme";
import type { MethodProps } from "../types";
import { FadeUp, Pop, SceneShell, fadeInOutOpacity, useScaledSize } from "./common";

type Point = MethodProps["points"][number];
type Window = { point: Point; start: number; end: number };

const NUM_R = 0.02;
const TITLE_R = 0.14;
const SUB_R = 0.42;
const CHECK_R = 0.88;

const PointSlot: React.FC<{ win: Window }> = ({ win }) => {
  const frame = useCurrentFrame();
  const s = useScaledSize();
  const span = win.end - win.start;
  if (frame < win.start - 2 || frame > win.end + 2) return null;

  const opacity = fadeInOutOpacity(frame, win.start, win.end, 12, 10);
  const checkAt = win.start + Math.round(span * CHECK_R);
  const checkScale = interpolate(frame, [checkAt, checkAt + 12], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        opacity,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: s(36),
        padding: `0 ${s(90)}px`,
      }}
    >
      <Pop delay={win.start + Math.round(span * NUM_R)} fromScale={0.5}>
        <div
          style={{
            width: s(110),
            height: s(110),
            borderRadius: s(55),
            background: colors.accent,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontFamily: headingFont,
            fontSize: s(60),
            color: colors.bg,
          }}
        >
          {win.point.num}
        </div>
      </Pop>

      <div style={{ textAlign: "center" }}>
        <FadeUp delay={win.start + Math.round(span * TITLE_R)} distance={14}>
          <div style={{ fontFamily: bodyFont, fontWeight: 700, fontSize: s(46), color: colors.text }}>
            {win.point.title}
          </div>
        </FadeUp>
        <FadeUp
          delay={win.start + Math.round(span * SUB_R)}
          distance={14}
          style={{ marginTop: s(14) }}
        >
          <div style={{ fontFamily: bodyFont, fontWeight: 900, fontSize: s(50), color: colors.accent }}>
            {win.point.sub}
          </div>
        </FadeUp>
      </div>

      <div style={{ scale: checkScale, fontSize: s(90), fontFamily: emojiFont }}>✅</div>
    </div>
  );
};

export const MethodScene: React.FC<{ durationInFrames: number; props: MethodProps }> = ({
  durationInFrames: D,
  props,
}) => {
  const s = useScaledSize();
  const n = props.points.length;
  const slot = D / n;
  const headOffset = Math.min(2, Math.floor(slot * 0.3));
  const windows: Window[] = props.points.map((point, i) => ({
    point,
    start: Math.round(i * slot + (i === 0 ? headOffset : 0)),
    end: Math.round((i + 1) * slot),
  }));

  return (
    <SceneShell durationInFrames={D}>
      <FadeUp
        delay={2}
        distance={16}
        style={{
          position: "absolute",
          top: s(90),
          left: 0,
          right: 0,
          textAlign: "center",
          fontFamily: headingFont,
          fontSize: s(46),
          color: colors.textMuted,
        }}
      >
        {props.header}
      </FadeUp>

      {windows.map((win) => (
        <PointSlot key={win.point.num} win={win} />
      ))}
    </SceneShell>
  );
};
