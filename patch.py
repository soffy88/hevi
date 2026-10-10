import re
import sys

with open('hevi/sourcing/corpus.py', 'r') as f:
    content = f.read()

nasa_code = """
    async def add_nasa_api(self, *, query: str, count: int = 3, client=None) -> list[ClipRecord]:
        added = []
        client = client or httpx.AsyncClient(timeout=30, follow_redirects=True)
        try:
            resp = await client.get("https://images-api.nasa.gov/search", params={"q": query, "media_type": "video"})
            resp.raise_for_status()
            items = resp.json().get("collection", {}).get("items", [])[:count]
            for it in items:
                try:
                    data = it["data"][0]
                    nasa_id = data["nasa_id"]
                    title = data.get("title", nasa_id)
                    collection_url = it["href"]
                    col_resp = await client.get(collection_url)
                    col_resp.raise_for_status()
                    mp4s = [u for u in col_resp.json() if str(u).endswith(".mp4")]
                    if not mp4s: continue
                    video_url = mp4s[0]
                    clip_id = f"nasa_{nasa_id[:40]}"
                    dest = self._clips_dir() / f"{clip_id}.mp4"
                    if not dest.exists():
                        dl_resp = await client.get(video_url)
                        dl_resp.raise_for_status()
                        dest.write_bytes(dl_resp.content)
                    rec = ClipRecord(
                        clip_id=clip_id, source="nasa", source_id=nasa_id,
                        source_url=video_url, local_path=str(dest.relative_to(self.root)),
                        query=query, title=title, license="public-domain"
                    )
                    self._index_record(rec)
                    added.append(rec)
                except Exception as exc:
                    logger.warning("NASA api fail %s", exc)
        finally:
            pass
        return added

    async def add_wikimedia_commons(self, *, query: str, count: int = 3, client=None) -> list[ClipRecord]:
        added = []
        client = client or httpx.AsyncClient(timeout=30, follow_redirects=True)
        try:
            # Action API search
            params = {
                "action": "query", "format": "json", "generator": "search",
                "gsrsearch": f"{query} filetype:video", "gsrlimit": count,
                "prop": "videoinfo", "viprop": "url|extmetadata"
            }
            resp = await client.get("https://commons.wikimedia.org/w/api.php", params=params)
            resp.raise_for_status()
            pages = resp.json().get("query", {}).get("pages", {}).values()
            for p in pages:
                try:
                    vi = p.get("videoinfo", [{}])[0]
                    video_url = vi.get("url")
                    if not video_url: continue
                    title = p.get("title", "")
                    clip_id = f"wiki_{p.get('pageid', '')}"
                    dest = self._clips_dir() / f"{clip_id}.mp4"
                    if not dest.exists():
                        dl_resp = await client.get(video_url)
                        dl_resp.raise_for_status()
                        dest.write_bytes(dl_resp.content)
                    ext = vi.get("extmetadata", {})
                    lic = ext.get("LicenseShortName", {}).get("value", "cc-by-sa")
                    rec = ClipRecord(
                        clip_id=clip_id, source="wikimedia", source_id=str(p.get("pageid")),
                        source_url=video_url, local_path=str(dest.relative_to(self.root)),
                        query=query, title=title, license=lic
                    )
                    self._index_record(rec)
                    added.append(rec)
                except Exception as exc:
                    logger.warning("wiki api fail %s", exc)
        finally:
            pass
        return added

    async def add_pexels(self, *, query: str, count: int = 3, api_key: str, client=None) -> list[ClipRecord]:
        added = []
        if not api_key: return added
        client = client or httpx.AsyncClient(timeout=30, follow_redirects=True)
        try:
            resp = await client.get(
                "https://api.pexels.com/videos/search", 
                params={"query": query, "per_page": count},
                headers={"Authorization": api_key}
            )
            resp.raise_for_status()
            items = resp.json().get("videos", [])
            for v in items:
                try:
                    vid = str(v["id"])
                    title = v.get("url", vid)
                    files = sorted(v.get("video_files", []), key=lambda x: -x.get("width", 0))
                    if not files: continue
                    video_url = files[0]["link"]
                    clip_id = f"pexels_{vid}"
                    dest = self._clips_dir() / f"{clip_id}.mp4"
                    if not dest.exists():
                        dl_resp = await client.get(video_url)
                        dl_resp.raise_for_status()
                        dest.write_bytes(dl_resp.content)
                    rec = ClipRecord(
                        clip_id=clip_id, source="pexels", source_id=vid,
                        source_url=v.get("url", video_url), local_path=str(dest.relative_to(self.root)),
                        query=query, title=title, license="pexels"
                    )
                    self._index_record(rec)
                    added.append(rec)
                except Exception as exc:
                    logger.warning("pexels api fail %s", exc)
        finally:
            pass
        return added
"""

idx = content.find("def _index_record")
if idx == -1:
    print("Not found")
    sys.exit(1)

new_content = content[:idx] + nasa_code + "\n    " + content[idx:]
with open('hevi/sourcing/corpus.py', 'w') as f:
    f.write(new_content)
