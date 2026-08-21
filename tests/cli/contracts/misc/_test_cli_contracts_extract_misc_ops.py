from tests.cli.contracts.misc._test_cli_contracts_extract_misc_common import *  # noqa: F403
from tests.test_core_unit_coverage_utils import _resolve_tests_fixture


def test_extract_marks_partial_for_malformed_preview_payload(tmp_path: Path) -> None:
    sample = tmp_path / "malformed_preview.opj"
    sample.write_bytes(b"CPYA" + b"Graph1\x00" + b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x00IEND" + b"\x00\x00\x00\x00")
    output = tmp_path / "out"
    manifest = output / "manifest.json"

    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(output),
            "--extended",
            "--no-strings",
            "--no-tables",
        ]
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))

    assert code == 0
    assert payload["status"] in {"ok", "partial"}
    assert any(
        item.get("kind") in {"graph", "graph_preview", "malformed_graph_preview"}
        and item.get("status") in {"partial", "unsupported"}
        for item in payload["items"]
    )
    assert any(
        "No valid image blocks were extracted" in warning or "No recognizable image blocks were found." in warning
        for warning in payload["warnings"]
    )


def test_extract_force_keeps_unsupported_collection_markers_with_existing_outputs(tmp_path: Path) -> None:
    sample = tmp_path / "small-force-regression.opj"
    sample.write_bytes(b"CPYA 6.0 552#\nBook1_A\n")

    output = tmp_path / "out"
    manifest = output / "manifest.json"

    first_code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(output),
            "--extended",
            "--no-strings",
            "--no-images",
        ]
    )
    assert first_code in {0, 4}
    first_payload = json.loads(manifest.read_text(encoding="utf-8"))

    first_artifacts = [
        item
        for item in first_payload["items"]
        if item.get("status") in {"extracted", "partial"}
        and not str(item.get("name", "")).endswith("_collection")
        and isinstance(item.get("path"), str)
        and (item.get("path") or "") != ""
    ]
    assert first_artifacts, "Expected at least one extractable artifact for skip/force behavior checks."

    second_code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(output),
            "--extended",
            "--no-strings",
            "--no-images",
        ]
    )
    assert second_code in {0, 4}
    second_payload = json.loads(manifest.read_text(encoding="utf-8"))

    assert any(
        item.get("kind") == "matrix"
        and item.get("name") == "matrix_collection"
        and item.get("status") == "unsupported"
        and item.get("error") == "no_matrix_objects"
        for item in second_payload["items"]
    )
    assert any(item.get("status") == "skipped" for item in second_payload["items"])

    third_code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(output),
            "--extended",
            "--no-strings",
            "--no-images",
            "--force",
        ]
    )
    assert third_code in {0, 4}
    third_payload = json.loads(manifest.read_text(encoding="utf-8"))

    assert any(
        item.get("kind") == "matrix"
        and item.get("name") == "matrix_collection"
        and item.get("status") == "unsupported"
        and item.get("error") == "no_matrix_objects"
        for item in third_payload["items"]
    )


@pytest.mark.parametrize(
    ("sample", "unsupported_marker"),
    [
        (
            _resolve_tests_fixture(
                Path(__file__),
                Path("fixtures") / "synthetic" / "synthetic-cpyua-binary.opju",
            ),
            ("note", "note_collection", "no_note_objects"),
        ),
    ],
)
def test_extract_unsupported_collections_remain_visible_with_and_without_force(
    sample: Path,
    unsupported_marker: tuple[str, str, str],
    tmp_path: Path,
) -> None:
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    output = tmp_path / "out"
    manifest_path = output / "manifest.json"

    first_code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(output),
            "--no-images",
            "--no-tables",
            "--no-strings",
        ]
    )
    assert first_code in {0, 4}
    first_payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    first_artifacts = [
        item
        for item in first_payload["items"]
        if item.get("status") in {"extracted", "partial"}
        and not str(item.get("name", "")).endswith("_collection")
        and item.get("path")
    ]
    assert first_artifacts, "Expected at least one extractable artifact for unsupported marker regression."

    kind, name, error = unsupported_marker
    baseline_unsupported = [
        item
        for item in first_payload["items"]
        if item.get("kind") == kind
        and item.get("name") == name
        and item.get("status") == "unsupported"
        and item.get("error") == error
    ]
    assert baseline_unsupported, f"Expected unsupported collection marker {kind}/{name}:{error} in baseline extract"

    second_code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(output),
            "--no-images",
            "--no-tables",
            "--no-strings",
        ]
    )
    assert second_code in {0, 4}
    second_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    second_unsupported = [
        item
        for item in second_payload["items"]
        if item.get("kind") == kind
        and item.get("name") == name
        and item.get("status") == "unsupported"
        and item.get("error") == error
    ]
    assert second_unsupported, f"Unsupported marker {kind}/{name}:{error} disappeared without --force"
    assert any(
        item.get("status") == "skipped" and not str(item.get("name", "")).endswith("_collection")
        for item in second_payload["items"]
    )

    third_code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(output),
            "--no-images",
            "--no-tables",
            "--no-strings",
            "--force",
        ]
    )
    assert third_code in {0, 4}
    third_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    third_unsupported = [
        item
        for item in third_payload["items"]
        if item.get("kind") == kind
        and item.get("name") == name
        and item.get("status") == "unsupported"
        and item.get("error") == error
    ]
    assert third_unsupported, f"Unsupported marker {kind}/{name}:{error} disappeared with --force"


def test_list_payload_marks_unsupported(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "unknown.bin"
    sample.write_bytes(b"plain text")

    code = main(["list", str(sample), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 3
    assert payload["status"] == "unsupported"
    assert payload["parser_status"] == "unsupported"
    assert payload["support_class"] == "heuristic"
    assert payload["warnings"] == ["Native parser does not support detected type 'unknown'."]


def test_extract_rejects_unrecognized_input_without_manifest(tmp_path: Path) -> None:
    sample = tmp_path / "other.txt"
    sample.write_text("random", encoding="utf-8")
    output = tmp_path / "out"

    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(output),
            "--no-images",
        ]
    )

    assert code == 3
    assert not output.exists()


def test_dump_block_zero_length_emits_empty_payload(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "sample.bin"
    sample.write_bytes(b"ABCDEF")

    code = main(["dump-block", str(sample), "--offset", "2", "--length", "0"])
    captured = capsys.readouterr()

    assert code == 0
    assert captured.out == ""


def test_dump_block_out_of_range_is_corrupted_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "sample.bin"
    sample.write_bytes(b"ABCDEF")

    code = main(["dump-block", str(sample), "--offset", "999", "--length", "4"])
    captured = capsys.readouterr()

    assert code == 6
    assert "offset/length outside file range" in captured.err


def test_strings_ascii_respects_min_length(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "sample.bin"
    sample.write_text("abc", encoding="utf-8")

    code = main(["strings", str(sample), "--min-length", "4"])
    captured = capsys.readouterr()

    assert code == 0
    assert captured.out == ""


def test_strings_utf16_mode_outputs_decoded_text(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "sample.bin"
    sample.write_bytes("hello world".encode("utf-16"))

    code = main(["strings", str(sample), "--encoding", "utf16", "--min-length", "4"])
    captured = capsys.readouterr()

    assert code == 0
    assert "hello world" in captured.out.strip()


def test_strings_large_split_multibyte_input_stays_deterministic(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sample = tmp_path / "large.bin"
    payload = b"\x00\x00" + b"\xff\xfe" * 1500 + b"hello world\n" + b"\x00" * 1024
    sample.write_bytes(payload)

    code = main(["strings", str(sample), "--encoding", "utf-8", "--min-length", "5"])
    captured = capsys.readouterr()

    assert code == 0
    assert "hello world" in captured.out


def test_strings_invalid_encoding_is_rejected_by_cli_parser(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sample = tmp_path / "sample.bin"
    sample.write_text("abc", encoding="utf-8")

    code = main(["strings", str(sample), "--encoding", "rot13"])
    captured = capsys.readouterr()

    assert code == 2
    assert "argument --encoding: invalid choice: 'rot13'" in captured.err


def test_sanitize_name_replaces_unsafe_characters() -> None:
    assert sanitize_name("a/b\\c:d*e?f|g<h>i.txt") == "a_b_c_d_e_f_g_h_i.txt"


def test_sanitize_name_returns_default_for_empty_value() -> None:
    assert sanitize_name("") == "item"


def test_build_parser_accepts_all_supported_commands(tmp_path: Path) -> None:
    from deopjufier.commands.parser import _build_parser

    parser = _build_parser()
    sample = tmp_path / "sample.opju"
    sample.write_text("sample", encoding="utf-8")

    parsed = parser.parse_args(["inspect", str(sample)])
    assert parsed.command == "inspect"
    assert parsed.file == sample

    parsed = parser.parse_args(["list", str(sample)])
    assert parsed.command == "list"
    assert parsed.file == sample

    parsed = parser.parse_args(["extract", str(sample), "-o", str(tmp_path / "out")])
    assert parsed.command == "extract"
    assert parsed.file == sample

    parsed = parser.parse_args(["strings", str(sample)])
    assert parsed.command == "strings"
    assert parsed.file == sample

    parsed = parser.parse_args(["images", str(sample)])
    assert parsed.command == "images"
    assert parsed.file == sample

    parsed = parser.parse_args(["get", str(sample), "item:v1:test"])
    assert parsed.command == "get"
    assert parsed.file == sample
    assert parsed.item_id == "item:v1:test"

    parsed = parser.parse_args(["table-scan", str(sample)])
    assert parsed.command == "table-scan"
    assert parsed.file == sample

    parsed = parser.parse_args(["dump-block", str(sample), "--offset", "0", "--length", "0"])
    assert parsed.command == "dump-block"
    assert parsed.file == sample

    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    parsed = parser.parse_args(["compare", str(left), str(right)])
    assert parsed.command == "compare"
    assert parsed.left == left
    assert parsed.right == right


def test_help_message_has_ascii_mascot_and_examples(capsys: pytest.CaptureFixture[str]) -> None:
    from deopjufier.commands.parser import _build_parser

    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--help"])

    out = capsys.readouterr().out
    assert "deopjufy" in out.lower()
    assert "inspect sample.opj" in out
    assert "dump-block" in out
    assert "  ____" in out


def test_support_wording_does_not_claim_full_opj_opju_support(
    capsys: pytest.CaptureFixture[str],
) -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    _assert_no_overclaim_support_language(readme, "README.md")
    assert re.search(r"native[- ]?only", readme, flags=re.IGNORECASE) is not None
    assert re.search(r"\bpartial\b", readme, flags=re.IGNORECASE) is not None

    compatibility = (REPO_ROOT / "docs" / "compatibility.md").read_text(encoding="utf-8")
    _assert_no_overclaim_support_language(
        compatibility,
        "docs/compatibility.md",
    )
    assert "complete worksheet, Excel, or graph-preview extraction" in compatibility

    done = (REPO_ROOT / "DONE.md").read_text(encoding="utf-8")
    _assert_no_overclaim_support_language(done, "DONE.md")

    code = main(["--help"])
    help_text = capsys.readouterr().out
    _assert_no_overclaim_support_language(help_text, "cli --help output")
    assert "native" in help_text.lower()
    assert "partial" in help_text.lower()
    assert code == 0


def test_cli_main_rejects_missing_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main([])
    captured = capsys.readouterr()
    assert code == 2
    assert "usage:" in captured.err.lower()


def test_cli_main_rejects_missing_file_argument(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["inspect"])
    captured = capsys.readouterr()
    assert code == 2
    assert "the following arguments are required: file" in captured.err
