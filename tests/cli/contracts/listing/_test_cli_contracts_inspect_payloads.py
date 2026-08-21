"""Core CLI and helper contract tests for deopjufier."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deopjufier.cli import NATIVE_BACKEND, main
from deopjufier.detect import detect_file
from deopjufier.errors import CorruptedInputError
from deopjufier.inventory import OpjObjectBoundary
from deopjufier.session import ExtractionSession
from tests.test_core_unit_coverage_utils import _repo_root, _resolve_synthetic_fixture

REPO_ROOT = _repo_root(Path(__file__))


def test_detect_prefers_extension_over_magic_signature(tmp_path: Path) -> None:
    candidate = tmp_path / "fake.opju"
    candidate.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)

    detected = detect_file(candidate)
    assert detected.detected_type == "opju"
    assert detected.reason == "extension"


def test_detect_magic_magic_falls_back_for_unknown_extension(tmp_path: Path) -> None:
    candidate = tmp_path / "sig.bin"
    candidate.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)

    detected = detect_file(candidate)
    assert detected.detected_type == "png"
    assert detected.reason == "magic"


def test_detect_magic_prefers_jpeg_magic_over_other_known(tmp_path: Path) -> None:
    candidate = tmp_path / "sig.bin"
    candidate.write_bytes(b"\xff\xd8\xff\xd9" + b"\x00" * 16)

    detected = detect_file(candidate)
    assert detected.detected_type == "jpeg"
    assert detected.reason == "magic"


def test_detect_magic_prefers_opju_magic_for_unknown_extension(tmp_path: Path) -> None:
    candidate = tmp_path / "sig.bin"
    candidate.write_bytes(b"CPYUA\x00\x00\x00\x00" + b"\x00" * 16)

    detected = detect_file(candidate)
    assert detected.detected_type == "opju"
    assert detected.reason == "magic"


def test_detect_magic_prefers_opj_magic_for_unknown_extension(tmp_path: Path) -> None:
    candidate = tmp_path / "sig.bin"
    candidate.write_bytes(b"CPYA\x00\x00\x00\x00" + b"\x00" * 16)

    detected = detect_file(candidate)
    assert detected.detected_type == "opj"
    assert detected.reason == "magic"


def test_detect_unknown_returns_unknown(tmp_path: Path) -> None:
    candidate = tmp_path / "raw.bin"
    candidate.write_bytes(b"\x00\x01\x02")

    detected = detect_file(candidate)
    assert detected.detected_type == "unknown"
    assert detected.confidence == 0.05
    assert detected.reason == "no-match"


def test_inspect_includes_opju_raw_dump_crosswalk_summary(capsys: pytest.CaptureFixture[str]) -> None:
    sample = _resolve_synthetic_fixture(Path(__file__), "synthetic-cpyua.opju")
    if not sample.exists():
        pytest.skip("synthetic OPJU fixture missing.")

    code = main(["inspect", str(sample), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["detected_type"] == "opju"
    crosswalk = payload["opju_raw_crosswalk"]
    assert isinstance(crosswalk, list)
    assert len(crosswalk) >= 1
    first = crosswalk[0]
    assert {"name", "offset", "length", "source_object_path", "raw_dump_crosswalk"} <= set(first.keys())
    assert isinstance(first["raw_dump_crosswalk"], list)


def test_inspect_includes_compact_parser_evidence_counts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    sample = REPO_ROOT / "refs" / "openopj" / "support" / "test.opj"
    if not sample.exists():
        pytest.skip("OpenOPJ reference fixture is not present.")

    code = main(["inspect", str(sample), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    counts = payload["counts"]
    evidence = counts["parser_evidence_counts"]
    assert set(evidence.keys()) >= {"kind", "object_kind", "discovery_type", "heuristic"}
    assert "object_discovery" in evidence["discovery_type"]
    assert int(evidence["heuristic"]["true"]) + int(evidence["heuristic"]["false"]) == counts["origin_objects"]
    assert sum(int(value) for value in evidence["kind"].values()) == counts["origin_objects"]


def test_list_unsupported_file_with_signature_stays_empty(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "odd.bin"
    sample.write_bytes(b"xx" + b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x00IEND\xae\x42\x60\x82")

    code = main(["list", str(sample), "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert code == 3
    assert payload["detected_type"] == "unknown"
    assert payload["support_class"] == "heuristic"
    assert payload["parser_status"] == "unsupported"
    assert payload["warnings"] == ["Native parser does not support detected type 'unknown'."]
    assert payload["status"] == "unsupported"
    assert payload["items"] == []


def test_inspect_unsupported_file_type_returns_code_three(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "unknown.bin"
    sample.write_bytes(b"abc")

    code = main(["inspect", str(sample), "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert code == 3
    assert payload["detected_type"] == "unknown"
    assert payload["path"] == str(sample)
    assert payload["support_class"] == "heuristic"
    assert payload["parser_status"] == "unsupported"
    assert payload["warnings"] == ["Native parser does not support detected type 'unknown'."]
    assert payload["status"] == "unsupported"
    assert payload["counts"]["items"] == 0
    assert payload["counts"]["images"] == 0
    assert payload["counts"]["artifact_counts"] == {}


def test_inspect_reports_magic_format_hints_for_extension_mismatch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sample = tmp_path / "renamed_opj.opju"
    sample.write_bytes(b"CPYA" + b"\x00" * 12)

    code = main(["inspect", str(sample), "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert code == 0
    assert payload["detected_type"] == "opj"
    assert payload["format_hints"]["magic_type"] == "opj"
    assert payload["format_hints"]["family_hint"] == "legacy-opj"
    assert not any("Header signature indicates" in message for message in payload["warnings"])


def test_rejects_backend_argument(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "file.opju"
    sample.write_text("fake opju", encoding="utf-8")

    code = main(["inspect", str(sample), "--backend", "native"])
    captured = capsys.readouterr()

    assert code == 2
    assert "unrecognized arguments" in captured.err


def test_inspect_includes_tool_metadata(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "tool.opju"
    sample.write_text("binary\n", encoding="utf-8")

    code = main(["inspect", str(sample), "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert code == 0
    assert payload["tool"]["name"] == "deopjufy"
    assert payload["tool"]["version"]
    assert payload["tool"]["backend"] == NATIVE_BACKEND
    assert payload["parser_status"] == "ok"
    assert payload["warnings"] == []


def test_inspect_parser_error_reports_error_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sample = tmp_path / "parser-error.opju"
    sample.write_bytes(b"CPYA")

    def _raise(_self: ExtractionSession, *_args, **_kwargs) -> list[object]:
        raise CorruptedInputError("truncated header")

    monkeypatch.setattr("deopjufier.app.ExtractionSession.objects", _raise)

    code = main(["inspect", str(sample), "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert code == 6
    assert payload["parser_status"] == "error"
    assert payload["status"] == "unsupported"
    assert payload["support_class"] == "failed"
    assert payload["warnings"] == ["Native parser error: truncated header"]


def test_inspect_unsupported_binary_with_embedded_signatures_still_reports_zero_counts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sample = tmp_path / "odd.bin"
    sample.write_bytes(b"xx" + b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x00IEND\xae\x42\x60\x82")

    code = main(["inspect", str(sample), "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert code == 3
    assert payload["detected_type"] == "unknown"
    assert payload["support_class"] == "heuristic"
    assert payload["parser_status"] == "unsupported"
    assert payload["warnings"] == ["Native parser does not support detected type 'unknown'."]
    assert payload["status"] == "unsupported"
    assert payload["counts"]["items"] == 0
    assert payload["counts"]["images"] == 0
    assert payload["counts"]["artifact_counts"] == {}


def test_inspect_recognized_file_reports_status_and_counts(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "opju.opju"
    sample.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x00IEND\xae\x42\x60\x82")

    code = main(["inspect", str(sample), "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert code == 0
    assert payload["status"] == "ok"
    assert payload["parser_status"] == "ok"
    assert payload["support_class"] == "heuristic"
    assert payload["warnings"] == []
    assert payload["counts"]["images"] >= 1
    assert payload["counts"]["items"] >= 1
    assert payload["counts"]["artifact_counts"]["image"] >= 1


def test_inspect_payload_includes_coverage_scope_and_verification(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sample = tmp_path / "legacy.opj"
    sample.write_bytes(b"CPYA")

    code = main(["inspect", str(sample), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["coverage_scope"] in {"recognized", "recovered"}
    assert payload["verification"] == "unverified"


def test_inspect_support_class_for_opj(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "legacy.opj"
    sample.write_bytes(b"CPYA")

    code = main(["inspect", str(sample), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["detected_type"] == "opj"
    assert payload["support_class"] == "heuristic"
    assert payload["parser_status"] in {"empty", "ok"}


def test_inspect_opju_without_parser_backed_artifacts_is_unknown(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sample = tmp_path / "no-opju-evidence.opju"
    sample.write_bytes(b"Graph1\nNote1\nFunction1\nExcelA\nMatrix1\nBook1_A\n")

    code = main(["inspect", str(sample), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["detected_type"] == "opju"
    assert payload["support_class"] == "heuristic"


def test_inspect_synthetic_binary_opju_without_parser_records_is_unknown(
    capsys: pytest.CaptureFixture[str],
) -> None:
    sample = _resolve_synthetic_fixture(Path(__file__), "synthetic-cpyua-binary.opju")
    if not sample.exists():
        pytest.skip("synthetic-cpyua-binary fixture missing")

    code = main(["inspect", str(sample), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["detected_type"] == "opju"
    assert payload["support_class"] == "parser"


def test_inspect_empty_opj_file_marks_empty(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "empty.opj"
    sample.write_bytes(b"\x00\x00")

    code = main(["inspect", str(sample), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["detected_type"] == "opj"
    assert payload["support_class"] == "parser"
    assert payload["parser_status"] == "empty"
    assert payload["status"] == "empty"
    assert payload["warnings"] == ["Native parser found no listable items."]
    assert payload["counts"]["items"] == 0


def test_inspect_missing_file_still_emits_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "missing.opju"
    code = main(["inspect", str(sample), "--json"])

    payload = json.loads(capsys.readouterr().out)

    assert code == 1
    assert payload["path"] == str(sample)
    assert payload["parser_status"] == "unsupported"
    assert payload["status"] == "unsupported"
    assert payload["support_class"] == "heuristic"
    assert payload["warnings"] == [f"Input file not found: {sample}"]


def test_list_missing_file_still_emits_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "missing.opju"
    code = main(["list", str(sample), "--json"])

    payload = json.loads(capsys.readouterr().out)

    assert code == 1
    assert payload["file"] == str(sample)
    assert payload["parser_status"] == "unsupported"
    assert payload["status"] == "unsupported"
    assert payload["support_class"] == "heuristic"
    assert payload["warnings"] == [f"Input file not found: {sample}"]


def test_inspect_failure_payload_stays_schema_stable(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "missing.opju"
    code = main(["inspect", str(sample), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 1
    assert payload["parser_status"] == "unsupported"
    assert isinstance(payload["tool"], dict)
    assert payload["support_class"] == "heuristic"
    assert payload["format_hints"] == {}
    assert payload["embedded_signatures"] == {
        "total_blocks": 0,
        "counts_by_kind": {},
        "sampled_blocks": [],
    }
    assert isinstance(payload["parser_warnings"], list)
    assert len(payload["parser_warnings"]) == 1
    assert payload["parser_warnings"][0]["code"] == "command-exec-error"


def test_list_failure_payload_stays_schema_stable(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "missing.opju"
    code = main(["list", str(sample), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 1
    assert payload["parser_status"] == "unsupported"
    assert payload["items"] == []
    assert payload["embedded_signatures"] == {
        "total_blocks": 0,
        "counts_by_kind": {},
        "sampled_blocks": [],
    }
    assert isinstance(payload["parser_warnings"], list)
    assert len(payload["parser_warnings"]) == 1
    assert payload["parser_warnings"][0]["code"] == "command-exec-error"


def test_inspect_counts_include_origin_object_inventory(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "with_objects.opj"
    sample.write_bytes(b"CPYA\0Book1_A\0Graph1\0PdMSheet1\0Note1\0Function1\0ExcelA\0__Meta\0")

    code = main(["inspect", str(sample), "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert code == 0
    assert payload["status"] == "ok"
    assert payload["counts"]["items"] >= 7
    assert payload["counts"]["images"] == 0
    assert payload["counts"]["origin_objects"] >= 2
    counts_by_kind = payload["counts"]["origin_object_kinds"]
    assert counts_by_kind["worksheet"] >= 1
    assert counts_by_kind["graph"] >= 1
    assert counts_by_kind["matrix"] >= 1
    assert counts_by_kind["note"] >= 1
    assert counts_by_kind["function"] >= 1
    assert counts_by_kind["excel"] >= 1
    assert counts_by_kind["meta"] >= 1


def test_inspect_reports_parser_backed_and_heuristic_counts_separately(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = tmp_path / "boundary-counts.opj"
    header = b"CPYA 4.2673 552#\n"
    sample.write_bytes(header + b"prefix Graph1")

    monkeypatch.setattr(
        "deopjufier.inventory.parse_opj_boundaries",
        lambda *_args, **_kwargs: [
            OpjObjectBoundary(
                kind="worksheet",
                name="Book1_A",
                source_object_path="Book/Book1_A",
                start_offset=len(header),
                end_offset=len(header) + 7,
                length=7,
                confidence=0.88,
                parser_rule="test",
            )
        ],
    )

    code = main(["inspect", str(sample), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    counts = payload["counts"]
    discovery_types = counts["origin_object_discovery_types"]
    boundary_kinds = counts["origin_object_boundary_kinds"]
    heuristic_kinds = counts["origin_object_heuristic_kinds"]

    assert discovery_types["opj_boundary"] >= 1
    assert discovery_types["object_discovery"] >= 1
    assert boundary_kinds["worksheet"] >= 1
    assert "graph" in heuristic_kinds


def test_list_payload_includes_status(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "objects.opj"
    sample.write_bytes(b"CPYA\0Book1_A\0Graph1\0")
    main(["list", str(sample), "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["status"] == "ok"
    assert payload["support_class"] == "heuristic"
    assert payload["parser_status"] == "ok"
    assert payload["warnings"] == []


@pytest.mark.parametrize("command", ["inspect", "list"])
def test_signature_scan_not_repeated_for_supported_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    sample = tmp_path / "sample.opj"
    sample.write_bytes(b"CPYA\0Book1_A\0Graph1\0PdMSheet1\0")
    calls = 0

    from deopjufier import blocks
    from deopjufier import session as session_module

    original = blocks.find_all_blocks

    def _counting_blocks(path, types=None):
        nonlocal calls
        calls += 1
        return original(path, types=types)

    monkeypatch.setattr(blocks, "find_all_blocks", _counting_blocks)
    monkeypatch.setattr(session_module, "find_all_blocks", _counting_blocks)

    code = main([command, str(sample)])
    assert code == 0
    assert calls == 1


def test_inspect_payload_is_deterministic_for_same_input(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "repeat.opju"
    sample.write_bytes(b"Book1_A\n1 2 3\nGraph1\n")

    code_a = main(["inspect", str(sample), "--json"])
    payload_a = json.loads(capsys.readouterr().out)

    code_b = main(["inspect", str(sample), "--json"])
    payload_b = json.loads(capsys.readouterr().out)

    assert code_a == code_b == 0
    assert payload_a == payload_b


def test_list_payload_is_deterministic_for_same_input(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "repeat.opju"
    sample.write_bytes(b"Book1_A\n1 2 3\nGraph1\n")

    code_a = main(["list", str(sample), "--json"])
    payload_a = json.loads(capsys.readouterr().out)

    code_b = main(["list", str(sample), "--json"])
    payload_b = json.loads(capsys.readouterr().out)

    assert code_a == code_b == 0
    assert payload_a == payload_b
