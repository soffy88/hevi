'use client';

import { useEffect, useRef, useState } from 'react';
import { proStudioApi } from '@/lib/api-client';

/**
 * LiveTalking(github.com/lipku/LiveTalking) 两种场景的前端入口。
 *
 * 跟上面 Card 2(Duix)不是同一套契约, 不能共用状态机——见后端
 * hevi/digital_human/livetalking_service.py 文件头。
 * - WebRTC 按需会话: 浏览器自己跑 RTCPeerConnection, 没有共享 stream_url,
 *   拿到 answer 就直接建立点对点连接, 在 <video> 里播放收到的媒体流。
 * - RTMP 固定频道: 运维管的常驻进程, 前端只做只读状态展示, 不提供开关按钮
 *   (那个按钮点了也没有对应的后端接口)。
 */
export function LiveTalkingPanel() {
  return (
    <section className="hevi-presenters__apps">
      <h2>LiveTalking 数字人</h2>
      <div className="hevi-presenters__apps-grid">
        <WebRTCCard />
        <RtmpStatusCard />
      </div>
    </section>
  );
}

function WebRTCCard() {
  const [capability, setCapability] = useState<{ can_start: boolean; message: string; setup?: string } | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);

  useEffect(() => {
    let active = true;
    void proStudioApi.livetalkingWebrtcCapabilities()
      .then(ready => { if (active) setCapability(ready); })
      .catch(() => { if (active) setCapability({ can_start: false, message: '无法确认 LiveTalking WebRTC 能力' }); });
    return () => { active = false; };
  }, []);

  async function connect() {
    setConnecting(true); setError(null);
    try {
      const pc = new RTCPeerConnection();
      pcRef.current = pc;
      pc.addTransceiver('video', { direction: 'recvonly' });
      pc.addTransceiver('audio', { direction: 'recvonly' });
      pc.ontrack = (event) => {
        if (videoRef.current) videoRef.current.srcObject = event.streams[0];
      };

      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);

      const answer = await proStudioApi.livetalkingWebrtcOffer({
        sdp: offer.sdp ?? '', type: offer.type,
      });
      await pc.setRemoteDescription({ sdp: answer.sdp, type: answer.type as RTCSdpType });
      setConnected(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : '建立会话失败');
      pcRef.current?.close();
      pcRef.current = null;
    }
    setConnecting(false);
  }

  function disconnect() {
    pcRef.current?.close();
    pcRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    setConnected(false);
  }

  useEffect(() => () => { pcRef.current?.close(); }, []);

  return (
    <article className="hevi-presenters__app">
      <div className="hevi-presenters__app-icon">💬</div>
      <h3>按需交互会话 (WebRTC)</h3>
      <p>客服问答 / 实时教学等场景：每次点击都跟 LiveTalking 单独建立一条 WebRTC 连接，不是共用的直播地址。</p>

      {capability && !capability.can_start && (
        <div className="hevi-presenters__live-warn">
          <p>⚠ {capability.message}</p>
          {capability.setup && <p className="hevi-presenters__live-warn-sub">{capability.setup}</p>}
        </div>
      )}

      <video ref={videoRef} autoPlay playsInline className="hevi-livetalking__video" />

      <div className="hevi-presenters__app-actions">
        <button disabled={connecting || connected || !capability?.can_start} onClick={() => void connect()}>
          {connecting ? '连接中…' : '📞 开始会话'}
        </button>
        <button disabled={!connected} onClick={disconnect}>⏹ 结束会话</button>
      </div>
      {error && <p className="hevi-presenters__live-error">⚠ {error}</p>}
    </article>
  );
}

function RtmpStatusCard() {
  const [status, setStatus] = useState<{ playback_url?: string; reachable?: boolean | null; message?: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    setLoading(true);
    proStudioApi.livetalkingRtmpStatus()
      .then(s => { if (active) { setStatus(s); setError(null); } })
      .catch(e => { if (active) setError(e instanceof Error ? e.message : '未配置 RTMP 频道'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  return (
    <article className="hevi-presenters__app">
      <div className="hevi-presenters__app-icon">📡</div>
      <h3>24 小时固定频道 (RTMP)</h3>
      <p>无人直播带货等场景：LiveTalking 进程以 --transport rtmp 常驻运行，这里只做只读状态展示，不提供远程开关。</p>

      {loading && <p className="hevi-presenters__live-status">检查中…</p>}
      {error && (
        <div className="hevi-presenters__live-warn">
          <p>⚠ {error}</p>
        </div>
      )}
      {status && (
        <div className="hevi-presenters__live-fields">
          <p>推流地址: {status.playback_url}</p>
          <p>
            可达性: {status.reachable === null ? '未配置探测端点，无法验证' : status.reachable ? '✅ 可达' : '❌ 不可达'}
          </p>
        </div>
      )}
    </article>
  );
}
