from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from autopost import scheduler, tiktok
from autopost.cli import ROOT, _extract_code
from autopost.instagram import InstagramClient

TZ = ZoneInfo("America/Sao_Paulo")
MB = 1024 * 1024


def item(id_, when, **kw):
    raw = {"id": id_, "quando": when, "plataforma": "instagram", "tipo": "post", "arquivo": "x.jpg"}
    raw.update(kw)
    return scheduler.Item.parse(raw, TZ)


def test_parse_validates_platform_and_type():
    with pytest.raises(scheduler.AgendaError):
        item("a", "2026-11-11 09:00", tipo="video")
    with pytest.raises(scheduler.AgendaError):
        item("a", "11/11/2026")
    assert item("a", "2026-11-11 09:00").when.tzinfo == TZ


def test_run_publishes_due_once_and_records(tmp_path):
    now = datetime(2026, 11, 11, 10, 0, tzinfo=TZ)
    items = [item("old", "2026-11-09 09:00"), item("due", "2026-11-11 09:00"), item("future", "2026-11-11 11:00")]
    state = scheduler.State(tmp_path / "s.json")
    calls = []
    scheduler.run(items, state, lambda i: calls.append(i.id) or "123", now, timedelta(hours=12), log=lambda m: None)
    scheduler.run(items, state, lambda i: calls.append(i.id) or "123", now, timedelta(hours=12), log=lambda m: None)
    assert calls == ["due"]
    assert scheduler.State.load(tmp_path / "s.json").published["due"]["resultado"] == "123"


def test_failures_retry_then_stop(tmp_path):
    now = datetime(2026, 11, 11, 10, 0, tzinfo=TZ)
    items = [item("x", "2026-11-11 09:00")]
    state = scheduler.State(tmp_path / "s.json")

    def boom(_):
        raise RuntimeError("falhou")

    results = [scheduler.run(items, state, boom, now, timedelta(hours=12), log=lambda m: None) for _ in range(5)]
    assert results == [1, 1, 1, 0, 0]
    assert state.failures["x"]["tentativas"] == 3


def test_waiting_for_file_is_not_a_failure(tmp_path):
    now = datetime(2026, 11, 11, 10, 0, tzinfo=TZ)
    state = scheduler.State(tmp_path / "s.json")
    n = scheduler.run([item("x", "2026-11-11 09:00")], state, lambda i: "1", now, timedelta(hours=12),
                      log=lambda m: None, is_ready=lambda i: False)
    assert n == 0 and not state.published and not state.failures


def test_chunk_plan():
    assert tiktok.chunk_plan(3 * MB) == (3 * MB, 1)
    assert tiktok.chunk_plan(8 * MB) == (8 * MB, 1)
    assert tiktok.chunk_plan(25 * MB) == (10 * MB, 2)  # last chunk takes the 5MB remainder
    assert tiktok.chunk_plan(30 * MB) == (10 * MB, 3)


def test_extract_code_from_redirect_url():
    assert _extract_code("https://github.com/?code=AB%2ACD&state=autopost") == "AB*CD"
    assert _extract_code(" abc ") == "abc"


def test_instagram_local_image_needs_base_url():
    client = InstagramClient("1", "t", media_base_url="https://cdn.example/m")
    assert client._public_url("media/a.jpg") == "https://cdn.example/m/media/a.jpg"
    with pytest.raises(Exception):
        InstagramClient("1", "t")._public_url("media/a.jpg")


def test_repository_agenda_is_valid():
    items = scheduler.load_agenda(ROOT / "agenda", TZ)
    assert items, "agenda vazia"
    per_day = {}
    for i in items:
        per_day.setdefault(i.when.date(), []).append(i)
    for day in per_day.values():
        ig = [i for i in day if i.platform == "instagram"]
        assert len([i for i in ig if i.kind != "stories"]) == 3
        assert len([i for i in ig if i.kind == "stories"]) == 1
        assert any(i.platform == "tiktok" for i in day)


class FakeResp:
    def __init__(self, data, status=200):
        self._data, self.status_code, self.text = data, status, str(data)

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


class FakeSession:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def _reply(self, method, url, **kw):
        self.calls.append((method, url, kw))
        for key, value in self.routes.items():
            if key in url:
                return FakeResp(value(kw) if callable(value) else value)
        raise AssertionError(f"unexpected {method} {url}")

    def post(self, url, **kw):
        return self._reply("POST", url, **kw)

    def get(self, url, **kw):
        return self._reply("GET", url, **kw)

    def put(self, url, **kw):
        return self._reply("PUT", url, **kw)


def test_tiktok_upload_flow(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x" * (12 * MB))
    ok = {"error": {"code": "ok"}}
    session = FakeSession({
        "creator_info": {**ok, "data": {"privacy_level_options": ["SELF_ONLY"]}},
        "video/init": {**ok, "data": {"publish_id": "p1", "upload_url": "https://up.tiktok/x"}},
        "up.tiktok": {},
        "status/fetch": {**ok, "data": {"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": [42]}},
    })
    client = tiktok.TikTokClient("tok", privacy_level="PUBLIC_TO_EVERYONE", root=tmp_path, session=session)
    assert client.post_video("v.mp4", "legenda") == "42"
    init = next(c for c in session.calls if "video/init" in c[1])[2]["json"]
    assert init["post_info"]["privacy_level"] == "SELF_ONLY"  # falls back while unaudited
    assert init["source_info"]["total_chunk_count"] == 1
    put = next(c for c in session.calls if c[0] == "PUT")[2]
    assert put["headers"]["Content-Range"] == f"bytes 0-{12 * MB - 1}/{12 * MB}"


def _form(call):
    data = call[2].get("data")
    return data if isinstance(data, dict) else {}


def test_instagram_carousel_and_story(tmp_path):
    (tmp_path / "s.mp4").write_bytes(b"video")
    counter = iter(range(100))
    session = FakeSession({
        "rupload": {"success": True},
        "/media_publish": {"id": "PUB"},
        "/media": lambda kw: {"id": f"C{next(counter)}"},
        "graph.instagram.com/v23.0/C": {"status_code": "FINISHED"},
    })
    client = InstagramClient("99", "tok", media_base_url="https://cdn/x", root=tmp_path, session=session, poll_interval=0)
    assert client.carousel(["a.jpg", "b.jpg"], "oi") == "PUB"
    carousel = [c for c in session.calls if _form(c).get("media_type") == "CAROUSEL"][0]
    assert carousel[2]["data"]["children"] == "C0,C1"
    assert client.story("s.mp4") == "PUB"
    story = [c for c in session.calls if _form(c).get("media_type") == "STORIES"][0]
    assert story[2]["data"]["upload_type"] == "resumable"
    assert any("rupload" in c[1] for c in session.calls)
