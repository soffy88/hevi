import {Composition} from 'remotion';
import {JingKe} from './JingKe';

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="JingKe"
        component={JingKe}
        durationInFrames={1260}
        fps={30}
        width={1920}
        height={1080}
      />
    </>
  );
};
