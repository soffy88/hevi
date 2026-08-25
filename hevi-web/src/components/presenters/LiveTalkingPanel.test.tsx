/**
 * LiveTalkingPanel 测试 — WebRTC 按需会话 + RTMP 固定频道只读状态。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { LiveTalkingPanel } from './LiveTalkingPanel';

const hoisted = vi.hoisted(() => ({
  webrtcCapabilities: vi.fn(),
  webrtcOffer: vi.fn(),
  rtmpStatus: vi.fn(),
}));

vi.mock('@/lib/api-client', () => ({
  proStudioApi: {
    livetalkingWebrtcCapabilities: hoisted.webrtcCapabilities,
    livetalkingWebrtcOffer: hoisted.webrtcOffer,
    livetalkingRtmpStatus: hoisted.rtmpStatus,
  },
}));

class FakeRTCPeerConnection {
  ontrack: ((event: { streams: MediaStream[] }) => void) | null = null;
  localDescription: { sdp: string; type: string } | null = null;
  addTransceiver = vi.fn();
  createOffer = vi.fn().mockResolvedValue({ sdp: 'v=0 fake-offer...', type: 'offer' });
  setLocalDescription = vi.fn().mockResolvedValue(undefined);
  setRemoteDescription = vi.fn().mockResolvedValue(undefined);
  close = vi.fn();
}

beforeEach(() => {
  hoisted.webrtcCapabilities.mockReset();
  hoisted.webrtcOffer.mockReset();
  hoisted.rtmpStatus.mockReset();
  vi.stubGlobal('RTCPeerConnection', FakeRTCPeerConnection);
});

describe('LiveTalkingPanel', () => {
  it('WebRTC 卡片: 能力未就绪时禁用开始按钮并显示原因', async () => {
    hoisted.webrtcCapabilities.mockResolvedValue({
      can_start: false, message: '未配置 LIVETALKING_WEBRTC_URL', setup: '请先部署 LiveTalking',
    });
    hoisted.rtmpStatus.mockRejectedValue(new Error('未配置'));

    render(<LiveTalkingPanel />);

    expect(await screen.findByText(/未配置 LIVETALKING_WEBRTC_URL/)).toBeInTheDocument();
    const startButton = screen.getByRole('button', { name: /开始会话/ });
    expect(startButton).toBeDisabled();
  });

  it('WebRTC 卡片: 就绪时点击开始会话完成 offer/answer 握手', async () => {
    hoisted.webrtcCapabilities.mockResolvedValue({ can_start: true, message: '就绪' });
    hoisted.rtmpStatus.mockRejectedValue(new Error('未配置'));
    hoisted.webrtcOffer.mockResolvedValue({
      session_id: '7', sdp: 'v=0 fake-answer...', type: 'answer', provider: 'livetalking', status: 'started',
    });

    const user = (await import('@testing-library/user-event')).default;
    render(<LiveTalkingPanel />);

    const startButton = await screen.findByRole('button', { name: /开始会话/ });
    await waitFor(() => expect(startButton).not.toBeDisabled());
    await user.click(startButton);

    await waitFor(() => expect(hoisted.webrtcOffer).toHaveBeenCalledWith({
      sdp: 'v=0 fake-offer...', type: 'offer',
    }));
    expect(await screen.findByRole('button', { name: /结束会话/ })).not.toBeDisabled();
  });

  it('WebRTC 卡片: 握手失败展示可读错误', async () => {
    hoisted.webrtcCapabilities.mockResolvedValue({ can_start: true, message: '就绪' });
    hoisted.rtmpStatus.mockRejectedValue(new Error('未配置'));
    hoisted.webrtcOffer.mockRejectedValue(new Error('LiveTalking offer 握手失败：HTTP 500'));

    const user = (await import('@testing-library/user-event')).default;
    render(<LiveTalkingPanel />);

    const startButton = await screen.findByRole('button', { name: /开始会话/ });
    await waitFor(() => expect(startButton).not.toBeDisabled());
    await user.click(startButton);

    expect(await screen.findByText(/握手失败/)).toBeInTheDocument();
  });

  it('RTMP 卡片: 已配置时展示推流地址与可达性', async () => {
    hoisted.webrtcCapabilities.mockResolvedValue({ can_start: false, message: 'x' });
    hoisted.rtmpStatus.mockResolvedValue({
      provider: 'livetalking', playback_url: 'rtmp://cdn.example/live/s1', reachable: true,
    });

    render(<LiveTalkingPanel />);

    expect(await screen.findByText(/rtmp:\/\/cdn\.example\/live\/s1/)).toBeInTheDocument();
    expect(await screen.findByText(/✅ 可达/)).toBeInTheDocument();
  });

  it('RTMP 卡片: 未配置时展示错误而不是假装可用', async () => {
    hoisted.webrtcCapabilities.mockResolvedValue({ can_start: false, message: 'x' });
    hoisted.rtmpStatus.mockRejectedValue(new Error('未配置 LIVETALKING_RTMP_PLAYBACK_URL'));

    render(<LiveTalkingPanel />);

    expect(await screen.findByText(/未配置 LIVETALKING_RTMP_PLAYBACK_URL/)).toBeInTheDocument();
  });
});
