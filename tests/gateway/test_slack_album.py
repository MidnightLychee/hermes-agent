"""Tests for SlackAdapter.send_media_group — batched files_upload_v2.

Slack's files_upload_v2 accepts a ``file_uploads`` list that uploads several
files in one batch with one shared ``initial_comment``. Per-item captions
become each item's ``title`` (rendered under the individual attachment).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.config import PlatformConfig
from gateway.platforms.base import MediaGroupItem
from gateway.platforms.slack import SlackAdapter


def _make_adapter():
    cfg = PlatformConfig(enabled=True, token="xoxb-test")
    adapter = SlackAdapter(cfg)
    adapter._app = MagicMock()

    upload_calls = []
    client = MagicMock()

    async def _files_upload_v2(**kwargs):
        upload_calls.append(kwargs)
        return {"ok": True}

    client.files_upload_v2 = _files_upload_v2
    adapter._get_client = lambda chat_id: client
    adapter._resolve_thread_ts = lambda reply_to, metadata: None
    return adapter, upload_calls


@pytest.mark.asyncio
async def test_album_all_captioned_builds_numbered_legend_with_titles(tmp_path):
    paths = []
    for name in ("a.png", "b.png", "c.png"):
        p = tmp_path / name
        p.write_bytes(b"\x89PNG\r\n\x1a\n")
        paths.append(str(p))

    adapter, calls = _make_adapter()
    items = [
        MediaGroupItem(path_or_url=paths[0], caption="alpha"),
        MediaGroupItem(path_or_url=paths[1], caption="beta"),
        MediaGroupItem(path_or_url=paths[2], caption="gamma"),
    ]
    result = await adapter.send_media_group("C123", items)
    assert result.success
    assert len(calls) == 1
    kwargs = calls[0]

    assert kwargs["channel"] == "C123"
    uploads = kwargs["file_uploads"]
    assert len(uploads) == 3
    assert [u["title"] for u in uploads] == ["alpha", "beta", "gamma"]
    assert [u["file"] for u in uploads] == paths

    # Numbered legend as initial_comment
    assert "1. alpha" in kwargs["initial_comment"]
    assert "2. beta" in kwargs["initial_comment"]
    assert "3. gamma" in kwargs["initial_comment"]


@pytest.mark.asyncio
async def test_album_no_captions_empty_initial_comment(tmp_path):
    paths = []
    for name in ("x.png", "y.png"):
        p = tmp_path / name
        p.write_bytes(b"\x89PNG\r\n\x1a\n")
        paths.append(str(p))

    adapter, calls = _make_adapter()
    items = [MediaGroupItem(path_or_url=paths[0]), MediaGroupItem(path_or_url=paths[1])]
    await adapter.send_media_group("C123", items)
    assert len(calls) == 1
    assert calls[0]["initial_comment"] == ""
    assert all(u["title"] is None for u in calls[0]["file_uploads"])


@pytest.mark.asyncio
async def test_album_first_caption_only_shared_comment(tmp_path):
    paths = []
    for name in ("x.png", "y.png"):
        p = tmp_path / name
        p.write_bytes(b"\x89PNG\r\n\x1a\n")
        paths.append(str(p))
    adapter, calls = _make_adapter()
    items = [
        MediaGroupItem(path_or_url=paths[0], caption="shared caption"),
        MediaGroupItem(path_or_url=paths[1]),
    ]
    await adapter.send_media_group("C123", items)
    assert calls[0]["initial_comment"] == "shared caption"


@pytest.mark.asyncio
async def test_album_skips_missing_files(tmp_path):
    good = tmp_path / "ok.png"
    good.write_bytes(b"\x89PNG\r\n\x1a\n")
    missing = tmp_path / "missing.png"

    adapter, calls = _make_adapter()
    items = [
        MediaGroupItem(path_or_url=str(good), caption="ok"),
        MediaGroupItem(path_or_url=str(missing), caption="gone"),
    ]
    result = await adapter.send_media_group("C123", items)
    assert result.success
    uploads = calls[0]["file_uploads"]
    assert [u["file"] for u in uploads] == [str(good)]


@pytest.mark.asyncio
async def test_album_all_missing_returns_failure(tmp_path):
    adapter, calls = _make_adapter()
    items = [MediaGroupItem(path_or_url=str(tmp_path / "nope.png"))]
    result = await adapter.send_media_group("C123", items)
    assert not result.success
    assert calls == []
