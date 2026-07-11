import { useCurrentFrame } from "remotion";
import { colors, headingFont, bodyFont, emojiFont } from "../theme";
import type { CardsProps } from "../types";
import { FadeUp, Pop, SceneShell, fadeInOutOpacity, useScaledSize, useWobble } from "./common";

type Card = CardsProps["cards"][number];
type Window = { card: Card; start: number; end: number };

const CardSlot: React.FC<{ win: Window }> = ({ win }) => {
  const frame = useCurrentFrame();
  const s = useScaledSize();
  const wobble = useWobble(0.12, 2.2);
  const opacity = fadeInOutOpacity(frame, win.start, win.end, 14, 12);

  if (frame < win.start - 2 || frame > win.end + 2) return null;

  return (
    <Pop
      delay={win.start}
      style={{
        position: "absolute",
        inset: 0,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        opacity,
      }}
    >
      <div
        style={{
          rotate: `${wobble}deg`,
          background: colors.bgSoft,
          borderRadius: 40,
          padding: `${s(64)}px ${s(72)}px`,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: s(20),
          boxShadow: "0 24px 60px rgba(0,0,0,0.45)",
          minWidth: s(640),
        }}
      >
        <div style={{ fontSize: s(120), fontFamily: emojiFont }}>{win.card.emoji}</div>
        <div style={{ fontFamily: headingFont, fontSize: s(58), color: colors.accent }}>
          {win.card.title}
        </div>
        <div
          style={{
            fontFamily: bodyFont,
            fontWeight: 700,
            fontSize: s(36),
            color: colors.text,
            textAlign: "center",
            whiteSpace: "pre-line",
            lineHeight: 1.5,
          }}
        >
          {win.card.desc}
        </div>
      </div>
    </Pop>
  );
};

export const CardsScene: React.FC<{ durationInFrames: number; props: CardsProps }> = ({
  durationInFrames: D,
  props,
}) => {
  const s = useScaledSize();
  const n = props.cards.length;
  const slot = D / n;
  // 头部偏移/收边按 slot 比例缩放,保证旁白很短、slot 很小时 start 依然 < end
  // (固定的 40/6 帧偏移量在极短 slot 下会让窗口倒挂)。
  const headOffset = Math.min(40, Math.floor(slot * 0.3));
  const trim = Math.min(6, Math.floor(slot * 0.1));
  const windows: Window[] = props.cards.map((card, i) => ({
    card,
    start: Math.round(i * slot + (i === 0 ? headOffset : trim)),
    end: Math.round((i + 1) * slot - trim),
  }));

  return (
    <SceneShell durationInFrames={D}>
      <FadeUp
        delay={4}
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
        <CardSlot key={win.card.title} win={win} />
      ))}
    </SceneShell>
  );
};
