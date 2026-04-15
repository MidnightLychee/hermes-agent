"""Tests for SignalAdapter.send_media_group — single-message multi-attachment.

signal-cli's ``send`` RPC accepts ``attachments`` as a list, so all items
arrive in one message with a shared attachment strip. Signal has no
per-item caption primitive — we fold per-item captions into the single
``message`` field as a numbered legend.
"""

from unittest.mock import AsyncMock

import pytest

from gateway.config import PlatformConfig
from gateway.platforms.base import MediaGroupItem
from gateway.platforms.signal import SignalAdapter


def _make_adapter():
    cfg = PlatformConfig(
        enabled=True,
        token="",
        extra={"account": "+15555550100", "http_url": "http://localhost:8080"},
    )
    adapter = SignalAdapter(cfg)

    rpc_calls = []

    async def _rpc(method, params, rpc_id=None):
        rpc_calls.append({"method": method, "params": params})
        return {"timestamp": 123456789}

    adapter._rpc = _rpc
    adapter._stop_typing_indicator = AsyncMock()
    adapter._track_sent_timestamp = lambda r: None
    return adapter, rpc_calls


@pytest.mark.asyncio
async def test_album_all_captioned_builds_numbered_legend(tmp_path):
    paths = []
    for name in ("a.png", "b.png", "c.png"):
        p = tmp_path / name
        p.write_bytes(b"\x89PNG\r\n\x1a\n")
        paths.append(str(p))

    adapter, rpc_calls = _make_adapter()
    items = [
        MediaGroupItem(path_or_url=paths[0], caption="first"),
        MediaGroupItem(path_or_url=paths[1], caption="second"),
        MediaGroupItem(path_or_url=paths[2], caption="third"),
    ]
    result = await adapter.send_media_group("+15555550200", items)
    assert result.success
    assert len(rpc_calls) == 1

    params = rpc_calls[0]["params"]
    assert params["attachments"] == paths
    assert "1. first" in params["message"]
    assert "2. second" in params["message"]
    assert "3. third" in params["message"]
    assert params["recipient"] == ["+15555550200"]


@pytest.mark.asyncio
async def test_album_group_chat_uses_groupId(tmp_path):
    p = tmp_path / "a.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n")
    adapter, rpc_calls = _make_adapter()
    items = [MediaGroupItem(path_or_url=str(p), caption="cap")]
    await adapter.send_media_group("group:abc123", items)
    assert rpc_calls[0]["params"]["groupId"] == "abc123"
    assert "recipient" not in rpc_calls[0]["params"]


@pytest.mark.asyncio
async def test_album_first_caption_only_is_shared_message(tmp_path):
    paths = []
    for name in ("a.png", "b.png"):
        p = tmp_path / name
        p.write_bytes(b"\x89PNG\r\n\x1a\n")
        paths.append(str(p))
    adapter, rpc_calls = _make_adapter()
    items = [
        MediaGroupItem(path_or_url=paths[0], caption="shared caption"),
        MediaGroupItem(path_or_url=paths[1]),
    ]
    await adapter.send_media_group("+15555550200", items)
    assert rpc_calls[0]["params"]["message"] == "shared caption"


@pytest.mark.asyncio
async def test_album_missing_files_are_skipped_not_fatal(tmp_path):
    good = tmp_path / "a.png"
    good.write_bytes(b"\x89PNG\r\n\x1a\n")
    missing = tmp_path / "does-not-exist.png"
    adapter, rpc_calls = _make_adapter()
    items = [
        MediaGroupItem(path_or_url=str(good), caption="ok"),
        MediaGroupItem(path_or_url=str(missing), caption="gone"),
    ]
    result = await adapter.send_media_group("+15555550200", items)
    assert result.success
    assert rpc_calls[0]["params"]["attachments"] == [str(good)]


@pytest.mark.asyncio
async def test_album_no_valid_files_returns_failure(tmp_path):
    adapter, rpc_calls = _make_adapter()
    items = [
        MediaGroupItem(path_or_url=str(tmp_path / "nope.png"), caption="x"),
    ]
    result = await adapter.send_media_group("+15555550200", items)
    assert not result.success
    assert "No attachments" in (result.error or "")
    assert rpc_calls == []
