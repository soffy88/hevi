import {Composition, Sequence} from 'remotion';
import {Farewell} from './scenes/Farewell';
import {EnterQin} from './scenes/EnterQin';
import {DaggerRevealed} from './scenes/DaggerRevealed';
import {Chase} from './scenes/Chase';
import {Finale} from './scenes/Finale';

export const JingKe: React.FC = () => {
  return (
    <>
      {/* Scene 1: 易水送别 - 8秒 */}
      <Sequence from={0} durationInFrames={240}>
        <Farewell />
      </Sequence>

      {/* Scene 2: 入秦宫 - 8秒 */}
      <Sequence from={240} durationInFrames={240}>
        <EnterQin />
      </Sequence>

      {/* Scene 3: 图穷匕见 - 8秒 */}
      <Sequence from={480} durationInFrames={240}>
        <DaggerRevealed />
      </Sequence>

      {/* Scene 4: 逐秦王 - 8秒 */}
      <Sequence from={720} durationInFrames={240}>
        <Chase />
      </Sequence>

      {/* Scene 5: 英雄落幕 - 10秒 */}
      <Sequence from={960} durationInFrames={300}>
        <Finale />
      </Sequence>
    </>
  );
};

// 总时长: 1260 frames = 42秒 (30fps)
