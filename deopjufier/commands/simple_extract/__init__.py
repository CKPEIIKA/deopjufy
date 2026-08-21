from deopjufier.commands.simple_extract.human_artifacts import retain_human_artifacts
from deopjufier.commands.simple_shared import *
from deopjufier.commands.support import _support_scope
from deopjufier.opj import (
    OpjProjectNode,
    OpjWorksheetMetadata,
    parse_opj_project_nodes,
    parse_opj_window_metadata,
    parse_opj_worksheet_metadata,
)

_OPJU_SHARED_OBJECT_KINDS = frozenset(
    {
        "worksheet",
        "matrix",
        "excel",
        "note",
        "function",
    }
)


def _emit_skipped_table_scan(manifest: Manifest, *, error: str) -> None:
    if _manifest_has_skipped_table_scan(manifest):
        return

    manifest.add_item(
        ManifestItem(
            kind="table_scan",
            name="numeric_tables",
            status="skipped",
            confidence=0.4,
            discovery_type="heuristic_scan",
            heuristic=True,
            source_object_path="numeric_tables",
            error=error,
        )
    )


def cmd_extract(args):
    session = _build_session(args.file)

    if args.format == "xlsx":
        table_format = "csv"
        book_format = "xlsx"
    elif args.format == "json":
        table_format = "json"
        book_format = "json"
    else:
        table_format = args.format
        book_format = args.format

    detection = session.detection
    if detection.detected_type not in SUPPORTED_TYPES:
        raise UnsupportedFileError("input is not a recognized Origin file (expected .opj or .opju)")

    outdir = _default_output_dir(args.file, args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    manifest = make_manifest(
        args.file,
        detection,
        "native-parser",
        size_bytes=session.size_bytes,
        sha256=session.sha256,
    )
    human_profile = args.human or args.human_only or args.human_artifacts_only or not args.extended
    partial = False
    shared_data: bytes | None = None

    def _required_file_data() -> bytes:
        nonlocal shared_data
        if shared_data is None:
            shared_data = session.file_data()
        return shared_data

    def _warn(message: str, code: str) -> None:
        _add_parser_warning(
            manifest.warnings,
            manifest.parser_warnings,
            code,
            message,
        )

    if not args.extended and (args.raw_dir is not None or args.text_dir is not None):
        _warn(
            "Raw/text carving options are inactive in human profile; use --extended or --map.",
            "machine-profile-outputs-ignored",
        )

    shared_blocks: list[ImageBlock] | None = None

    def _get_image_blocks() -> list[ImageBlock]:
        nonlocal shared_blocks
        if shared_blocks is None:
            shared_blocks = session.image_blocks()
        return shared_blocks

    raw_output_dir = None if human_profile else args.raw_dir
    text_output_dir = None if human_profile else args.text_dir
    effective_parser_only = args.parser_only

    skip_default_raw_text_outputs = (
        args.extended
        and not human_profile
        and detection.detected_type == "opju"
        and not effective_parser_only
        and args.no_images
        and args.no_strings
        and args.no_tables
        and session.size_bytes > _EXTRACT_LARGE_FILE_HEURISTIC_LIMIT_BYTES
    )

    if args.extended and not human_profile and not skip_default_raw_text_outputs:
        if raw_output_dir is None:
            raw_output_dir = outdir / "raw"
        if text_output_dir is None:
            text_output_dir = outdir / "text"
    owned_image_blocks: list[ImageBlock] = []
    shared_objects: list[OriginObject] | None = None
    opju_recovery_max_tables = 200
    opju_recovery_include_family_binary = True
    should_collect_objects = (not args.no_objects) or (raw_output_dir is not None) or (text_output_dir is not None)
    if should_collect_objects:
        use_parser_only_objects = effective_parser_only or (
            detection.detected_type == "opj" and session.size_bytes > _EXTRACT_LARGE_FILE_HEURISTIC_LIMIT_BYTES
        )
        collect_heuristics = not use_parser_only_objects
        if detection.detected_type == "opju":
            shared_objects = session.objects(
                collect_heuristics=collect_heuristics,
                allowed_kinds=_OPJU_SHARED_OBJECT_KINDS,
            )
        else:
            shared_objects = session.objects(
                collect_heuristics=collect_heuristics,
                heuristic_kind_limit=(
                    _EXTRACT_HEURISTIC_OBJECT_LIMIT_PER_KIND
                    if session.size_bytes > _EXTRACT_LARGE_FILE_HEURISTIC_LIMIT_BYTES
                    else None
                ),
            )
        if detection.detected_type == "opj" and session.size_bytes > _EXTRACT_LARGE_FILE_HEURISTIC_LIMIT_BYTES:
            parser_objects = [obj for obj in shared_objects if obj.parser_confirmed]
            if parser_objects:
                parser_kinds = {obj.object_kind for obj in parser_objects}
                fallback_objects = [
                    obj for obj in shared_objects if not obj.parser_confirmed and obj.object_kind not in parser_kinds
                ]
                shared_objects = parser_objects + _limit_extract_objects(
                    fallback_objects,
                    per_kind_limit=_EXTRACT_HEURISTIC_OBJECT_LIMIT_PER_KIND,
                )
            else:
                shared_objects = _limit_extract_objects(
                    shared_objects,
                    per_kind_limit=_EXTRACT_HEURISTIC_OBJECT_LIMIT_PER_KIND,
                )
    matrix_shared_objects: list[OriginObject] | None = None
    if shared_objects is not None and detection.detected_type == "opj":
        matrix_shared_objects = session.objects(
            max_repeats_per_name=None,
            collect_heuristics=collect_heuristics,
            heuristic_kind_limit=(
                _EXTRACT_HEURISTIC_OBJECT_LIMIT_PER_KIND
                if session.size_bytes > _EXTRACT_LARGE_FILE_HEURISTIC_LIMIT_BYTES
                else None
            ),
            allowed_kinds=frozenset({"matrix"}),
        )
    else:
        matrix_shared_objects = shared_objects
    skip_inline_tables = (
        detection.detected_type == "opj"
        and session.size_bytes > _EXTRACT_LARGE_FILE_HEURISTIC_LIMIT_BYTES
        and args.no_images
        and args.no_strings
    )
    skip_large_opju_table_scan = (
        detection.detected_type == "opju"
        and args.extended
        and session.size_bytes > _EXTRACT_LARGE_FILE_HEURISTIC_LIMIT_BYTES
        and args.no_images
        and args.no_strings
    )
    disable_opju_table_scan_for_human_profile = (
        detection.detected_type == "opju"
        and args.no_images
        and args.no_strings
        and human_profile
        and not args.extended
        and session.size_bytes > _EXTRACT_LARGE_FILE_HEURISTIC_LIMIT_BYTES
    )
    effective_no_tables = (
        args.no_tables or human_profile or skip_large_opju_table_scan or disable_opju_table_scan_for_human_profile
    )
    shared_rows = (
        None
        if skip_inline_tables or effective_no_tables
        else session.table_rows(
            min_rows=args.table_min_rows,
            min_columns=args.table_min_columns,
        )
    )
    step_enabled = any(
        [
            not args.no_images,
            not args.no_strings and not human_profile,
            not args.no_tables and not human_profile,
            not args.no_objects,
            raw_output_dir is not None,
            text_output_dir is not None,
        ]
    )

    raw_gap_payload: tuple[list[tuple[int, int]], list[RawRegionClassification]] | None = None
    text_gap_payload: tuple[list[tuple[int, int]], list[RawRegionClassification]] | None = None
    if raw_output_dir is not None:
        raw_gap_payload = _scan_gaps_once(
            session=session,
            mode="raw",
            min_size=args.raw_min_bytes,
            image_blocks=_get_image_blocks(),
            objects=shared_objects,
            min_rows=2,
            min_columns=2,
            text_min_length=4,
            classify_numeric=not args.no_tables,
        )
    if text_output_dir is not None:
        if args.text_min_bytes == args.raw_min_bytes and raw_gap_payload is not None:
            text_gap_payload = raw_gap_payload
        else:
            text_gap_payload = _scan_gaps_once(
                session=session,
                mode="text",
                min_size=args.text_min_bytes,
                image_blocks=_get_image_blocks(),
                objects=shared_objects,
                min_rows=2,
                min_columns=2,
                text_min_length=args.text_min_length,
                classify_numeric=not args.no_tables,
            )

    worksheet_objects: list[OriginObject] | None = None
    worksheet_allow_parser_recovery = False
    matrix_objects: list[OriginObject] | None = None
    matrix_allow_parser_recovery = False
    excel_objects: list[OriginObject] | None = None
    excel_allow_parser_recovery = False
    function_objects: list[OriginObject] | None = None
    function_allow_parser_recovery = False

    if not args.no_objects:
        file_data = _required_file_data()
        worksheet_objects, worksheet_allow_parser_recovery = session.objects_for_tabular_extraction(
            file_data,
            object_kind="worksheet",
            supplied_objects=shared_objects,
            prefer_supplied_objects=False,
            trust_supplied_objects_on_large=True,
            rewrite_worksheet_source_path=True,
            filter_non_parser_worksheet_duplicates=True,
        )
        matrix_objects, matrix_allow_parser_recovery = session.objects_for_tabular_extraction(
            file_data,
            object_kind="matrix",
            supplied_objects=matrix_shared_objects,
            prefer_supplied_objects=False,
            trust_supplied_objects_on_large=True,
        )
        excel_objects, excel_allow_parser_recovery = session.objects_for_tabular_extraction(
            file_data,
            object_kind="excel",
            supplied_objects=shared_objects,
            prefer_supplied_objects=False,
            trust_supplied_objects_on_large=True,
        )
        if shared_objects is not None:
            function_objects = [obj for obj in shared_objects if obj.object_kind == "function"]

        if function_objects is not None:
            function_allow_parser_recovery = any(
                obj.object_kind == "function" and obj.parser_confirmed for obj in function_objects
            )

    precomputed_worksheet_metadata: dict[str, OpjWorksheetMetadata] | None = None
    precomputed_project_nodes: list[OpjProjectNode] | None = None
    if detection.detected_type == "opj" and not args.no_objects:
        opj_data = _required_file_data()
        try:
            semantic_elements = walk_opj_file(opj_data, tolerant=False)
        except OpjStreamError:
            try:
                semantic_elements = walk_opj_file(opj_data, tolerant=True)
            except OpjStreamError:
                semantic_elements = []
        window_metadata = parse_opj_window_metadata(opj_data, elements=semantic_elements)
        precomputed_project_nodes = parse_opj_project_nodes(opj_data, elements=semantic_elements)
        worksheet_metadata_names = {
            obj.name
            for obj in [*(worksheet_objects or []), *(excel_objects or [])]
            if obj.object_kind in {"worksheet", "excel"}
        }
        if worksheet_metadata_names:
            precomputed_worksheet_metadata = parse_opj_worksheet_metadata(
                opj_data,
                worksheet_names=worksheet_metadata_names,
                parsed_window_metadata=window_metadata,
            )

    if not args.no_strings and not human_profile:
        _log("extracting visible strings", enabled=args.verbose, quiet=args.quiet)
        strings_count = extract_strings(
            args.file,
            outdir / "strings",
            manifest,
            encoding="ascii",
            min_length=args.strings_min_length,
            force=args.force,
            manifest_root=outdir,
        )
        if strings_count == 0:
            partial = True
            _warn("No visible strings matched extract criteria.", "no-visible-strings")
    if args.no_tables:
        _emit_skipped_table_scan(
            manifest,
            error="table_scan_disabled_by_option",
        )
    elif skip_large_opju_table_scan:
        _emit_skipped_table_scan(
            manifest,
            error="table_scan_disabled_by_scan_profile",
        )
    elif shared_rows is not None:
        _log("extracting numeric tables", enabled=args.verbose, quiet=args.quiet)
        table_count = extract_tables(
            args.file,
            outdir / "tables",
            manifest,
            output_format=table_format,
            min_rows=args.table_min_rows,
            min_columns=args.table_min_columns,
            force=args.force,
            table_rows=shared_rows,
            manifest_root=outdir,
        )
        if table_count == 0 and shared_rows:
            if not _manifest_has_skipped_table_scan(manifest):
                _warn("No numeric tables matched scan criteria.", "no-numeric-tables")
        elif table_count == 0 and not effective_no_tables and (args.table_min_rows != 1 or args.table_min_columns != 2):
            # Explicit table-scan parameterization implies the caller expects a result.
            _warn("No numeric tables matched scan criteria.", "no-numeric-tables")
    else:
        _emit_skipped_table_scan(
            manifest,
            error="table_scan_disabled_by_scan_profile",
        )
    if not args.no_objects:
        _log("exporting functions", enabled=args.verbose, quiet=args.quiet)
        has_shared_worksheet_objects = False
        if shared_objects is not None:
            has_shared_worksheet_objects = any(obj.object_kind == "worksheet" for obj in shared_objects)

        book_count = extract_books(
            args.file,
            outdir,
            manifest,
            output_format=book_format,
            force=args.force,
            table_min_rows=args.table_min_rows,
            table_min_columns=args.table_min_columns,
            allow_heuristic_scan=not effective_no_tables,
            file_data=_required_file_data(),
            objects=worksheet_objects,
            allow_parser_recovery=worksheet_allow_parser_recovery,
            recovery_max_tables=opju_recovery_max_tables,
            recovery_include_family_binary=opju_recovery_include_family_binary,
            precomputed_opj_metadata=precomputed_worksheet_metadata,
            precomputed_opju_descriptors=(
                session.opju_column_descriptors() if detection.detected_type == "opju" else None
            ),
            manifest_root=outdir,
            include_descriptor_tables=not args.no_tables,
        )
        has_worksheet_data_artifact = any(
            item.kind == "worksheet"
            and item.status in {"extracted", "partial"}
            and not item.name.endswith("_collection")
            for item in manifest.items
        )
        if (
            book_count == 0
            and should_warn_for_missing_artifact(manifest, "worksheet")
            and (detection.detected_type != "opj" or has_shared_worksheet_objects)
            and not (detection.detected_type == "opju" and has_worksheet_data_artifact)
        ):
            _warn("No worksheet data emitted to book exports.", "no-worksheet-data")

        matrix_count = extract_matrices(
            args.file,
            outdir,
            manifest,
            output_format=book_format,
            force=args.force,
            table_min_rows=args.table_min_rows,
            table_min_columns=args.table_min_columns,
            allow_heuristic_scan=not effective_no_tables,
            file_data=_required_file_data(),
            objects=matrix_objects,
            allow_parser_recovery=matrix_allow_parser_recovery,
            recovery_max_tables=opju_recovery_max_tables,
            recovery_include_family_binary=opju_recovery_include_family_binary,
            emit_unsupported_collection=not human_profile and not use_parser_only_objects,
            manifest_root=outdir,
        )
        has_parser_backed_matrix_objects = any(
            obj.object_kind == "matrix" and obj.parser_confirmed for obj in (matrix_objects or [])
        )
        if matrix_count == 0 and should_warn_for_missing_artifact(
            manifest,
            "matrix",
            detected_type=detection.detected_type,
            has_parser_backed_artifacts=has_parser_backed_matrix_objects,
        ):
            _warn("No matrix data emitted to matrix exports.", "no-matrix-data")

        excel_count = extract_excel(
            args.file,
            outdir,
            manifest,
            output_format=book_format,
            force=args.force,
            table_min_rows=args.table_min_rows,
            table_min_columns=args.table_min_columns,
            allow_heuristic_scan=not effective_no_tables,
            file_data=_required_file_data(),
            objects=excel_objects,
            allow_parser_recovery=excel_allow_parser_recovery,
            emit_unsupported_collection=not human_profile
            and not use_parser_only_objects
            and not any(obj.object_kind == "excel" and obj.parser_confirmed for obj in (excel_objects or [])),
            precomputed_opj_metadata=precomputed_worksheet_metadata,
            manifest_root=outdir,
        )
        has_parser_backed_excel_objects = any(
            obj.object_kind == "excel" and obj.parser_confirmed for obj in (excel_objects or [])
        )
        if excel_count == 0 and should_warn_for_missing_artifact(
            manifest,
            "excel",
            detected_type=detection.detected_type,
            has_parser_backed_artifacts=has_parser_backed_excel_objects,
        ):
            _warn(
                "No excel data emitted to excel exports.",
                "no-excel-data",
            )

        partial = (
            _export_notes_and_functions(
                args=args,
                manifest=manifest,
                outdir=outdir,
                shared_objects=shared_objects,
                function_objects=function_objects,
                function_allow_parser_recovery=function_allow_parser_recovery,
                function_has_parser_backed_artifacts=function_allow_parser_recovery,
                file_data=_required_file_data(),
                detection=detection,
                use_parser_only_objects=use_parser_only_objects,
                warn=_warn,
                walk_elements=session.opju_walk() if detection.detected_type == "opju" else None,
            )
            or partial
        )

        invalid_spreadsheet_regions = [
            item
            for item in manifest.items
            if item.kind == "origin_storage_region" and item.error == "advertised_spreadsheet_signature_mismatch"
        ]
        if invalid_spreadsheet_regions:
            _warn(
                f"Preserved {len(invalid_spreadsheet_regions)} advertised spreadsheet payloads as raw "
                "OriginStorage regions because their container signatures did not match their filenames.",
                "spreadsheet-signature-mismatch",
            )
            partial = True

        partial = (
            _export_graph_previews(
                args=args,
                detection=detection,
                session=session,
                manifest=manifest,
                outdir=outdir,
                shared_blocks=shared_blocks,
                owned_image_blocks=owned_image_blocks,
                shared_objects=shared_objects,
                use_parser_only_objects=use_parser_only_objects,
                required_file_data=_required_file_data,
                get_image_blocks=_get_image_blocks,
                warn=_warn,
            )
            or partial
        )

        if detection.detected_type == "opju":
            extract_origin_storage_analysis_summary(
                args.file,
                outdir,
                manifest,
                force=args.force,
                file_data=_required_file_data(),
                manifest_root=outdir,
            )

        if not human_profile:
            _log("exporting project tree", enabled=args.verbose, quiet=args.quiet)
            extract_project_tree(
                args.file,
                outdir,
                manifest,
                force=args.force,
                manifest_root=outdir,
                file_data=_required_file_data(),
                project_nodes=precomputed_project_nodes,
            )

    if not args.no_objects and not human_profile:
        if detection.detected_type == "opju":
            _log("exporting decoded OPJU regions", enabled=args.verbose, quiet=args.quiet)
            extract_opju_decoded_regions(
                args.file,
                outdir,
                manifest,
                force=args.force,
                file_data=_required_file_data(),
                manifest_root=outdir,
                include_strings=not args.no_strings,
                strings_min_length=args.strings_min_length,
                include_numeric_runs=not args.no_tables,
                regions=session.opju_decoded_regions(),
            )

        object_count = extract_origin_inventory(
            args.file,
            outdir / "metadata",
            manifest,
            force=args.force,
            objects=shared_objects,
            manifest_root=outdir,
        )
        if object_count == 0:
            partial = True

        extract_origin_storage_reports(
            args.file,
            outdir,
            manifest,
            force=args.force,
            file_data=_required_file_data(),
            emit_per_record_items=not args.no_tables,
            emit_no_records_item=args.parser_only,
            manifest_root=outdir,
        )

    if raw_output_dir is not None:
        if args.raw_min_bytes < 1:
            raise ValueError("raw-min-bytes must be positive")
        if raw_gap_payload is None:
            raw_ranges, raw_classes = _scan_gaps_once(
                session=session,
                mode="raw",
                min_size=args.raw_min_bytes,
                image_blocks=_get_image_blocks(),
                objects=shared_objects,
                min_rows=2,
                min_columns=2,
                text_min_length=4,
                classify_numeric=not args.no_tables,
            )
        else:
            raw_ranges, raw_classes = raw_gap_payload
        raw_count = extract_raw_blocks(
            args.file,
            raw_output_dir,
            manifest,
            force=args.force,
            min_size=args.raw_min_bytes,
            image_blocks=_get_image_blocks(),
            objects=shared_objects,
            file_data=_required_file_data(),
            gap_ranges=raw_ranges,
            gap_classifications=raw_classes,
            manifest_root=raw_output_dir,
            excluded_region_classes={RAW_REGION_CLASS_TEXT}
            if text_output_dir is not None and args.text_min_bytes == args.raw_min_bytes
            else None,
        )
        if raw_count == 0:
            _warn("No raw blocks met export criteria.", "no-raw-blocks")

    if text_output_dir is not None:
        if args.text_min_bytes < 1:
            raise ValueError("text-min-bytes must be positive")
        if args.text_min_length < 1:
            raise ValueError("text-min-length must be positive")
        if text_gap_payload is None:
            text_ranges, text_classes = _scan_gaps_once(
                session=session,
                mode="text",
                min_size=args.text_min_bytes,
                image_blocks=_get_image_blocks(),
                objects=shared_objects,
                min_rows=2,
                min_columns=2,
                text_min_length=args.text_min_length,
                classify_numeric=not args.no_tables,
            )
        else:
            text_ranges, text_classes = text_gap_payload
        text_count = extract_text_regions(
            args.file,
            text_output_dir,
            manifest,
            force=args.force,
            min_size=args.text_min_bytes,
            min_length=args.text_min_length,
            image_blocks=_get_image_blocks(),
            objects=shared_objects,
            file_data=_required_file_data(),
            gap_ranges=text_ranges,
            gap_classifications=text_classes,
            manifest_root=text_output_dir,
        )
        if text_count == 0:
            _warn("No text regions met export criteria.", "no-text-regions")

    if not args.no_images:
        _log("extracting embedded images", enabled=args.verbose, quiet=args.quiet)
        _ensure_file(args.file)
        image_blocks = _filter_unowned_image_blocks(_get_image_blocks(), owned_image_blocks)
        image_objects = shared_objects
        if detection.detected_type == "opju" and image_objects is not None:
            image_objects = [obj for obj in image_objects if obj.parser_confirmed]
        extracted = extract_images(
            args.file,
            outdir / "images",
            manifest,
            force=args.force,
            image_blocks=image_blocks,
            objects=image_objects if detection.detected_type in {"opj", "opju"} else None,
            manifest_root=outdir,
        )
        if not extracted and has_malformed_graph_preview(manifest):
            partial = True

    if detection.detected_type == "opju" and raw_output_dir is not None and text_output_dir is not None:
        _ensure_carved_raw_gap_evidence(manifest)

    opju_walk_elements = (
        session.opju_walk()
        if detection.detected_type == "opju" and (args.map or args.extended or not args.no_objects)
        else None
    )
    opju_descriptors = (
        session.opju_column_descriptors()
        if detection.detected_type == "opju" and (args.extended or not args.no_objects)
        else None
    )
    if detection.detected_type == "opju" and args.extended:
        extract_opju_tagged_envelopes(
            args.file,
            outdir,
            manifest,
            force=args.force,
            file_data=_required_file_data(),
            manifest_root=outdir,
            walk_elements=opju_walk_elements,
            descriptors=opju_descriptors,
        )

    if args.map:
        extract_byte_map(
            args.file,
            outdir,
            manifest,
            force=args.force,
            file_data=_required_file_data(),
            manifest_root=outdir,
            walk_elements=opju_walk_elements,
        )

    if detection.detected_type == "opju" and not args.no_objects:
        extract_opju_semantic_provenance(
            args.file,
            outdir,
            manifest,
            force=args.force,
            file_data=_required_file_data(),
            manifest_root=outdir,
            descriptors=opju_descriptors,
            decoded_regions=session.opju_decoded_regions(),
            walk_elements=opju_walk_elements,
            output_format=book_format,
        )

    if not step_enabled:
        _warn("No extraction step was enabled.", "no-extraction-steps")
        partial = True

    if human_profile:
        retain_human_artifacts(manifest, outdir)

    manifest.parser_status = _compute_parser_status(
        step_enabled=step_enabled,
        manifest_items=manifest.items,
    )

    manifest_outcome = _classify_extract_outcome(
        step_enabled=step_enabled,
        hard_failure=partial,
    )
    manifest_status_map = {
        "unsupported but honest": "unsupported",
        "partial failure": "partial",
        "ok but absent": "ok",
    }
    manifest.status = manifest_status_map[manifest_outcome]
    manifest.coverage_scope, manifest.verification = _support_scope(
        detection.detected_type,
        manifest.parser_status,
        status=manifest.status,
        warnings=manifest.warnings,
        warning_codes=[warning["code"] for warning in manifest.parser_warnings],
        items=manifest.items,
    )
    manifest.support_class = _support_class(
        detection.detected_type,
        manifest.parser_status,
        status=manifest.status,
        warnings=manifest.warnings,
        warning_codes=[warning["code"] for warning in manifest.parser_warnings],
        items=manifest.items,
    )

    manifest_path = args.manifest or (outdir / "manifest.json")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest.write(manifest_path)

    if partial or (args.fail_on_partial and _manifest_has_partial_outputs(manifest)):
        if args.fail_on_partial:
            return EXIT_PARTIAL
        return EXIT_SUCCESS

    return EXIT_SUCCESS
