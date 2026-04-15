"""Tests for DiscordAdapter.send_media_group native multi-attachment support.

Discord renders multiple attachments on a single message as an inline grid,
which is the closest native analogue to a Telegram album. This test verifies
the adapter builds one message with up to 10 discord.File attachments, puts
per-item captions into each File's description (alt text), and chunks over
the 10-item limit into multiple messages.
"""

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import gateway.platforms.discord as discord_mod
from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import MediaGroupItem
from gateway.platforms.discord import DiscordAdapter


class _FakeFile:
    def __init__(self, source, filename=None, description=None):
        self.source = source
        self.filename = filename
        self.description = description


@pytest.fixture(autouse=True)
def _stub_discord_module(monkeypatch):
    """Ensure gateway.platforms.discord.discord.File is available under the test
    environment even when discord.py isn't installed."""
    stub = MagicMock()
    stub.File = _FakeFile
    monkeypatch.setattr(discord_mod, "discord", stub)
    yield


def _make_adapter():
    cfg = PlatformConfig(enabled=True, token="fake-token")
    adapter = DiscordAdapter(cfg)

    sent_calls = []
    channel = MagicMock()

    async def _send(content=None, files=None, **kwargs):
        sent_calls.append({"content": content, "files": list(files or [])})
        return SimpleNamespace(id=42)

    channel.send = _send

    client = MagicMock()
    client.get_channel = MagicMock(return_value=channel)
    client.fetch_channel = AsyncMock(return_value=channel)
    adapter._client = client
    return adapter, sent_calls


@pytest.mark.asyncio
async def test_album_three_local_files_single_message(tmp_path):
    paths = []
    for name in ("a.png", "b.png", "c.png"):
        p = tmp_path / name
        p.write_bytes(b"\x89PNG\r\n\x1a\n")
        paths.append(str(p))

    adapter, sent = _make_adapter()

    items = [
        MediaGroupItem(path_or_url=paths[0], caption="alpha"),
        MediaGroupItem(path_or_url=paths[1], caption="beta"),
        MediaGroupItem(path_or_url=paths[2], caption="gamma"),
    ]
    result = await adapter.send_media_group("123456", items)

    assert result.success
    assert len(sent) == 1, f"expected one Discord message, got {len(sent)}"
    msg = sent[0]

    # One message, three file attachments
    assert len(msg["files"]) == 3
    # Each file carries its caption as description (alt text)
    assert [f.description for f in msg["files"]] == ["alpha", "beta", "gamma"]
    # All-captioned albums render a numbered legend as the message content
    assert msg["content"] is not None
    assert "1. alpha" in msg["content"]
    assert "2. beta" in msg["content"]
    assert "3. gamma" in msg["content"]


@pytest.mark.asyncio
async def test_album_no_captions_sends_files_only(tmp_path):
    paths = []
    for name in ("x.png", "y.png"):
        p = tmp_path / name
        p.write_bytes(b"\x89PNG\r\n\x1a\n")
        paths.append(str(p))

    adapter, sent = _make_adapter()
    items = [
        MediaGroupItem(path_or_url=paths[0]),
        MediaGroupItem(path_or_url=paths[1]),
    ]
    await adapter.send_media_group("123456", items)

    assert len(sent) == 1
    assert sent[0]["content"] is None
    assert len(sent[0]["files"]) == 2


@pytest.mark.asyncio
async def test_album_only_first_caption_uses_legacy_shape(tmp_path):
    paths = []
    for name in ("x.png", "y.png", "z.png"):
        p = tmp_path / name
        p.write_bytes(b"\x89PNG\r\n\x1a\n")
        paths.append(str(p))

    adapter, sent = _make_adapter()
    items = [
        MediaGroupItem(path_or_url=paths[0], caption="shared caption"),
        MediaGroupItem(path_or_url=paths[1]),
        MediaGroupItem(path_or_url=paths[2]),
    ]
    await adapter.send_media_group("123456", items)

    assert len(sent) == 1
    # Legacy shape: first caption becomes message content (no numbered legend)
    assert sent[0]["content"] == "shared caption"


@pytest.mark.asyncio
async def test_album_over_ten_items_splits_messages(tmp_path):
    paths = []
    for i in range(12):
        p = tmp_path / f"p{i}.png"
        p.write_bytes(b"\x89PNG\r\n\x1a\n")
        paths.append(str(p))

    adapter, sent = _make_adapter()
    items = [MediaGroupItem(path_or_url=paths[i], caption=f"c{i}") for i in range(12)]

    await adapter.send_media_group("123456", items)

    # 12 items → 10 + 2 across two Discord messages
    assert len(sent) == 2
    assert len(sent[0]["files"]) == 10
    assert len(sent[1]["files"]) == 2
