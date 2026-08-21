"""Image signature handlers for embedded binary resources."""

from collections.abc import Iterable
from pathlib import Path

from deopjufier.blocks_parse import *


def _signature_hits_in_window(
    window: bytes,
    window_start: int,
    signatures: Iterable[tuple[bytes, str]],
) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    for signature, kind in signatures:
        search_pos = 0
        while True:
            hit = window.find(signature, search_pos)
            if hit < 0:
                break
            hits.append((window_start + hit, kind))
            search_pos = hit + 1
    return hits


def _dedupe(blocks: list[ImageBlock]) -> list[ImageBlock]:
    seen: list[ImageBlock] = []
    for block in sorted(blocks, key=lambda b: b.offset):
        if not seen:
            seen.append(block)
            continue
        prev = seen[-1]
        if block.offset < prev.offset + max(prev.length, 1):
            continue
        seen.append(block)
    return seen


def _iter_signature_offsets(path: Path, signatures: Iterable[tuple[bytes, str]]) -> list[tuple[int, str]]:
    max_sig_len = max(len(sig) for sig, _ in signatures)
    overlap = max_sig_len - 1
    signature_hits: list[tuple[int, str]] = []

    with path.open("rb") as handle:
        carry = b""
        scanned = 0
        while True:
            chunk = handle.read(_IMAGE_SCAN_WINDOW_BYTES)
            if not chunk:
                break

            window = carry + chunk
            window_start = scanned - len(carry)
            signature_hits.extend(
                _signature_hits_in_window(
                    window,
                    window_start,
                    signatures,
                )
            )

            scanned += len(chunk)
            if overlap > 0:
                carry = window[-overlap:] if len(window) > overlap else window

    signature_hits.sort(key=lambda item: item[0])
    return signature_hits


def _append_signature_block(
    blocks: list[ImageBlock],
    path: Path,
    start: int,
    kind: str,
    file_size: int,
    *,
    allow_invalid_jpeg: bool,
) -> None:
    max_scan = file_size - start
    appenders = {
        "png": _append_png_signature_block,
        "gif": _append_gif_signature_block,
        "bmp": _append_bmp_signature_block,
        "pdf": _append_pdf_signature_block,
    }
    appender = appenders.get(kind)
    if appender is None:
        if kind == "jpeg":
            _append_jpeg_signature_block(
                blocks=blocks,
                path=path,
                start=start,
                max_scan=max_scan,
                allow_invalid_jpeg=allow_invalid_jpeg,
            )
        return

    appender(
        blocks=blocks,
        path=path,
        start=start,
        max_scan=max_scan,
    )


def _append_png_signature_block(
    *,
    blocks: list[ImageBlock],
    path: Path,
    start: int,
    max_scan: int,
) -> None:
    length, error = _find_png_block_in_file(path, start, scan_limit=max_scan)
    if length is not None:
        blocks.append(
            ImageBlock(
                start,
                length,
                "png",
                "png",
                valid=error is None,
                error=error,
            )
        )


def _append_jpeg_signature_block(
    *,
    blocks: list[ImageBlock],
    path: Path,
    start: int,
    max_scan: int,
    allow_invalid_jpeg: bool = False,
) -> None:
    length, error = _find_jpeg_length_in_file(
        path,
        start,
        scan_limit=min(max_scan, _JPEG_MAX_SCAN_BYTES),
        allow_fallback=allow_invalid_jpeg,
    )
    if length is not None:
        blocks.append(
            ImageBlock(
                start,
                length,
                "jpeg",
                "jpg",
                valid=error is None,
                error=error,
            )
        )
        return

    if allow_invalid_jpeg and error is not None:
        blocks.append(
            ImageBlock(
                start,
                min(max_scan, _JPEG_MAX_SCAN_BYTES),
                "jpeg",
                "jpg",
                valid=False,
                error=error,
            )
        )


def _append_gif_signature_block(
    *,
    blocks: list[ImageBlock],
    path: Path,
    start: int,
    max_scan: int,
) -> None:
    gif_len = _find_gif_length_in_file(
        path,
        start,
        scan_limit=min(max_scan, _GIF_MAX_SCAN_BYTES),
    )
    if gif_len is not None:
        blocks.append(ImageBlock(start, gif_len, "gif", "gif", valid=True))
        return

    blocks.append(
        ImageBlock(
            start,
            min(_INVALID_GIF_SAMPLE_BYTES, max_scan),
            "gif",
            "gif",
            valid=False,
            error="gif_invalid",
        )
    )


def _append_bmp_signature_block(
    *,
    blocks: list[ImageBlock],
    path: Path,
    start: int,
    max_scan: int,
) -> None:
    bmp_length = _find_bmp_length_in_file(
        path,
        start,
        scan_limit=min(max_scan, _BMP_MAX_SCAN_BYTES),
    )
    if bmp_length is not None:
        blocks.append(ImageBlock(start, bmp_length, "bmp", "bmp", valid=True))


def _append_pdf_signature_block(
    *,
    blocks: list[ImageBlock],
    path: Path,
    start: int,
    max_scan: int,
) -> None:
    pdf_length = _find_pdf_length_in_file(
        path,
        start,
        scan_limit=min(max_scan, _PDF_MAX_SCAN_BYTES),
    )
    if pdf_length is not None:
        blocks.append(ImageBlock(start, pdf_length, "pdf", "pdf", valid=True))


def _make_svg_block(start: int, length: int) -> ImageBlock | None:
    if length <= 0:
        return None
    return ImageBlock(offset=start, length=length, kind="svg", extension="svg")


def _close_pending_svg(
    window: memoryview,
    window_start: int,
    pending_start: tuple[int, int],
) -> tuple[list[ImageBlock], tuple[int, int] | None]:
    start_abs, start_rel = pending_start
    end_match = _SVG_END_RE.search(window, start_rel - window_start)
    if end_match is None:
        return [], pending_start

    block = _make_svg_block(start_abs, end_match.end() + window_start - start_abs)
    if block is None:
        return [], None
    return [block], None


def _scan_svg_window(
    window: memoryview,
    window_start: int,
    *,
    pending_start: tuple[int, int] | None = None,
) -> tuple[list[ImageBlock], tuple[int, int] | None]:
    hits: list[ImageBlock] = []
    next_idx = 0

    if pending_start is not None:
        pending_hits, pending_start = _close_pending_svg(
            window,
            window_start,
            pending_start,
        )
        hits.extend(pending_hits)
        if pending_start is not None:
            return hits, pending_start

    while True:
        start_match = _SVG_START_RE.search(window, next_idx)
        if start_match is None:
            break

        start_abs = start_match.start() + window_start
        end_match = _SVG_END_RE.search(window, start_match.end())
        if end_match is not None:
            length = end_match.end() + window_start - start_abs
            svg_block = _make_svg_block(start_abs, length)
            if svg_block is not None:
                hits.append(svg_block)
            next_idx = end_match.end()
        else:
            pending_start = (start_abs, start_match.start())
            break

    return hits, pending_start


def _iter_svg_blocks(path: Path, *, scan_limit: int | None = None) -> list[ImageBlock]:
    if scan_limit is not None and scan_limit <= 0:
        return []

    max_sig_len = 5
    overlap = max_sig_len - 1
    hits: list[ImageBlock] = []
    pending_start: tuple[int, int] | None = None
    scanned = 0
    with path.open("rb") as handle:
        carry = b""
        while True:
            remaining = scan_limit - scanned if scan_limit is not None else _IMAGE_SCAN_WINDOW_BYTES
            if remaining <= 0:
                break
            chunk = handle.read(min(_IMAGE_SCAN_WINDOW_BYTES, remaining))
            if not chunk:
                break

            window = carry + chunk
            window_start = scanned - len(carry)
            scanned += len(chunk)

            window_data = memoryview(window)
            new_hits, pending_start = _scan_svg_window(
                window_data,
                window_start,
                pending_start=pending_start,
            )
            hits.extend(new_hits)
            carry = window[-overlap:] if len(window) > overlap else window

    hits.sort(key=lambda item: item.offset)
    return hits


def find_image_blocks(path: Path, *, allow_invalid_jpeg: bool = False) -> list[ImageBlock]:
    file_stats = path.stat()
    cache_key: tuple[Path, int, int, bool] = (
        path,
        file_stats.st_size,
        file_stats.st_mtime_ns,
        allow_invalid_jpeg,
    )
    if cache_key in _IMAGE_BLOCK_CACHE:
        return list(_IMAGE_BLOCK_CACHE[cache_key])

    signatures: tuple[tuple[bytes, str], ...] = (
        (PNG_SIG, "png"),
        (JPEG_SIG, "jpeg"),
        (GIF_SIGS[0], "gif"),
        (GIF_SIGS[1], "gif"),
        (BMP_SIG, "bmp"),
        (PDF_SIG, "pdf"),
    )
    signature_hits = _iter_signature_offsets(path, signatures=signatures)
    blocks: list[ImageBlock] = []

    for start, kind in signature_hits:
        _append_signature_block(
            blocks,
            path,
            start,
            kind,
            file_stats.st_size,
            allow_invalid_jpeg=allow_invalid_jpeg,
        )

    blocks.extend(_iter_svg_blocks(path))

    resolved = _dedupe(blocks)
    _IMAGE_BLOCK_CACHE[cache_key] = resolved
    return list(resolved)


def _find_gif_length_in_file(
    path: Path,
    start: int,
    *,
    scan_limit: int = _GIF_MAX_SCAN_BYTES,
) -> int | None:
    if scan_limit <= 0:
        return None
    if start < 0:
        return None

    with path.open("rb") as fh:
        fh.seek(start)
        data = fh.read(scan_limit)
        if len(data) < 13:
            return None
        return _parse_gif_payload_length(data, 0)


def _find_bmp_length_in_file(
    path: Path,
    start: int,
    *,
    scan_limit: int = _BMP_MAX_SCAN_BYTES,
) -> int | None:
    if scan_limit <= 0:
        return None
    if start < 0:
        return None

    with path.open("rb") as fh:
        fh.seek(start)
        data = fh.read(scan_limit)
        if len(data) < 54:
            return None
        payload_length = _parse_bmp_payload_length(data, 0)
        if payload_length is None:
            return None
        return payload_length


def find_all_blocks(
    path: Path,
    types: Iterable[str] | None = None,
    *,
    allow_invalid_jpeg: bool = False,
) -> list[ImageBlock]:
    requested = {t.lower() for t in types} if types is not None else {"png", "jpeg", "gif", "bmp", "svg", "pdf"}
    blocks = find_image_blocks(path, allow_invalid_jpeg=allow_invalid_jpeg)
    return [b for b in blocks if b.kind in requested]


__all__ = [name for name in globals() if not name.startswith("__")]
