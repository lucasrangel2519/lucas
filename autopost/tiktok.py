"""TikTok publishing via the Content Posting API (Direct Post).

Docs: https://developers.tiktok.com/doc/content-posting-api-get-started
Requires an app with Login Kit + Content Posting API and the ``video.publish`` scope.
Until TikTok audits the app, every post is forced to SELF_ONLY (private).
"""

from __future__ import annotations

import math
import tempfile
import time
from pathlib import Path
from urllib.parse import urlencode

import requests

AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
API = "https://open.tiktokapis.com/v2"
SCOPES = "user.info.basic,video.publish"

MIN_CHUNK = 5 * 1024 * 1024
DEFAULT_CHUNK = 10 * 1024 * 1024
MAX_CHUNK = 64 * 1024 * 1024


class TikTokError(RuntimeError):
    pass


def _check(resp: requests.Response) -> dict:
    try:
        data = resp.json()
    except ValueError:
        resp.raise_for_status()
        raise TikTokError(f"Resposta inesperada: {resp.text[:300]}")
    err = data.get("error")
    if isinstance(err, dict) and err.get("code") not in (None, "ok"):
        raise TikTokError(f"Erro do TikTok ({resp.status_code}): {err}")
    if isinstance(err, str):  # OAuth endpoint style
        raise TikTokError(f"Erro do TikTok: {err} - {data.get('error_description', '')}")
    if resp.status_code >= 400:
        raise TikTokError(f"Erro do TikTok ({resp.status_code}): {data}")
    return data


# ----------------------------------------------------------------- OAuth helpers
def authorize_url(client_key: str, redirect_uri: str, state: str = "autopost") -> str:
    return AUTH_URL + "?" + urlencode(
        {
            "client_key": client_key,
            "scope": SCOPES,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "state": state,
        }
    )


def _token_request(**form) -> dict:
    return _check(
        requests.post(
            f"{API}/oauth/token/",
            data=form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
    )


def exchange_code(client_key: str, client_secret: str, redirect_uri: str, code: str) -> dict:
    return _token_request(
        client_key=client_key,
        client_secret=client_secret,
        code=code,
        grant_type="authorization_code",
        redirect_uri=redirect_uri,
    )


def refresh_token(client_key: str, client_secret: str, refresh: str) -> dict:
    """Returns new access_token (24h) and refresh_token (365 days)."""
    return _token_request(
        client_key=client_key,
        client_secret=client_secret,
        grant_type="refresh_token",
        refresh_token=refresh,
    )


def chunk_plan(size: int, chunk_size: int = DEFAULT_CHUNK) -> tuple[int, int]:
    """Return (chunk_size, total_chunk_count) following TikTok's upload rules.

    Videos under 5MB go in one chunk. Otherwise chunks are 5-64MB and the last
    chunk absorbs the remainder (it may be up to 128MB).
    """
    if size <= 0:
        raise TikTokError("Video vazio")
    if size < MIN_CHUNK:
        return size, 1
    chunk_size = max(MIN_CHUNK, min(chunk_size, MAX_CHUNK))
    if size <= chunk_size:
        return size, 1
    return chunk_size, max(1, math.floor(size / chunk_size))


# ----------------------------------------------------------------- Publisher
class TikTokClient:
    def __init__(
        self,
        access_token: str,
        privacy_level: str = "SELF_ONLY",
        brand_organic: bool = False,
        root: Path | None = None,
        poll_interval: float = 5.0,
        poll_timeout: float = 900.0,
        session: requests.Session | None = None,
    ):
        if not access_token:
            raise TikTokError("Sem token do TikTok (rode: python -m autopost auth-tiktok)")
        self.token = access_token
        self.privacy_level = privacy_level
        self.brand_organic = brand_organic
        self.root = root or Path.cwd()
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout
        self.http = session or requests.Session()

    def _post(self, path: str, body: dict | None = None) -> dict:
        resp = self.http.post(
            f"{API}/{path}",
            json=body or {},
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            timeout=60,
        )
        return _check(resp).get("data", {})

    def creator_info(self) -> dict:
        return self._post("post/publish/creator_info/query/")

    def _resolve_privacy(self, info: dict) -> str:
        options = info.get("privacy_level_options") or []
        if not options or self.privacy_level in options:
            return self.privacy_level
        if "SELF_ONLY" in options:
            return "SELF_ONLY"
        return options[0]

    def _local_file(self, ref: str) -> tuple[Path, bool]:
        """Return a local path for ref (downloading URLs). bool = is temporary."""
        if ref.startswith("http://") or ref.startswith("https://"):
            tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
            with self.http.get(ref, stream=True, timeout=300) as r:
                r.raise_for_status()
                for block in r.iter_content(1024 * 1024):
                    tmp.write(block)
            tmp.close()
            return Path(tmp.name), True
        path = (self.root / ref).resolve()
        if not path.exists():
            raise TikTokError(f"Arquivo nao encontrado: {ref}")
        return path, False

    def post_video(self, ref: str, caption: str = "", brand_organic: bool | None = None) -> str:
        info = self.creator_info()
        path, temporary = self._local_file(ref)
        try:
            size = path.stat().st_size
            chunk_size, total = chunk_plan(size)
            post_info = {
                "title": caption[:2200],
                "privacy_level": self._resolve_privacy(info),
                "disable_duet": bool(info.get("duet_disabled", False)),
                "disable_stitch": bool(info.get("stitch_disabled", False)),
                "disable_comment": bool(info.get("comment_disabled", False)),
                "video_cover_timestamp_ms": 1000,
                "brand_organic_toggle": self.brand_organic if brand_organic is None else brand_organic,
                "brand_content_toggle": False,
            }
            init = self._post(
                "post/publish/video/init/",
                {
                    "post_info": post_info,
                    "source_info": {
                        "source": "FILE_UPLOAD",
                        "video_size": size,
                        "chunk_size": chunk_size,
                        "total_chunk_count": total,
                    },
                },
            )
            publish_id, upload_url = init["publish_id"], init["upload_url"]
            with path.open("rb") as fh:
                for i in range(total):
                    start = i * chunk_size
                    end = size - 1 if i == total - 1 else start + chunk_size - 1
                    fh.seek(start)
                    chunk = fh.read(end - start + 1)
                    resp = self.http.put(
                        upload_url,
                        data=chunk,
                        headers={
                            "Content-Type": "video/mp4",
                            "Content-Length": str(len(chunk)),
                            "Content-Range": f"bytes {start}-{end}/{size}",
                        },
                        timeout=600,
                    )
                    if resp.status_code not in (200, 201, 206):
                        raise TikTokError(f"Falha no upload do pedaco {i + 1}/{total}: {resp.status_code} {resp.text[:200]}")
        finally:
            if temporary:
                path.unlink(missing_ok=True)
        return self.wait_published(publish_id)

    def wait_published(self, publish_id: str) -> str:
        deadline = time.monotonic() + self.poll_timeout
        while True:
            data = self._post("post/publish/status/fetch/", {"publish_id": publish_id})
            status = data.get("status")
            if status == "PUBLISH_COMPLETE":
                ids = data.get("publicaly_available_post_id") or data.get("publicly_available_post_id") or []
                return str(ids[0]) if ids else publish_id
            if status == "FAILED":
                raise TikTokError(f"TikTok recusou o video: {data.get('fail_reason')}")
            if time.monotonic() > deadline:
                # Upload done; TikTok keeps processing on its side.
                return publish_id
            time.sleep(self.poll_interval)
