import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';

export const Chase: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();

  // 两人绕柱追逐
  const angle = frame * 5;
  const centerX = width / 2;
  const centerY = height / 2;
  const radius = 200;

  const jingkeX = centerX + Math.cos((angle * Math.PI) / 180) * radius;
  const jingkeY = centerY + Math.sin((angle * Math.PI) / 180) * radius * 0.5;

  const qinwangX = centerX + Math.cos(((angle + 180) * Math.PI) / 180) * radius;
  const qinwangY = centerY + Math.sin(((angle + 180) * Math.PI) / 180) * radius * 0.5;

  const titleOpacity = spring({frame: frame - 10, fps, config: {damping: 20}});

  return (
    <AbsoluteFill style={{
      background: 'linear-gradient(180deg, #0a0a2a 0%, #1a1a4a 50%, #0a0a1a 100%)',
    }}>
      {/* 宫殿柱子 */}
      <svg width={width} height={height} style={{position: 'absolute'}}>
        <rect
          x={centerX - 40}
          y={height / 2 - 200}
          width={80}
          height={400}
          fill="#4a3a2a"
          stroke="#2a1a0a"
          strokeWidth={3}
        />
        <rect
          x={centerX - 60}
          y={height / 2 - 220}
          width={120}
          height={30}
          fill="#5a4a3a"
        />
      </svg>

      {/* 荆轲 */}
      <svg width={width} height={height} style={{position: 'absolute'}}>
        <g transform={`translate(${jingkeX}, ${jingkeY})`}>
          <ellipse cx={0} cy={0} rx={30} ry={60} fill="#0a0a0a" />
          <circle cx={0} cy={-85} r={22} fill="#0a0a0a" />
          {/* 匕首 */}
          <polygon
            points="25,-20 35,-20 32,10 28,10"
            fill="#c0c0c0"
            transform={`rotate(${angle})`}
          />
        </g>
      </svg>

      {/* 秦王 */}
      <svg width={width} height={height} style={{position: 'absolute'}}>
        <g transform={`translate(${qinwangX}, ${qinwangY})`}>
          <ellipse cx={0} cy={0} rx={35} ry={70} fill="#1a1a1a" />
          <circle cx={0} cy={-100} r={25} fill="#1a1a1a" />
          {/* 王冠 */}
          <polygon
            points="-20,-130 20,-130 15,-150 -15,-150"
            fill="#d4af37"
          />
        </g>
      </svg>

      {/* 标题 */}
      <div style={{
        position: 'absolute',
        top: 100,
        width: '100%',
        textAlign: 'center',
        opacity: titleOpacity,
      }}>
        <div style={{
          fontSize: 80,
          fontWeight: 'bold',
          color: '#4488ff',
          textShadow: '0 0 30px rgba(68, 136, 255, 0.8)',
        }}>
          逐秦王
        </div>
        <div style={{
          fontSize: 36,
          color: '#88aaff',
          marginTop: 20,
        }}>
          二人绕柱而走
        </div>
      </div>

      {/* 紧张氛围文字 */}
      {frame > 60 && (
        <div style={{
          position: 'absolute',
          bottom: 150,
          width: '100%',
          textAlign: 'center',
          opacity: spring({frame: frame - 60, fps}),
        }}>
          <div style={{
            fontSize: 36,
            color: '#ffffff',
          }}>
            群臣愕然 莫知所为
          </div>
        </div>
      )}
    </AbsoluteFill>
  );
};
