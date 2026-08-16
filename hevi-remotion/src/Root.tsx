import "./index.css";
import { Composition } from "remotion";
import { Zhibo } from "./Zhibo";
import { ExplainerVideo, getTotalDurationInFrames } from "./ExplainerVideo";
import { HandDrawnDiary, getHandDrawnDuration } from "./HandDrawnDiary/HandDrawnDiary";
import { PaperPromo, getPaperPromoDuration } from "./templates/PaperPromo/PaperPromo";

const FPS = 30;

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="Zhibo"
        component={Zhibo}
        durationInFrames={150}
        fps={30}
        width={1280}
        height={720}
      />
      <Composition
        id="Explainer-Portrait"
        component={ExplainerVideo}
        durationInFrames={getTotalDurationInFrames(FPS)}
        fps={FPS}
        width={1080}
        height={1920}
      />
      <Composition
        id="Explainer-Landscape"
        component={ExplainerVideo}
        durationInFrames={getTotalDurationInFrames(FPS)}
        fps={FPS}
        width={1920}
        height={1080}
      />
      {/* 3O 内化:手绘日记漫画(渲染契约:RENDER-CONTRACT.md) */}
      <Composition
        id="HandDrawn-Portrait"
        component={HandDrawnDiary}
        durationInFrames={getHandDrawnDuration([{ text: "示例拍" }], FPS)}
        fps={FPS}
        width={1080}
        height={1440}
        defaultProps={{
          beats: [
            { text: "王生慕道赴崂山,跪求道士收留。" },
            { text: "初遭拒绝,以死相誓,终获准入观。" },
          ],
          title: "崂山道士",
          transition: "cut",
        }}
      />
      {/* 3O 内化:产品宣传片模板(promo-energy-arc 序列) */}
      <Composition
        id="PaperPromo"
        component={PaperPromo}
        durationInFrames={getPaperPromoDuration(["核心功能一", "核心功能二"], FPS)}
        fps={FPS}
        width={1920}
        height={1080}
        defaultProps={{
          productName: "示例产品",
          tagline: "一切研究,一处汇聚",
          features: ["核心功能一", "核心功能二"],
          pages: [],
        }}
      />
    </>
  );
};
