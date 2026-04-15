"""Tests for FeishuAdapter.send_media_group — interleaved post delivery.

Feishu's ``post`` message type renders each row of its ``content`` array
as a paragraph. An ``img`` row embeds an uploaded image inline. Sending a
single post with interleaved ``text``/``img`` rows delivers a captioned
album in one chat bubble — more expressive than Telegram's shared-caption
album.

Protocol: each image is uploaded via ``im.v1.image.create`` to obtain an
``image_key`` before the post message is sent.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.config import PlatformConfig
from gateway.platforms.base import MediaGroupItem
from gateway.platforms.feishu import FeishuAdapter


def _make_adapter(image_keys):
    cfg = PlatformConfig(
        enabled=True,
        token="fake",
        extra={"app_id": "cli_test", "app_secret": "secret-test"},
    )
    adapter = FeishuAdapter(cfg)

    client = MagicMock()
    keys_iter = iter(image_keys)
    upload_calls = []

    def _upload(req):
        upload_calls.append(req)
        r = MagicMock()
        r.code = 0
        r.success = MagicMock(return_value=True)
        r.data = MagicMock()
        r.data.image_key = next(keys_iter)
        return r

    client.im = MagicMock()
    client.im.v1 = MagicMock()
    client.im.v1.image = MagicMock()
    client.im.v1.image.create = MagicMock(side_effect=_upload)
    adapter._client = client
    adapter._build_image_upload_body = lambda image_type, image: {"image_type": image_type, "image": image}
    adapter._build_image_upload_request = lambda body: body
    adapter._extract_response_field = lambda resp, field: getattr(resp.data, field, None)

    send_calls = []

    async def _send_with_retry(**kwargs):
        send_calls.append(kwargs)
        resp = MagicMock()
        resp.success = MagicMock(return_value=True)
        return resp

    adapter._feishu_send_with_retry = _send_with_retry

    def _finalize(response, default_message):
        from gateway.platforms.base import SendResult
        return SendResult(success=True, message_id="msg-album")

    adapter._finalize_send_result = _finalize
    adapter._build_post_payload = lambda content: json.dumps({"zh_cn": {"title": "", "content": []}})

    return adapter, upload_calls, send_calls


@pytest.mark.asyncio
async def test_album_interleaves_captions_and_images(tmp_path):
    paths = []
    for name in ("a.png", "b.png", "c.png"):
        p = tmp_path / name
        p.write_bytes(b"\x89PNG\r\n\x1a\n")
        paths.append(str(p))

    adapter, upload_calls, send_calls = _make_adapter(
        image_keys=["k1", "k2", "k3"]
    )
    items = [
        MediaGroupItem(path_or_url=paths[0], caption="alpha"),
        MediaGroupItem(path_or_url=paths[1], caption="beta"),
        MediaGroupItem(path_or_url=paths[2], caption="gamma"),
    ]
    result = await adapter.send_media_group("oc_chat123", items)

    assert result.success
    assert len(upload_calls) == 3, "each image should be uploaded once"
    assert len(send_calls) == 1, "one post message carries the album"

    payload = json.loads(send_calls[0]["payload"])
    content = payload["zh_cn"]["content"]
    # Expect rows: [text(alpha)], [img(k1)], [text(beta)], [img(k2)], [text(gamma)], [img(k3)]
    assert content == [
        [{"tag": "text", "text": "alpha"}],
        [{"tag": "img", "image_key": "k1"}],
        [{"tag": "text", "text": "beta"}],
        [{"tag": "img", "image_key": "k2"}],
        [{"tag": "text", "text": "gamma"}],
        [{"tag": "img", "image_key": "k3"}],
    ]


@pytest.mark.asyncio
async def test_album_without_captions_just_images(tmp_path):
    paths = []
    for name in ("x.png", "y.png"):
        p = tmp_path / name
        p.write_bytes(b"\x89PNG\r\n\x1a\n")
        paths.append(str(p))

    adapter, upload_calls, send_calls = _make_adapter(image_keys=["k1", "k2"])
    items = [
        MediaGroupItem(path_or_url=paths[0]),
        MediaGroupItem(path_or_url=paths[1]),
    ]
    await adapter.send_media_group("oc_chat123", items)

    payload = json.loads(send_calls[0]["payload"])
    assert payload["zh_cn"]["content"] == [
        [{"tag": "img", "image_key": "k1"}],
        [{"tag": "img", "image_key": "k2"}],
    ]


@pytest.mark.asyncio
async def test_album_first_caption_only(tmp_path):
    paths = []
    for name in ("x.png", "y.png"):
        p = tmp_path / name
        p.write_bytes(b"\x89PNG\r\n\x1a\n")
        paths.append(str(p))
    adapter, _, send_calls = _make_adapter(image_keys=["k1", "k2"])
    items = [
        MediaGroupItem(path_or_url=paths[0], caption="header"),
        MediaGroupItem(path_or_url=paths[1]),
    ]
    await adapter.send_media_group("oc_chat123", items)
    payload = json.loads(send_calls[0]["payload"])
    assert payload["zh_cn"]["content"] == [
        [{"tag": "text", "text": "header"}],
        [{"tag": "img", "image_key": "k1"}],
        [{"tag": "img", "image_key": "k2"}],
    ]


@pytest.mark.asyncio
async def test_non_image_items_fall_back_to_per_item(tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    doc = tmp_path / "a.pdf"
    doc.write_bytes(b"%PDF-1.4\n")

    adapter, upload_calls, send_calls = _make_adapter(image_keys=["k1"])

    # Stub the base fallback so we can assert it ran
    fallback_called = []

    async def fake_super_send(self, chat_id, items, metadata=None):
        from gateway.platforms.base import SendResult
        fallback_called.append((chat_id, list(items)))
        return SendResult(success=True)

    # Patch the bound super().send_media_group via monkey-replacing a
    # method on the adapter's class chain. Simplest: override the method
    # name on the instance to call the base adapter's default.
    from gateway.platforms.base import BasePlatformAdapter
    adapter_super = BasePlatformAdapter.send_media_group.__get__(adapter)
    # Re-bind so the test can observe; we're not relying on super() semantics
    # because FeishuAdapter.send_media_group calls super().send_media_group
    # which resolves to BasePlatformAdapter.send_media_group.
    # Replace BasePlatformAdapter.send_media_group temporarily.
    original = BasePlatformAdapter.send_media_group
    BasePlatformAdapter.send_media_group = fake_super_send
    try:
        items = [
            MediaGroupItem(path_or_url=str(img), caption="pic"),
            MediaGroupItem(
                path_or_url=str(doc), caption="doc", send_as_document=True,
            ),
        ]
        result = await adapter.send_media_group("oc_chat123", items)
    finally:
        BasePlatformAdapter.send_media_group = original

    assert result.success
    # No post was sent because we fell back to per-item
    assert send_calls == []
    assert upload_calls == []
    assert len(fallback_called) == 1


@pytest.mark.asyncio
async def test_album_all_missing_returns_failure(tmp_path):
    adapter, upload_calls, send_calls = _make_adapter(image_keys=[])
    items = [
        MediaGroupItem(path_or_url=str(tmp_path / "nope.png"), caption="x"),
    ]
    result = await adapter.send_media_group("oc_chat123", items)
    assert not result.success
    assert upload_calls == []
    assert send_calls == []
