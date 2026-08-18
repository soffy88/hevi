// PlaybackPanel.tsx - Video playback and event scrubbing
"use client";

import { useEffect, useState } from "react";

interface PlaybackPanelProps {
  run_id: string;
}

export default function PlaybackPanel({ run_id }: PlaybackPanelProps) {
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [events, setEvents] = useState<any[]>([]);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchData() {
      try {
        // 1. Fetch video URL (assuming an endpoint exists or we can construct from run_id)
        // For now, we'll use a placeholder; in reality, this might come from a different API
        const videoRes = await fetch(`/api/backlot/runs/${run_id}/video`);
        if (videoRes.ok) {
          const videoData = await videoRes.json();
          setVideoUrl(videoData.url);
        } else {
          // Fallback to a default or null
          setVideoUrl(null);
        }

        // 2. Fetch events for timeline
        const eventsRes = await fetch(`/api/backlot/runs/${run_id}/events?limit=100`);
        if (eventsRes.ok) {
          const eventsData = await eventsRes.json();
          setEvents(eventsData.events || []);
        }
      } catch (err) {
        console.error("Failed to load playback data:", err);
      } finally {
        setLoading(false);
      }
    }

    if (run_id) {
      fetchData();
    }
  }, [run_id]);

  const handleTimeUpdate = (e: React.ChangeEvent<HTMLInputElement>) => {
    const time = parseFloat(e.target.value);
    setCurrentTime(time);
    // In a real player, we would seek the video to this time
    // For simplicity, we just update the state; the video element would need to be controlled
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center p-4 bg-gray-100 rounded-lg shadow">
        <div className="animate-spin rounded-full h-8 w-8 border-4 border-blue-500 border-t-transparent" />
        <span className="text-sm text-gray-600 ml-2">正在加载回放数据...</span>
      </div>
    );
  }

  if (!videoUrl) {
    return (
      <div className="p-4 bg-gray-50 rounded-lg shadow">
        <p className="text-sm text-gray-600">暂无回放视频</p>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg shadow p-4">
      <h3 className="text-lg font-medium mb-4 flex items-center">
        <span className="text-indigo-600 mr-2">回放视图</span>
      </h3>
      
      <div className="space-y-4">
        {/* Video player */}
        <div className="ratio ratio-16x9 mb-4">
          <video
            src={videoUrl}
            controls
            autoPlay
            className="w-full h-full object-contain"
            onTimeUpdate={(e) => {
              const time = (e.currentTarget as HTMLVideoElement).currentTime;
              setCurrentTime(time);
            }}
            onLoadedMetadata={(e) => {
              setDuration((e.currentTarget as HTMLVideoElement).duration);
            }}
          />
        </div>

        {/* Timeline scrubber */}
        <div className="space-y-2">
          <label className="block text-sm font-medium text-gray-700">
            时间轴
          </label>
          <div className="flex items-center">
            <input
              type="range"
              min="0"
              max={duration}
              step="0.1"
              value={currentTime}
              onChange={handleTimeUpdate}
              className="flex-1"
            />
            <span className="ml-2 text-xs text-gray-500">
              {currentTime.toFixed(1)}s / {duration.toFixed(1)}s
            </span>
          </div>
        </div>

        {/* Events timeline markers */}
        <div className="mt-4">
          <p className="font-medium mb-2">事件标记</p>
          <div className="h-2 bg-gray-200 rounded overflow-hidden">
            {events.map((event, index) => {
              // We need a timestamp for each event to map to video time
              // For simplicity, we'll distribute evenly or use a placeholder
              const percent = (index / Math.max(events.length - 1, 1)) * 100;
              return (
                <div
                  key={index}
                  className="absolute left-0 h-2 w-1 bg-blue-500"
                  style={{ left: `${percent}%` }}
                />
              );
            })}
          </div>
          <div className="mt-2 flex justify-between text-xs text-gray-500">
            <span>0s</span>
            <span>{duration.toFixed(1)}s</span>
          </div>
        </div>
      </div>
    </div>
  );
}