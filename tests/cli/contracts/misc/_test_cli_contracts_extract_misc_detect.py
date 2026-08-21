from deopjufier.commands.parser import _build_parser
from tests.cli.contracts.misc._test_cli_contracts_extract_misc_common import *  # noqa: F403


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


def test_extract_parser_only_is_accepted() -> None:
    parser = _build_parser()
    args = parser.parse_args(["extract", "sample.opju", "--parser-only"])

    assert args.command == "extract"
    assert args.parser_only
    assert not args.extended
    assert args.human


def test_extract_parser_only_stays_human_profile_by_default(tmp_path: Path) -> None:
    sample = REPO_ROOT / "tests" / "fixtures" / "synthetic" / "synthetic-cpyua.opju"
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    output = tmp_path / "parser-only"
    manifest_path = output / "manifest.json"
    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(output),
            "--parser-only",
            "--no-images",
            "--no-strings",
        ]
    )

    assert code in {0, 4}
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert not (output / "raw").exists()
    assert not (output / "text").exists()
    assert not any(item.get("kind") == "raw_dump" for item in payload.get("items", ()))
    assert not any(item.get("kind") == "text_region" for item in payload.get("items", ()))


def test_extract_parser_only_can_be_combined_with_extended_profile() -> None:
    parser = _build_parser()
    args = parser.parse_args(["extract", "sample.opju", "--parser-only", "--extended"])

    assert args.command == "extract"
    assert args.parser_only
    assert args.extended
    assert not args.human
    assert not args.human_only
    assert not args.human_artifacts_only


def test_extract_parser_only_can_be_combined_with_map_profile() -> None:
    parser = _build_parser()
    args = parser.parse_args(["extract", "sample.opju", "--parser-only", "--map"])

    assert args.command == "extract"
    assert args.parser_only
    assert args.extended
    assert not args.human
    assert not args.human_only
    assert not args.human_artifacts_only


def test_extract_parser_only_extended_enables_machine_output(tmp_path: Path) -> None:
    sample = REPO_ROOT / "tests" / "fixtures" / "synthetic" / "synthetic-cpyua.opju"
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    output = tmp_path / "parser-only-extended"
    manifest_path = output / "manifest.json"
    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(output),
            "--parser-only",
            "--extended",
            "--no-tables",
            "--no-strings",
        ]
    )

    assert code in {0, 4}
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert (output / "raw").exists()
    assert (output / "text").exists()
    assert any(
        item.get("kind") in {"raw_dump", "text_region", "origin_object_inventory"} for item in payload.get("items", ())
    )


@pytest.mark.parametrize("machine_profile", ["--extended", "--map"])
def test_extract_parser_only_map_like_extended_enables_machine_output(
    tmp_path: Path,
    machine_profile: str,
) -> None:
    sample = REPO_ROOT / "tests" / "fixtures" / "synthetic" / "synthetic-cpyua.opju"
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    output = tmp_path / "parser-only-machine"
    manifest_path = output / "manifest.json"
    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(output),
            "--parser-only",
            machine_profile,
            "--no-tables",
            "--no-strings",
        ]
    )

    assert code in {0, 4}
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert (output / "raw").exists()
    assert (output / "text").exists()
    assert any(
        item.get("kind") in {"raw_dump", "text_region", "origin_object_inventory"} for item in payload.get("items", ())
    )


@pytest.mark.parametrize(
    "fixture",
    [
        Path("refs/public/zenodo/zenodo-3779638-fig2.opju"),
        Path("refs/public/zenodo/zenodo-3779638-fig3.opju"),
        Path("refs/public/zenodo/zenodo-3779638-fig4.opj"),
    ],
)
def test_extract_real_parser_only_default_keeps_human_region_profile(
    tmp_path: Path,
    fixture: Path,
) -> None:
    sample = REPO_ROOT / fixture
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    output = tmp_path / "real-parser-only" / sample.name
    manifest_path = output / "manifest.json"
    raw_dir = output / "explicit_raw"
    text_dir = output / "explicit_text"

    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(output),
            "--parser-only",
            "--raw-dir",
            str(raw_dir),
            "--text-dir",
            str(text_dir),
            "--no-tables",
            "--no-strings",
            "--no-images",
        ]
    )

    assert code in {0, 4}
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert not raw_dir.exists()
    assert not text_dir.exists()
    assert "Raw/text carving options are inactive in human profile" in " ".join(payload.get("warnings", ()))
    assert not any(
        item.get("kind") in {"raw_dump", "text_region", "origin_object_inventory"} for item in payload.get("items", ())
    )


@pytest.mark.parametrize("machine_profile", ["--map", "--extended"])
@pytest.mark.parametrize(
    "fixture",
    [
        Path("refs/public/zenodo/zenodo-3779638-fig2.opju"),
        Path("refs/public/zenodo/zenodo-3779638-fig3.opju"),
        Path("refs/public/zenodo/zenodo-10721640-figure-1b.opju"),
        Path("refs/public/zenodo/zenodo-3779638-fig4.opj"),
    ],
)
def test_extract_real_parser_only_machine_profile_emits_machine_outputs(
    tmp_path: Path,
    fixture: Path,
    machine_profile: str,
) -> None:
    sample = REPO_ROOT / fixture
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    output = tmp_path / "real-parser-only-map" / fixture.name
    manifest_path = output / "manifest.json"
    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(output),
            "--parser-only",
            machine_profile,
            "--no-tables",
            "--no-strings",
        ]
    )

    assert code in {0, 4}
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert (output / "raw").exists()
    assert (output / "text").exists()
    assert any(
        item.get("kind") in {"raw_dump", "text_region", "origin_object_inventory"} for item in payload.get("items", ())
    )


@pytest.mark.parametrize("machine_profile", ["--map", "--extended"])
@pytest.mark.parametrize(
    "fixture",
    [
        Path("refs/public/zenodo/zenodo-3779638-fig2.opju"),
        Path("refs/public/zenodo/zenodo-3779638-fig4.opj"),
        Path("refs/public/zenodo/zenodo-10721640-figure-1b.opju"),
    ],
)
def test_extract_real_parser_only_machine_profile_obeys_explicit_raw_text_dirs(
    tmp_path: Path,
    fixture: Path,
    machine_profile: str,
) -> None:
    sample = REPO_ROOT / fixture
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    output = tmp_path / "real-parser-only-map-explicit" / fixture.name
    manifest_path = output / "manifest.json"
    raw_dir = output / "explicit_machine_raw"
    text_dir = output / "explicit_machine_text"

    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(output),
            "--parser-only",
            machine_profile,
            "--raw-dir",
            str(raw_dir),
            "--text-dir",
            str(text_dir),
            "--no-tables",
            "--no-strings",
        ]
    )

    assert code in {0, 4}
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert raw_dir.exists()
    assert text_dir.exists()
    assert "Raw/text carving options are inactive in human profile" not in " ".join(payload.get("warnings", ()))
    assert any(
        item.get("kind") in {"raw_dump", "text_region", "origin_object_inventory"} for item in payload.get("items", ())
    )


def test_extract_human_option_is_accepted() -> None:
    parser = _build_parser()
    args = parser.parse_args(["extract", "sample.opju", "--human"])

    assert args.command == "extract"
    assert args.human


def test_extract_default_profile_is_human_flagged() -> None:
    parser = _build_parser()
    args = parser.parse_args(["extract", "sample.opju"])

    assert args.command == "extract"
    assert args.human
    assert not args.extended
    assert not args.human_only
    assert not args.human_artifacts_only


@pytest.mark.parametrize("extended_arg", ["--extended", "--map"])
def test_extract_extended_option_is_accepted(extended_arg: str) -> None:
    parser = _build_parser()
    args = parser.parse_args(["extract", "sample.opju", extended_arg])

    assert args.command == "extract"
    assert args.extended
    assert not args.human
    assert not args.human_only
    assert not args.human_artifacts_only


def test_extract_default_profile_stays_human_only(tmp_path: Path) -> None:
    sample = REPO_ROOT / "tests" / "fixtures" / "synthetic" / "synthetic-cpyua.opju"
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    output = tmp_path / "default"
    manifest_path = output / "manifest.json"
    code = main(["extract", str(sample), "-o", str(output)])
    assert code in {0, 4}
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert not (output / "raw").exists()
    assert not (output / "text").exists()
    assert not any(
        item.get("kind")
        in {
            "origin_object_inventory",
            "origin_storage_report",
            "origin_storage_report_json",
            "origin_storage_report_summary",
            "raw_dump",
            "text_region",
        }
        for item in payload.get("items", ())
    )


@pytest.mark.parametrize(
    "fixture",
    [
        Path("refs/public/zenodo/zenodo-10721640-figure-1b.opju"),
        Path("refs/public/zenodo/zenodo-3779638-fig2.opju"),
    ],
)
def test_extract_default_profile_stays_human_only_on_public_fixture(
    tmp_path: Path,
    fixture: Path,
) -> None:
    sample = REPO_ROOT / fixture
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    output = tmp_path / "real-default" / sample.name
    manifest_path = output / "manifest.json"
    code = main(["extract", str(sample), "-o", str(output)])
    assert code in {0, 4}
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert not (output / "raw").exists()
    assert not (output / "text").exists()
    assert not any(
        item.get("kind")
        in {
            "origin_object_inventory",
            "origin_storage_report",
            "origin_storage_report_json",
            "origin_storage_report_summary",
            "raw_dump",
            "text_region",
        }
        for item in payload.get("items", ())
    )


@pytest.mark.parametrize(
    "fixture",
    [
        Path("refs/public/zenodo/zenodo-3779638-fig4.opj"),
    ],
)
def test_extract_default_profile_stays_human_only_on_public_opj_fixture(
    tmp_path: Path,
    fixture: Path,
) -> None:
    sample = REPO_ROOT / fixture
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    output = tmp_path / "real-default-opj" / sample.name
    manifest_path = output / "manifest.json"
    code = main(["extract", str(sample), "-o", str(output)])
    assert code in {0, 4}
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert not (output / "raw").exists()
    assert not (output / "text").exists()
    assert not any(
        item.get("kind")
        in {
            "origin_object_inventory",
            "origin_storage_report",
            "origin_storage_report_json",
            "origin_storage_report_summary",
            "raw_dump",
            "text_region",
        }
        for item in payload.get("items", ())
    )


@pytest.mark.parametrize(
    "fixture",
    [
        Path("refs/public/zenodo/zenodo-10721640-figure-1b.opju"),
    ],
)
def test_extract_real_default_with_raw_text_dirs_ignored(
    tmp_path: Path,
    fixture: Path,
) -> None:
    sample = REPO_ROOT / fixture
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    output = tmp_path / "real-default-ignored" / sample.name
    manifest_path = output / "manifest.json"
    raw_dir = output / "explicit_raw"
    text_dir = output / "explicit_text"
    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(output),
            "--raw-dir",
            str(raw_dir),
            "--text-dir",
            str(text_dir),
        ]
    )
    assert code in {0, 4}
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert not raw_dir.exists()
    assert not text_dir.exists()
    assert "Raw/text carving options are inactive in human profile" in " ".join(payload.get("warnings", ()))
    assert not any(
        item.get("kind")
        in {
            "origin_object_inventory",
            "origin_storage_report",
            "origin_storage_report_json",
            "origin_storage_report_summary",
            "raw_dump",
            "text_region",
        }
        for item in payload.get("items", ())
    )


@pytest.mark.parametrize("human_profile", ["--human", "--human-only", "--human-artifacts-only"])
def test_extract_human_profiles_ignore_raw_text_dirs(
    tmp_path: Path,
    human_profile: str,
) -> None:
    sample = REPO_ROOT / "tests" / "fixtures" / "synthetic" / "synthetic-cpyua.opju"
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    output = tmp_path / "real-humans" / human_profile.lstrip("-")
    manifest_path = output / "manifest.json"
    raw_dir = output / "explicit_raw"
    text_dir = output / "explicit_text"
    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(output),
            human_profile,
            "--raw-dir",
            str(raw_dir),
            "--text-dir",
            str(text_dir),
            "--no-tables",
            "--no-strings",
            "--no-images",
        ]
    )
    assert code in {0, 4}
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert not raw_dir.exists()
    assert not text_dir.exists()
    assert "Raw/text carving options are inactive in human profile" in " ".join(payload.get("warnings", ()))
    assert not any(
        item.get("kind") in {"raw_dump", "text_region", "origin_object_inventory"} for item in payload.get("items", ())
    )


@pytest.mark.parametrize("extended_arg", ["--extended", "--map"])
def test_extract_extended_profile_enables_machine_output(
    tmp_path: Path,
    extended_arg: str,
) -> None:
    sample = REPO_ROOT / "tests" / "fixtures" / "synthetic" / "synthetic-cpyua.opju"
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    output = tmp_path / "extended"
    manifest_path = output / "manifest.json"
    code = main(["extract", str(sample), "-o", str(output), extended_arg])
    assert code in {0, 4}
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert (output / "raw").exists()
    assert (output / "text").exists()
    assert any(
        item.get("kind") in {"table_scan", "raw", "text", "metadata", "origin_storage_report"}
        for item in payload.get("items", ())
    )


@pytest.mark.parametrize(
    "fixture,extended_arg",
    [
        (Path("refs/public/zenodo/zenodo-3779638-fig4.opj"), "--extended"),
        (Path("refs/public/zenodo/zenodo-3779638-fig4.opj"), "--map"),
        (Path("refs/public/zenodo/zenodo-10721640-figure-1b.opju"), "--extended"),
        (Path("refs/public/zenodo/zenodo-10721640-figure-1b.opju"), "--map"),
    ],
)
def test_extract_real_fixture_extended_profile_adds_machine_artifacts(
    tmp_path: Path,
    fixture: Path,
    extended_arg: str,
) -> None:
    sample = REPO_ROOT / fixture
    if not sample.exists():
        pytest.skip(f"Fixture missing: {sample}")

    output = tmp_path / "real-extended" / sample.name / extended_arg.lstrip("-")
    manifest_path = output / "manifest.json"
    code = main(["extract", str(sample), "-o", str(output), extended_arg])
    assert code in {0, 4}
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert (output / "raw").exists()
    assert (output / "text").exists()
    assert any(
        item.get("kind")
        in {
            "origin_object_inventory",
            "origin_storage_report",
            "origin_storage_report_json",
            "origin_storage_report_summary",
            "metadata",
            "raw_dump",
            "text_region",
        }
        for item in payload.get("items", ())
    )


def test_extract_human_and_extended_are_mutually_exclusive() -> None:
    parser = _build_parser()

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["extract", "sample.opju", "--human", "--extended"])

    assert exc_info.value.code == 2

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["extract", "sample.opju", "--human", "--map"])

    assert exc_info.value.code == 2


def test_extract_human_only_and_extended_are_mutually_exclusive() -> None:
    parser = _build_parser()

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["extract", "sample.opju", "--human-only", "--extended"])

    assert exc_info.value.code == 2

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["extract", "sample.opju", "--human-only", "--map"])

    assert exc_info.value.code == 2


def test_extract_human_artifacts_only_and_extended_are_mutually_exclusive() -> None:
    parser = _build_parser()

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["extract", "sample.opju", "--human-artifacts-only", "--extended"])

    assert exc_info.value.code == 2

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["extract", "sample.opju", "--human-artifacts-only", "--map"])

    assert exc_info.value.code == 2


@pytest.mark.parametrize("human_profile", ["--human", "--human-only", "--human-artifacts-only"])
@pytest.mark.parametrize("machine_profile", ["--extended", "--map"])
def test_parser_only_human_and_machine_profiles_are_mutually_incompatible(
    human_profile: str,
    machine_profile: str,
) -> None:
    parser = _build_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["extract", "sample.opju", "--parser-only", machine_profile, human_profile])
    assert exc_info.value.code == 2


@pytest.mark.parametrize("human_profile", ["--human", "--human-only", "--human-artifacts-only"])
def test_parser_only_can_be_combined_with_human_profile(human_profile: str) -> None:
    parser = _build_parser()
    args = parser.parse_args(["extract", "sample.opju", "--parser-only", human_profile])

    assert args.command == "extract"
    assert args.parser_only
    assert args.human is (human_profile == "--human")
    assert not args.extended
    assert args.human_only is (human_profile == "--human-only")
    assert args.human_artifacts_only is (human_profile == "--human-artifacts-only")


def test_extract_without_file_data_inputs_does_not_load_full_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deopjufier import commands

    sample = tmp_path / "extract_stream.opju"
    sample.write_bytes(b"xx" + b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x00IEND\xae\x42\x60\x82")

    def _fail_file_data(_: object) -> bytes:
        raise AssertionError("cmd_extract should not preload full bytes for image-only run")

    monkeypatch.setattr(commands.ExtractionSession, "file_data", _fail_file_data)
    code = main(
        [
            "extract",
            str(sample),
            "--no-objects",
            "--no-strings",
            "--no-tables",
            "--force",
        ]
    )

    assert code == 0


def test_list_parser_error_reports_error_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sample = tmp_path / "parser-error.opj"
    sample.write_bytes(b"CPYA")

    def _raise(_self: ExtractionSession, *_args, **_kwargs) -> list[dict]:
        raise CorruptedInputError("bad object map")

    monkeypatch.setattr("deopjufier.app.ExtractionSession.list_items", _raise)

    code = main(["list", str(sample), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 6
    assert payload["status"] == "unsupported"
    assert payload["support_class"] == "failed"
    assert payload["parser_status"] == "error"
    assert payload["warnings"] == ["Native parser error: bad object map"]


def test_inspect_parser_error_reports_truncated_opj_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sample = tmp_path / "parser-error.opj"
    sample.write_bytes(b"CPYA")

    def _raise(*_args: object, **_kwargs: object) -> list[object]:
        raise CorruptedInputError("truncated OPJ boundary table")

    monkeypatch.setattr("deopjufier.inventory.parse_opj_boundaries", _raise)

    code = main(["inspect", str(sample), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 6
    assert payload["status"] == "unsupported"
    assert payload["support_class"] == "failed"
    assert payload["parser_status"] == "error"
    assert payload["warnings"] == ["Native parser error: truncated OPJ boundary table"]


def test_list_parser_error_reports_truncated_opju_region(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sample = tmp_path / "parser-error.opju"
    sample.write_bytes(b"CPYUA")

    def _raise(*_args: object, **_kwargs: object) -> list[object]:
        raise CorruptedInputError("truncated OriginStorage region")

    monkeypatch.setattr("deopjufier.inventory.parse_opju_records", _raise)

    code = main(["list", str(sample), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 6
    assert payload["status"] == "unsupported"
    assert payload["support_class"] == "failed"
    assert payload["parser_status"] == "error"
    assert payload["warnings"] == ["Native parser error: truncated OriginStorage region"]


def test_extract_parser_error_reports_corrupted_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sample = tmp_path / "parser-error.opj"
    sample.write_bytes(b"CPYA")
    output = tmp_path / "out"

    def _raise(_self: ExtractionSession, *_args: object, **_kwargs: object) -> list[object]:
        raise CorruptedInputError("bad object map")

    monkeypatch.setattr("deopjufier.commands.support.ExtractionSession.objects", _raise)

    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(output),
            "--no-strings",
            "--no-tables",
            "--no-images",
        ]
    )
    captured = capsys.readouterr()

    assert code == 6
    assert "bad object map" in captured.err
    assert not (output / "manifest.json").exists()
    assert not output.exists() or len(list(output.iterdir())) == 0


def test_extract_parser_error_reports_opju_originstorage_truncation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sample = tmp_path / "parser-error.opju"
    sample.write_bytes(b"CPYUA")
    output = tmp_path / "out"

    def _raise(*_args: object, **_kwargs: object) -> list[object]:
        raise CorruptedInputError("truncated OriginStorage region")

    monkeypatch.setattr("deopjufier.inventory.parse_opju_records", _raise)

    code = main(
        [
            "extract",
            str(sample),
            "-o",
            str(output),
            "--no-strings",
            "--no-tables",
            "--no-images",
        ]
    )
    captured = capsys.readouterr()

    assert code == 6
    assert "truncated OriginStorage region" in captured.err
    assert not output.exists() or len(list(output.iterdir())) == 0
