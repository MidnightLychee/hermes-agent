"""End-to-end regression test for album delivery in the non-streaming path.

Upstream refactors have split the delivery pipeline into two paths (streaming
via gateway/run.py::_deliver_media_from_response, non-streaming via
BasePlatformAdapter._process_message_background).  Previous regressions left
the non-streaming path on the legacy extract_media pipeline, which dumps all
captions into one text message and sends each photo with an individual
sendPhoto call — no album.

This test feeds the canonical `MEDIA:/path\\ncaption\\n...` album shape
through _process_message_background and asserts that the adapter dispatched
a single send_media_group call (not N individual send_image_file calls and
not a concatenated caption blob).
"""

import asyncio

import pytest

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import (
    BasePlatformAdapter,
    MessageEvent,
    ProcessingOutcome,
    SendResult,
)
from gateway.session import SessionSource, build_session_key


class RecordingAdapter(BasePlatformAdapter):
    """Minimal adapter that records every outbound call."""

    def __init__(self):
        super().__init__(PlatformConfig(enabled=True, token="fake-token"), Platform.TELEGRAM)
        self.sent = []
        self.image_file_sends = []
        self.image_url_sends = []
        self.media_group_sends = []
        self.document_sends = []
        self.video_sends = []

    async def connect(self) -> bool:
        return True

    async def disconnect(self) -> None:
        return None

    async def send(self, chat_id, content, reply_to=None, metadata=None) -> SendResult:
        self.sent.append({"chat_id": chat_id, "content": content})
        return SendResult(success=True, message_id="msg-text")

    async def send_typing(self, chat_id: str, metadata=None) -> None:
        return None

    async def get_chat_info(self, chat_id: str):
        return {"id": chat_id}

    async def send_image_file(self, chat_id, image_path, caption=None, metadata=None):
        self.image_file_sends.append({"path": image_path, "caption": caption})
        return SendResult(success=True, message_id="msg-photo")

    async def send_image(self, chat_id, image_url, caption=None, metadata=None):
        self.image_url_sends.append({"url": image_url, "caption": caption})
        return SendResult(success=True, message_id="msg-photo-url")

    async def send_document(self, chat_id, file_path, caption=None, metadata=None):
        self.document_sends.append({"path": file_path, "caption": caption})
        return SendResult(success=True, message_id="msg-doc")

    async def send_video(self, chat_id, video_path, caption=None, metadata=None):
        self.video_sends.append({"path": video_path, "caption": caption})
        return SendResult(success=True, message_id="msg-video")

    async def send_media_group(self, chat_id, media_items, metadata=None):
        self.media_group_sends.append(
            {
                "chat_id": chat_id,
                "items": [
                    {"path_or_url": i.path_or_url, "caption": i.caption}
                    for i in media_items
                ],
            }
        )
        return SendResult(success=True, message_id="msg-album")

    async def on_processing_start(self, event: MessageEvent) -> None:
        return None

    async def on_processing_complete(
        self, event: MessageEvent, outcome: ProcessingOutcome
    ) -> None:
        return None


def _make_event() -> MessageEvent:
    return MessageEvent(
        text="send me the album",
        source=SessionSource(
            platform=Platform.TELEGRAM,
            chat_id="-100123",
            chat_type="private",
            thread_id=None,
        ),
        message_id="inbound-1",
    )


async def _run(adapter: RecordingAdapter, response: str) -> None:
    async def handler(_event):
        return response

    async def hold_typing(_chat_id, interval=2.0, metadata=None):
        await asyncio.Event().wait()

    adapter.set_message_handler(handler)
    adapter._keep_typing = hold_typing

    event = _make_event()
    await adapter._process_message_background(event, build_session_key(event.source))


def _album_response(paths_and_captions):
    return "\n".join(f"MEDIA:{p}\n{c}" for p, c in paths_and_captions)


@pytest.mark.asyncio
async def test_album_dispatches_send_media_group(tmp_path):
    paths = []
    for name in ("a.png", "b.png", "c.png"):
        p = tmp_path / name
        p.write_bytes(b"\x89PNG\r\n\x1a\n")  # valid enough PNG magic
        paths.append(str(p))

    captions = ["caption a", "caption b", "caption c"]
    response = _album_response(list(zip(paths, captions)))

    adapter = RecordingAdapter()
    await _run(adapter, response)

    # Exactly one album call with all three items and their per-item captions.
    assert len(adapter.media_group_sends) == 1, (
        f"expected 1 send_media_group call, got {len(adapter.media_group_sends)} "
        f"(image_file={len(adapter.image_file_sends)}, sent={len(adapter.sent)})"
    )
    items = adapter.media_group_sends[0]["items"]
    assert [i["path_or_url"] for i in items] == paths
    assert [i["caption"] for i in items] == captions

    # Legacy per-item paths must NOT have been used.
    assert adapter.image_file_sends == []
    assert adapter.image_url_sends == []

    # And the captions must NOT have been dumped as a text message.
    for call in adapter.sent:
        assert "caption a" not in call["content"]
        assert "MEDIA:" not in call["content"]


@pytest.mark.asyncio
async def test_album_over_ten_items_splits_into_multiple_groups(tmp_path):
    paths = []
    captions = []
    for i in range(12):
        p = tmp_path / f"img{i}.png"
        p.write_bytes(b"\x89PNG\r\n\x1a\n")
        paths.append(str(p))
        captions.append(f"cap {i}")

    response = _album_response(list(zip(paths, captions)))

    adapter = RecordingAdapter()
    await _run(adapter, response)

    # Telegram caps albums at 10 — 12 items should split into 10 + 2.
    assert len(adapter.media_group_sends) == 2
    assert len(adapter.media_group_sends[0]["items"]) == 10
    assert len(adapter.media_group_sends[1]["items"]) == 2
    assert adapter.image_file_sends == []


@pytest.mark.asyncio
async def test_text_prose_before_album_is_sent_and_media_blob_stripped(tmp_path):
    paths = [str(tmp_path / "a.png"), str(tmp_path / "b.png")]
    for p in paths:
        from pathlib import Path
        Path(p).write_bytes(b"\x89PNG\r\n\x1a\n")

    response = (
        "Here are the two renders you asked for:\n\n"
        f"MEDIA:{paths[0]}\ncap a\n"
        f"MEDIA:{paths[1]}\ncap b"
    )

    adapter = RecordingAdapter()
    await _run(adapter, response)

    # Prose was sent as a text message — but without MEDIA: lines or raw captions.
    text_messages = [c["content"] for c in adapter.sent]
    assert any("Here are the two renders" in m for m in text_messages)
    for m in text_messages:
        assert "MEDIA:" not in m

    # Album delivered as one send_media_group call.
    assert len(adapter.media_group_sends) == 1
    assert len(adapter.media_group_sends[0]["items"]) == 2
