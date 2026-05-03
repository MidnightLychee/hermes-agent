---
name: send-media-group
description: Send multiple images as an album / media group / photo gallery in a single chat message with per-item or shared captions. Use whenever you need to deliver 2+ pictures together on Telegram, Discord, Signal, Slack, or Feishu — e.g. "send me all the blue renders", "share the 10 reference images", "here is the photo album", "post the gallery". Covers the exact MEDIA: response shape Hermes' gateway parses into a native album, edge cases (auto-split over 10 items, per-item vs trailing captions, blank-line separators), and how each platform renders the result.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [messaging, album, media-group, telegram, discord, signal, slack, feishu, photo-album, gallery, multi-image, captions]
---

# send-media-group

Send multiple images as a single album with captions on every chat platform where Hermes has native grouping support. You write one response block, the gateway parses it into a `MediaGroupBlock`, and each adapter delivers it using its platform's native primitive.

## When to use this skill

Any time the user wants 2 or more images delivered together. Typical triggers:

- "send all the blue ones"
- "share the reference images"
- "post the gallery / album / photo collection"
- "send me every angle"

The same triggers apply in any language — the words "album", "gallery", "these images", "all of them", or the equivalent in the user's locale all qualify.

If you are sending a single image, do not use this shape — use `MEDIA:/path` followed by the caption as usual. This skill is only for 2+ items.

## Response shape (the exact syntax)

Consecutive `MEDIA:` lines form an album. Each caption goes on the line(s) directly after its `MEDIA:` line. No blank lines between items.

```
MEDIA:/tmp/cat.png
A fluffy orange cat
MEDIA:/tmp/dog.png
A happy golden retriever
MEDIA:/tmp/bird.png
A bright red cardinal
```

Renders as one album with three images, each carrying its own caption.

## Rules

1. **No blank lines between album items.** A blank line ends the current album and starts a new one.
2. **No prose between `MEDIA:` lines.** Text like "Next up:" or "And finally:" splits the album. Keep the rhythm `MEDIA:/path → caption → MEDIA:/path → caption`.
3. **Use `MEDIA:/absolute/path` for local files.** Never use `![alt](path)` markdown for local files in an album — that bypasses the parser.
4. **Shared caption shape.** If you want ONE caption to apply to the whole album instead of per-item captions, put it *after* all the `MEDIA:` lines, with no blank line:
   ```
   MEDIA:/tmp/a.png
   MEDIA:/tmp/b.png
   MEDIA:/tmp/c.png
   The three sunset shots from yesterday
   ```
5. **Auto-split at 10 items.** Telegram (and the others) cap an album at 10 media per message. The parser splits larger groups into chunks of 10 automatically — you can write 16 `MEDIA:` lines back-to-back and the platform will send one album of 10 + one of 6. Do not split manually.
6. **Starting a new album mid-response.** Insert exactly one blank line. The next `MEDIA:` begins a fresh album.
7. **Mixing prose with albums.** Prose paragraphs before or after an album are fine. Put a blank line between prose and the first `MEDIA:` line, and a blank line between the last caption and following prose. Prose text is sent as a separate message; the album follows.
8. **URLs work too.** `MEDIA:https://example.com/image.png` uses the remote image directly (downloaded by the adapter). Mix local and remote paths in the same album if you want.

## Worked examples

### Three images, per-item captions

```
MEDIA:/renders/blue/front.png
Front elevation, blue colorway
MEDIA:/renders/blue/rear.png
Rear elevation, blue colorway
MEDIA:/renders/blue/side.png
Side profile, blue colorway
```

### Six images, one shared caption

```
MEDIA:/renders/teardown/01.png
MEDIA:/renders/teardown/02.png
MEDIA:/renders/teardown/03.png
MEDIA:/renders/teardown/04.png
MEDIA:/renders/teardown/05.png
MEDIA:/renders/teardown/06.png
Teardown sequence, six steps
```

### Album preceded by prose, followed by prose

```
Here are the reference images you requested. I cropped each one to match the hero shot's aspect ratio.

MEDIA:/refs/a.jpg
Variant A — warm tint
MEDIA:/refs/b.jpg
Variant B — cool tint

Let me know which you prefer and I will render the final.
```

### Two separate albums in one response

```
MEDIA:/before/a.png
Before — corner 1
MEDIA:/before/b.png
Before — corner 2

MEDIA:/after/a.png
After — corner 1
MEDIA:/after/b.png
After — corner 2
```

The blank line between them tells the parser to emit two albums instead of one four-image album.

## How each platform renders it

Behavior is consistent — one visual "album per MediaGroupBlock" — but each platform's rendering differs. You do not need to change anything in your response; the adapter handles platform differences.

| Platform | Native primitive | What the user sees |
|---|---|---|
| **Telegram** | `sendMediaGroup` | One album bubble. Per-item captions display under each photo. |
| **Discord** | Multi-attachment message | One message with up to 10 attachments as an inline grid. Per-item captions appear as a numbered legend in the message body (and as alt-text on each image). |
| **Signal** | `send` RPC with multiple attachments | One message carrying the attachment strip. Per-item captions are folded into a numbered legend in the message body (Signal has no per-attachment caption primitive). |
| **Slack** | Batched `files_upload_v2` | One channel post with all files attached. Per-item captions appear as each file's `title` beneath the thumbnail, plus a numbered legend as the shared `initial_comment`. |
| **Feishu** | Rich-text `post` with interleaved rows | One chat bubble containing alternating caption paragraphs and inline images — the richest rendering of the group. |
| **WhatsApp / Matrix / iMessage / WeCom / WeChat / DingTalk** | None native | The adapter falls back to sending each item as an individual message with its caption. Still correct; just not visually grouped. |

The content you write is the same everywhere. Do not try to inline per-platform numbered legends yourself — the adapter already does that for you on the platforms that need it.

## Common mistakes

- Writing `![caption](path)` for local files. Markdown images only work for public URLs; for local paths, use `MEDIA:/absolute/path` every time.
- Adding "Here is image 1:" / "Here is image 2:" between `MEDIA:` lines. Any non-caption text between items ends the album.
- Leaving a blank line between an image and its caption. That breaks the caption off — caption goes on the line *immediately* after `MEDIA:`.
- Splitting a 15-image album into three 5-image responses "to avoid the 10 limit." Don't — write all 15 in one response; the parser auto-splits at 10.
- Mixing `MEDIA:` and `![alt](path)` in the same album. The parser groups by `MEDIA:` only; `![alt](path)` items end up as separate messages. Use one style per album.

## Non-image media

`MEDIA:/path.mp4` (video) and `MEDIA:/path.ogg` (audio) also parse as media items. If an album mixes images with non-image files, adapters that cannot group those natively (e.g. Signal grouping images but not mixing with audio in one post) fall back to per-item delivery for the non-conforming items. Stick to all-images for the most consistent rendering.

## Checklist before sending

1. 2+ media items? If not, use single-item `MEDIA:` syntax instead.
2. Each caption on the line immediately after its `MEDIA:` line? No blank line between them?
3. No prose interspersed between `MEDIA:` lines?
4. If you want a shared caption, it is after all `MEDIA:` lines with no blank line?
5. Local paths start with `/` (absolute)?

If all five pass, the gateway will deliver a native album.
