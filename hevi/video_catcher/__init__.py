"""Link-to-local-media ingestion contracts."""

from hevi.video_catcher.omodul.runtime import discover_video, download_video
from hevi.video_catcher.oprim.contracts import VideoCatchRequest, VideoDiscovery

__all__ = ["VideoCatchRequest", "VideoDiscovery", "discover_video", "download_video"]
