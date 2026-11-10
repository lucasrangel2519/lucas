"""Instagram publishing via the Instagram API with Instagram Login.

Docs: https://developers.facebook.com/docs/instagram-platform/content-publishing
Requires an Instagram Professional (Business or Creator) account and a token with
the scopes ``instagram_business_basic`` and ``instagram_business_content_publish``.
"""

from __future__ import annotations

import time
from pathlib import Path
from urllib.parse import urlencode

import requests

AUTH_URL = "https://www.instagram.com/oauth/authorize"
SHORT_TOKEN_URL = "https://api.instagram.com/oauth/access_token"
GRAPH = "https://graph.instagram.com"
RUPLOAD = "https://rupload.facebook.com/ig-api-upload"
SCOPES = "instagram_business_basic,instagram_business_content_publish"

VIDEO_EXT = {".mp4", ".mov"}


class InstagramError(RuntimeError):
    pass


def _check(resp: requests.Response) -> dict:
    try:
        data = resp.json()
    except ValueError:
        resp.raise_for_status()
        raise InstagramError(f"Resposta inesperada: {resp.text[:300]}")
    if resp.status_code >= 400 or "error" in data:
        raise InstagramError(f"Erro do Instagram ({resp.status_code}): {data.get('error', data)}")
    return data


# ----------------------------------------------------------------- OAuth helpers
def authorize_url(app_id: str, redirect_uri: str, state: str = "autopost") -> str:
    return AUTH_URL + "?" + urlencode(
        {
            "client_id": app_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPES,
            "state": state,
        }
    )


def exchange_code(app_id: str, app_secret: str, redirect_uri: str, code: str) -> dict:
    """Code -> short-lived token -> long-lived token (60 days)."""
    code = code.split("#_")[0]
    short = _check(
        requests.post(
            SHORT_TOKEN_URL,
            data={
                "client_id": app_id,
                "client_secret": app_secret,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "code": code,
            },
            timeout=30,
        )
    )
    if "data" in short:  # some responses wrap the payload in a list
        short = short["data"][0]
    long_lived = _check(
        requests.get(
            f"{GRAPH}/access_token",
            params={
                "grant_type": "ig_exchange_token",
                "client_secret": app_secret,
                "access_token": short["access_token"],
            },
            timeout=30,
        )
    )
    return {
        "user_id": str(short["user_id"]),
        "access_token": long_lived["access_token"],
        "expires_in": long_lived.get("expires_in"),
    }


def refresh_token(access_token: str) -> dict:
    """Extend a long-lived token for another 60 days (token must be >24h old)."""
    return _check(
        requests.get(
            f"{GRAPH}/refresh_access_token",
            params={"grant_type": "ig_refresh_token", "access_token": access_token},
            timeout=30,
        )
    )


# ----------------------------------------------------------------- Publisher
class InstagramClient:
    def __init__(
        self,
        user_id: str,
        access_token: str,
        api_version: str = "v23.0",
        media_base_url: str = "",
        root: Path | None = None,
        poll_interval: float = 5.0,
        poll_timeout: float = 600.0,
        session: requests.Session | None = None,
    ):
        if not user_id or not access_token:
            raise InstagramError("Configure IG_USER_ID e IG_ACCESS_TOKEN (rode: python -m autopost auth-instagram)")
        self.user_id = user_id
        self.token = access_token
        self.base = f"{GRAPH}/{api_version}"
        self.api_version = api_version
        self.media_base_url = media_base_url.rstrip("/")
        self.root = root or Path.cwd()
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout
        self.http = session or requests.Session()

    # -- low level
    def _post(self, path: str, **params) -> dict:
        params["access_token"] = self.token
        return _check(self.http.post(f"{self.base}/{path}", data=params, timeout=60))

    def _get(self, path: str, **params) -> dict:
        params["access_token"] = self.token
        return _check(self.http.get(f"{self.base}/{path}", params=params, timeout=60))

    def _is_url(self, ref: str) -> bool:
        return ref.startswith("http://") or ref.startswith("https://")

    def _public_url(self, ref: str) -> str:
        if self._is_url(ref):
            return ref
        if not self.media_base_url:
            raise InstagramError(
                f"'{ref}' e um arquivo local. O Instagram so aceita imagens por URL publica: "
                "configure MEDIA_BASE_URL ou use um link https no campo 'arquivo'."
            )
        return f"{self.media_base_url}/{ref.lstrip('/')}"

    @staticmethod
    def _is_video(ref: str) -> bool:
        return Path(ref.split("?")[0]).suffix.lower() in VIDEO_EXT

    def _local_path(self, ref: str) -> Path:
        path = (self.root / ref).resolve()
        if not path.exists():
            raise InstagramError(f"Arquivo nao encontrado: {ref}")
        return path

    # -- containers
    def _video_container(self, ref: str, **params) -> str:
        if self._is_url(ref):
            return self._post(f"{self.user_id}/media", video_url=ref, **params)["id"]
        # Local video: resumable upload straight to Meta, no hosting needed.
        container_id = self._post(f"{self.user_id}/media", upload_type="resumable", **params)["id"]
        path = self._local_path(ref)
        data = path.read_bytes()
        resp = self.http.post(
            f"{RUPLOAD}/{self.api_version}/{container_id}",
            headers={
                "Authorization": f"OAuth {self.token}",
                "offset": "0",
                "file_size": str(len(data)),
            },
            data=data,
            timeout=600,
        )
        _check(resp)
        return container_id

    def _image_container(self, ref: str, **params) -> str:
        return self._post(f"{self.user_id}/media", image_url=self._public_url(ref), **params)["id"]

    def _media_container(self, ref: str, **params) -> str:
        if self._is_video(ref):
            return self._video_container(ref, **params)
        return self._image_container(ref, **params)

    def wait_ready(self, container_id: str) -> None:
        deadline = time.monotonic() + self.poll_timeout
        while True:
            status = self._get(container_id, fields="status_code,status").get("status_code")
            if status in ("FINISHED", "PUBLISHED"):
                return
            if status in ("ERROR", "EXPIRED"):
                info = self._get(container_id, fields="status")
                raise InstagramError(f"Processamento da midia falhou: {info.get('status')}")
            if time.monotonic() > deadline:
                raise InstagramError("Tempo esgotado esperando o Instagram processar a midia")
            time.sleep(self.poll_interval)

    def _publish(self, container_id: str) -> str:
        self.wait_ready(container_id)
        return self._post(f"{self.user_id}/media_publish", creation_id=container_id)["id"]

    # -- public API
    def post(self, ref: str, caption: str = "") -> str:
        """Feed post with a single image (or a video, which Instagram publishes as a Reel)."""
        if self._is_video(ref):
            return self.reel(ref, caption)
        return self._publish(self._image_container(ref, caption=caption))

    def carousel(self, refs: list[str], caption: str = "") -> str:
        if not 2 <= len(refs) <= 10:
            raise InstagramError("Carrossel precisa de 2 a 10 arquivos")
        children = []
        for ref in refs:
            extra = {"media_type": "VIDEO"} if self._is_video(ref) else {}
            child = self._media_container(ref, is_carousel_item="true", **extra)
            self.wait_ready(child)
            children.append(child)
        container = self._post(
            f"{self.user_id}/media", media_type="CAROUSEL", children=",".join(children), caption=caption
        )["id"]
        return self._publish(container)

    def reel(self, ref: str, caption: str = "", share_to_feed: bool = True) -> str:
        container = self._video_container(
            ref, media_type="REELS", caption=caption, share_to_feed=str(share_to_feed).lower()
        )
        return self._publish(container)

    def story(self, ref: str) -> str:
        return self._publish(self._media_container(ref, media_type="STORIES"))

    def publishing_limit(self) -> dict:
        return self._get(f"{self.user_id}/content_publishing_limit", fields="quota_usage,config")
