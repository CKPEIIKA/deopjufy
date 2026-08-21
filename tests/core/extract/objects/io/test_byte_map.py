from __future__ import annotations

import json
from pathlib import Path

from deopjufier.detect import detect_file
from deopjufier.extract.byte_map import extract_byte_map
from deopjufier.manifest import ManifestItem, make_manifest


def test_extract_byte_map_partitions_and_reconstructs_every_source_byte(tmp_path: Path) -> None:
    data = b"0123456789"
    sample = tmp_path / "sample.opju"
    sample.write_bytes(data)
    manifest = make_manifest(
        sample,
        detect_file(sample),
        "native-parser",
        size_bytes=len(data),
        sha256="unused-in-unit-test",
    )
    manifest.add_item(
        ManifestItem(
            kind="worksheet",
            name="Book1",
            status="partial",
            confidence=0.9,
            discovery_type="parser_window",
            heuristic=False,
            range_start=2,
            range_end=5,
        )
    )
    manifest.add_item(
        ManifestItem(
            kind="table_scan",
            name="scan",
            status="extracted",
            confidence=0.4,
            discovery_type="heuristic_scan",
            heuristic=True,
            range_start=7,
            range_end=9,
        )
    )
    manifest.add_item(
        ManifestItem(
            kind="matrix",
            name="zero_length_synthetic",
            status="extracted",
            confidence=0.9,
            discovery_type="parser_window",
            heuristic=False,
            offset=0,
            length=0,
            range_start=0,
            range_end=len(data),
        )
    )

    count = extract_byte_map(sample, tmp_path / "out", manifest, force=True, file_data=data)

    index_path = tmp_path / "out/byte-map/index.json"
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    assert count == payload["byte_accounting"]["segment_count"]
    assert payload["byte_accounting"] == {
        "accounted_bytes": len(data),
        "class_bytes": {"heuristic": 2, "parser_bounded": 3, "unknown": 5},
        "complete": True,
        "segment_count": 5,
        "unaccounted_bytes": 0,
    }
    assert payload["reconstruction"]["matches_input"] is True
    reconstructed = b"".join((index_path.parent / segment["path"]).read_bytes() for segment in payload["segments"])
    assert reconstructed == data
    byte_map_item = manifest.items[-1]
    assert byte_map_item.kind == "byte_map"
    assert byte_map_item.status == "extracted"
    assert byte_map_item.verification == "exact"
    assert byte_map_item.source_ranges == [{"start": 0, "end": len(data)}]
