import { interpolate, useCurrentFrame } from "remotion";
import { colors, headingFont } from "../theme";
import type { HookProps } from "../types";
import { FadeUp, IconCircle, SceneShell, useScaledSize } from "./common";

// 比例锚点来自"沉没成本"首个真实分镜的实测节拍(itemsStart/shatter/title/sub),
// 按 durationInFrames 缩放,泛化到任意时长的钩子文案。
const ITEMS_START_R = 0.11;
const SHATTER_R = 0.5;
const TITLE_R = 0.84;
const SUB_R = 0.91;

const Fragment: React.FC<{ delay: number; angle: number; distance: number; size: number }> = ({
  delay,
  angle,
  distance,
  size,
}) => {
  const frame = useCurrentFrame();
  const p = interpolate(frame, [delay, delay + 26], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const opacity = interpolate(frame, [delay, delay + 8, delay + 26], [0, 1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const rad = (angle * Math.PI) / 180;
  const x = Math.cos(rad) * distance * p;
  const y = Math.sin(rad) * distance * p + p * p * 90;

  return (
    <div
      style={{
        position: "absolute",
        width: size,
        height: size * 0.6,
        background: colors.textMuted,
        opacity,
        translate: `${x}px ${y}px`,
        rotate: `${angle + p * 200}deg`,
        borderRadius: 6,
      }}
    />
  );
};

export const HookScene: React.FC<{ durationInFrames: number; props: HookProps }> = ({
  durationInFrames: D,
  props,
}) => {
  const frame = useCurrentFrame();
  const s = useScaledSize();

  const itemsStart = Math.round(D * ITEMS_START_R);
  const shatterAt = Math.round(D * SHATTER_R);
  const titleAt = Math.round(D * TITLE_R);
  const subAt = Math.round(D * SUB_R);

  const wobble = Math.sin(frame * 0.4) * (frame < shatterAt ? 2.5 : 0);
  const cardsOpacity = interpolate(frame, [shatterAt - 4, shatterAt + 18], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const cardsFall = interpolate(frame, [shatterAt - 10, shatterAt + 30], [0, s(140)], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const titleScale = interpolate(frame, [titleAt, titleAt + 14], [0.7, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const titleOpacity = interpolate(frame, [titleAt, titleAt + 14], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <SceneShell durationInFrames={D}>
      <div
        style={{
          position: "absolute",
          top: "34%",
          left: 0,
          right: 0,
          display: "flex",
          justifyContent: "center",
          gap: s(56),
          opacity: frame < shatterAt + 30 ? cardsOpacity : 0,
          translate: `0px ${cardsFall}px`,
        }}
      >
        {props.items.map((it, i) => (
          <FadeUp key={it.label} delay={itemsStart + i * 10} distance={40}>
            <div
              style={{
                rotate: `${wobble * (i === 0 ? 1 : -1)}deg`,
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                gap: s(10),
              }}
            >
              <IconCircle emoji={it.emoji} size={s(150)} />
              {it.cost && (
                <div style={{ fontFamily: headingFont, fontSize: s(40), color: colors.accent }}>
                  {it.cost}
                </div>
              )}
            </div>
          </FadeUp>
        ))}
      </div>

      {frame >= shatterAt - 4 && frame < shatterAt + 40 && (
        <div style={{ position: "absolute", top: "34%", left: "50%", width: 0, height: 0 }}>
          {Array.from({ length: 10 }).map((_, i) => (
            <Fragment
              key={i}
              delay={shatterAt}
              angle={(360 / 10) * i}
              distance={s(220)}
              size={s(28)}
            />
          ))}
        </div>
      )}

      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: s(24),
        }}
      >
        <div
          style={{
            opacity: titleOpacity,
            scale: titleScale,
            fontFamily: headingFont,
            fontSize: s(140),
            color: colors.text,
            textAlign: "center",
            textShadow: `0 0 ${s(60)}px rgba(255,201,74,0.25)`,
          }}
        >
          {props.title}
        </div>
        <FadeUp delay={subAt} distance={16}>
          <div style={{ fontFamily: headingFont, fontSize: s(48), color: colors.danger }}>
            {props.subtitle}
          </div>
        </FadeUp>
      </div>
    </SceneShell>
  );
};
