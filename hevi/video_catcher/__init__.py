"""Link-to-local-media ingestion contracts."""

from hevi.layer4_legacy.video_catcher.omodul_impl.runtime import discover_video, download_video
from hevi.layer4_legacy.video_catcher.oprim_impl.contracts import VideoCatchRequest, VideoDiscovery

__all__ = ["VideoCatchRequest", "VideoDiscovery", "discover_video", "download_video"]
