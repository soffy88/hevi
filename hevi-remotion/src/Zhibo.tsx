import {
  AbsoluteFill,
  Easing,
  Sequence,
  interpolate,
  useCurrentFrame,
} from "remotion";
import { loadFont as loadMaShanZheng } from "@remotion/google-fonts/MaShanZheng";
import { loadFont as loadNotoSerifSC } from "@remotion/google-fonts/NotoSerifSC";

const { fontFamily: brushFont } = loadMaShanZheng("normal", {
  weights: ["400"],
  subsets: ["chinese-simplified"],
});
const { fontFamily: serifFont } = loadNotoSerifSC("normal", {
  weights: ["400", "600"],
  subsets: ["chinese-simplified"],
});

const NAME = "智伯";
const ERA = "战国 · 晋";
const APPEARANCE = "四十余岁 · 魁伟美髯 · 玄色深衣";

const Background: React.FC = () => {
  const frame = useCurrentFrame();
  const scale = interpolate(frame, [0, 150], [1, 1.06], {
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill
      style={{
        scale,
        background:
          "radial-gradient(circle at 50% 42%, #2b2b28 0%, #1a1a18 45%, #0c0c0b 100%)",
      }}
    >
      <AbsoluteFill
        style={{
          background:
            "repeating-linear-gradient(115deg, rgba(255,255,255,0.015) 0px, rgba(255,255,255,0.015) 2px, transparent 2px, transparent 6px)",
        }}
      />
      <AbsoluteFill
        style={{
          boxShadow: "inset 0 0 260px 90px rgba(0,0,0,0.85)",
        }}
      />
    </AbsoluteFill>
  );
};

const Title: React.FC = () => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [5, 35], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.16, 1, 0.3, 1),
  });
  const scale = interpolate(frame, [5, 40], [0.88, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.16, 1, 0.3, 1),
  });

  return (
    <div
      style={{
        opacity,
        scale,
        fontFamily: brushFont,
        fontSize: 220,
        color: "#e8e2d0",
        letterSpacing: 12,
        textShadow: "0 0 60px rgba(0,0,0,0.6)",
      }}
    >
      {NAME}
    </div>
  );
};

const Era: React.FC = () => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [0, 25], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.16, 1, 0.3, 1),
  });
  const translateY = interpolate(frame, [0, 25], [16, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.16, 1, 0.3, 1),
  });

  return (
    <div
      style={{
        opacity,
        translate: `0px ${translateY}px`,
        fontFamily: serifFont,
        fontWeight: 600,
        fontSize: 42,
        color: "#c9a86a",
        letterSpacing: 6,
      }}
    >
      {ERA}
    </div>
  );
};

const Appearance: React.FC = () => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [0, 25], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.16, 1, 0.3, 1),
  });
  const translateY = interpolate(frame, [0, 25], [16, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.16, 1, 0.3, 1),
  });

  return (
    <div
      style={{
        opacity,
        translate: `0px ${translateY}px`,
        fontFamily: serifFont,
        fontWeight: 400,
        fontSize: 32,
        color: "#a6a196",
        letterSpacing: 3,
      }}
    >
      {APPEARANCE}
    </div>
  );
};

const Seal: React.FC = () => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [90, 115], [0, 0.9], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <div
      style={{
        position: "absolute",
        right: 90,
        bottom: 90,
        opacity,
        width: 64,
        height: 64,
        background: "#8c2b22",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontFamily: brushFont,
        fontSize: 30,
        color: "#f2e6d8",
      }}
    >
      智
    </div>
  );
};

export const Zhibo: React.FC = () => {
  return (
    <AbsoluteFill>
      <Background />
      <AbsoluteFill
        style={{
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 28,
          }}
        >
          <Title />
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: 14,
            }}
          >
            <Sequence from={45} layout="none">
              <Era />
            </Sequence>
            <Sequence from={70} layout="none">
              <Appearance />
            </Sequence>
          </div>
        </div>
      </AbsoluteFill>
      <Seal />
    </AbsoluteFill>
  );
};
