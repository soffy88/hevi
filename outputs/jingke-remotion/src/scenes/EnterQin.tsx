import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';

export const EnterQin: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();

  // 荆轲从门口走向宫殿中央
  const personY = interpolate(frame, [0, 80], [height - 200, height - 400], {
    extrapolateRight: 'clamp',
  });
  const personScale = interpolate(frame, [0, 80], [0.5, 1.2], {
    extrapolateRight: 'clamp',
  });

  // 宫殿柱子
  const pillars = [
    {x: 200, height: 600},
    {x: 500, height: 650},
    {x: 800, height: 700},
    {x: 1100, height: 650},
    {x: 1400, height: 600},
    {x: 1700, height: 550},
  ];

  const titleOpacity = spring({frame: frame - 20, fps, config: {damping: 20}});

  return (
    <AbsoluteFill style={{
      background: 'linear-gradient(180deg, #2a1a0a 0%, #3a2a1a 50%, #1a0a00 100%)',
    }}>
      {/* 宫殿柱子 */}
      <svg width={width} height={height} style={{position: 'absolute'}}>
        {pillars.map((pillar, i) => (
          <g key={i}>
            <rect
              x={pillar.x}
              y={height - pillar.height}
              width={60}
              height={pillar.height}
              fill="#4a3a2a"
              stroke="#2a1a0a"
              strokeWidth={2}
            />
            {/* 柱顶 */}
            <rect
              x={pillar.x - 20}
              y={height - pillar.height - 20}
              width={100}
              height={30}
              fill="#5a4a3a"
            />
          </g>
        ))}
      </svg>

      {/* 荆轲剪影 */}
      <svg width={width} height={height} style={{position: 'absolute'}}>
        <g transform={`translate(${width / 2}, ${personY}) scale(${personScale})`}>
          <ellipse cx={0} cy={0} rx={35} ry={70} fill="#0a0a0a" />
          <circle cx={0} cy={-100} r={25} fill="#0a0a0a" />
          <rect x={-15} y={-130} width={30} height={20} fill="#0a0a0a" />
        </g>
      </svg>

      {/* 标题 */}
      <div style={{
        position: 'absolute',
        top: 150,
        width: '100%',
        textAlign: 'center',
        opacity: titleOpacity,
      }}>
        <div style={{
          fontSize: 80,
          fontWeight: 'bold',
          color: '#d4af37',
          textShadow: '0 0 20px rgba(212, 175, 55, 0.5)',
        }}>
          入秦宫
        </div>
        <div style={{
          fontSize: 36,
          color: '#aa8844',
          marginTop: 20,
        }}>
          携督亢地图与樊於期首级
        </div>
      </div>
    </AbsoluteFill>
  );
};
