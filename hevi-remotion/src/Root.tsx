import "./index.css";
import { Composition } from "remotion";
import { Zhibo } from "./Zhibo";
import { ExplainerVideo, getTotalDurationInFrames } from "./ExplainerVideo";

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
    </>
  );
};
