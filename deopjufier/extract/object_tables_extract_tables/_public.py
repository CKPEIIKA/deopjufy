from deopjufier.extract.object_tables_extract_filters import *  # noqa: F403
from deopjufier.extract.object_tables_extract_tables._core import _extract_tabular_objects
from deopjufier.extract.object_tables_match import *  # noqa: F403
from deopjufier.inventory import (
    MAGIC_OPJ,
    ParserBackedDiscoveryRecord,
    discover_origin_objects,
)
from deopjufier.opj import recover_excel_sheets_from_opj_sections
from deopjufier.opju import (
    OpjuColumnDescriptor,
    descriptor_table_metadata,
    group_opju_column_descriptors,
    iter_opju_column_descriptors,
    iter_opju_column_metadata,
)


def extract_books(
    input_path: Path,
    out_dir: Path,
    manifest: Manifest,
    *,
    output_format: str = "csv",
    force: bool = False,
    table_min_rows: int = 1,
    table_min_columns: int = 1,
    manifest_root: Path | None = None,
    file_data: bytes | None = None,
    objects: list[OriginObject] | None = None,
    allow_parser_recovery: bool | None = None,
    allow_heuristic_scan: bool = True,
    recovery_max_tables: int = 200,
    emit_unsupported_collection: bool = True,
    recovery_include_family_binary: bool = True,
    precomputed_opj_metadata: dict[str, OpjWorksheetMetadata] | None = None,
    include_descriptor_tables: bool = True,
    precomputed_opju_descriptors: tuple[OpjuColumnDescriptor, ...] | None = None,
    selected_names: set[str] | None = None,
    selected_object_keys: set[tuple[int, str, str]] | None = None,
) -> int:
    """Extract worksheet-like objects."""
    data = file_data if file_data is not None else input_path.read_bytes()
    is_opju = _is_opju_file(data, input_path)
    objects_for_extract = list(objects or [])
    descriptors = (
        precomputed_opju_descriptors
        if is_opju and include_descriptor_tables and precomputed_opju_descriptors is not None
        else (iter_opju_column_descriptors(data) if is_opju and include_descriptor_tables else ())
    )
    descriptor_metadata = iter_opju_column_metadata(data, descriptors) if is_opju else ()
    descriptor_tables = group_opju_column_descriptors(descriptors, descriptor_metadata)
    if selected_names is not None:
        descriptor_tables = tuple(table for table in descriptor_tables if table.name in selected_names)
    descriptor_source_ranges = {table.name: table.source_ranges for table in descriptor_tables}
    descriptor_table_names = set(descriptor_source_ranges)
    known_descriptor_objects = {
        obj.name for obj in objects_for_extract if getattr(obj, "parser_rule", None) == "opju_column_descriptor_table"
    }
    for table in descriptor_tables:
        if table.name in known_descriptor_objects:
            continue
        source_start = min(source_range["start"] for source_range in table.source_ranges)
        source_end = max(source_range["end"] for source_range in table.source_ranges)
        objects_for_extract.append(
            ParserBackedDiscoveryRecord(
                offset=source_start,
                name=table.name,
                length=source_end - source_start,
                object_kind="worksheet",
                source_object_path=table.name,
                parser_rule="opju_column_descriptor_table",
                parser_confidence=0.99,
            )
        )
    descriptor_tables_only = bool(descriptor_tables) and not allow_heuristic_scan
    if descriptor_tables_only:
        objects_for_extract = [
            obj for obj in objects_for_extract if getattr(obj, "parser_rule", None) == "opju_column_descriptor_table"
        ]
    if allow_parser_recovery is None:
        allow_parser_recovery = False

    worksheet_names: list[str] = []
    seen_worksheet_names: set[str] = set()
    for obj in objects_for_extract:
        if obj.object_kind != "worksheet":
            continue
        if selected_names is not None and obj.name not in selected_names:
            continue
        if obj.name in seen_worksheet_names:
            continue
        worksheet_names.append(obj.name)
        seen_worksheet_names.add(obj.name)

    if not is_opju:
        worksheet_names = sorted(_collapse_worksheet_recovery_names(set(worksheet_names)))
        seen_worksheet_names = set(worksheet_names)
    elif not worksheet_names:
        for name in sorted(_discover_worksheet_names_for_recovery(input_path)):
            if name not in seen_worksheet_names:
                worksheet_names.append(name)
                seen_worksheet_names.add(name)
    worksheet_objects_for_recovery = [
        obj
        for obj in objects_for_extract
        if obj.object_kind == "worksheet" and (selected_names is None or obj.name in selected_names)
    ]
    if is_opju and not descriptor_tables_only:
        try:
            discovered_worksheet_objects = [
                obj
                for obj in discover_origin_objects(
                    input_path,
                    allowed_kinds=frozenset({"worksheet"}),
                    collect_heuristics=True,
                    total_limit=None,
                )
                if obj.object_kind == "worksheet"
            ]
            known_recovery_objects = {
                (obj.offset, obj.name, obj.length, obj.source_object_path) for obj in worksheet_objects_for_recovery
            }
            known_extract_objects = {
                (obj.offset, obj.name, obj.length, obj.source_object_path) for obj in objects_for_extract
            }
            for obj in discovered_worksheet_objects:
                if selected_names is not None and obj.name not in selected_names:
                    continue
                key = (obj.offset, obj.name, obj.length, obj.source_object_path)
                if key not in known_recovery_objects:
                    worksheet_objects_for_recovery.append(obj)
                    known_recovery_objects.add(key)
                if key not in known_extract_objects:
                    objects_for_extract.append(obj)
                    known_extract_objects.add(key)
                if obj.name not in seen_worksheet_names:
                    worksheet_names.append(obj.name)
                    seen_worksheet_names.add(obj.name)
        except Exception:
            pass
    elif not worksheet_objects_for_recovery:
        try:
            worksheet_objects_for_recovery = [
                obj
                for obj in discover_origin_objects(
                    input_path,
                    allowed_kinds=frozenset({"worksheet"}),
                    collect_heuristics=True,
                    total_limit=None,
                )
                if obj.object_kind == "worksheet" and (selected_names is None or obj.name in selected_names)
            ]
        except Exception:
            worksheet_objects_for_recovery = []

    opju_rows_by_name: dict[str, list[list[str]]] = {}
    opju_dims_by_name: dict[str, tuple[int, int]] = {}
    recovered_parser_backed_worksheet_names: set[str] = set()

    if descriptor_tables_only:
        opju_rows_by_name = {table.name: table.text_rows() for table in descriptor_tables}
        opju_dims_by_name = {table.name: (table.row_count, len(table.columns)) for table in descriptor_tables}
        recovered_parser_backed_worksheet_names = set(opju_rows_by_name)
    elif not data.startswith(MAGIC_OPJ):
        (
            opju_rows_by_name,
            opju_dims_by_name,
            recovered_parser_backed_worksheet_names,
        ) = _recover_opju_worksheet_rows_compat(
            data,
            worksheet_names=set(worksheet_names),
            path=input_path,
            worksheet_objects=[obj for obj in worksheet_objects_for_recovery],
            max_tables=recovery_max_tables,
            include_family_binary=recovery_include_family_binary,
            include_descriptor_tables=False,
        )
        for table in descriptor_tables:
            opju_rows_by_name[table.name] = table.text_rows()
            opju_dims_by_name[table.name] = (table.row_count, len(table.columns))
            recovered_parser_backed_worksheet_names.add(table.name)
    if len(recovered_parser_backed_worksheet_names) <= _OPJU_PARSER_NAME_HINT_LIMIT:
        parser_backed_worksheet_names = set(recovered_parser_backed_worksheet_names)
    else:
        parser_backed_worksheet_names = {
            name for name in set(opju_rows_by_name) | set(opju_dims_by_name) if _looks_like_worksheet_object_name(name)
        }
    if not parser_backed_worksheet_names and recovered_parser_backed_worksheet_names:
        parser_backed_worksheet_names = {
            name
            for name in recovered_parser_backed_worksheet_names
            if _looks_like_worksheet_object_name(name) and name in set(worksheet_names)
        }
    if not parser_backed_worksheet_names:
        parser_backed_worksheet_names = {name for name in worksheet_names if _looks_like_worksheet_object_name(name)}
    has_recovered_non_family_rows_raw = any(
        name not in {"", "origin_storage_family_"} and not name.startswith("origin_storage_family_") and bool(rows)
        for name, rows in opju_rows_by_name.items()
    )
    opju_rows_by_name, opju_dims_by_name = _filter_meaningful_recovered_rows(
        opju_rows_by_name,
        opju_dims_by_name,
        parser_backed_worksheet_names=parser_backed_worksheet_names,
    )
    has_family_rows = any(name.startswith("origin_storage_family_") for name in opju_rows_by_name)
    if not parser_backed_worksheet_names and has_family_rows:
        # Keep concrete worksheet row bindings, but drop family-table rows unless
        # parser-backed worksheet names are available to anchor them safely.
        opju_rows_by_name = {
            name: rows for name, rows in opju_rows_by_name.items() if not name.startswith("origin_storage_family_")
        }
        opju_dims_by_name = {
            name: dims for name, dims in opju_dims_by_name.items() if not name.startswith("origin_storage_family_")
        }
    opj_rows_by_name: dict[str, list[list[str]]] = {}
    opj_dims_by_name: dict[str, tuple[int, int]] = {}
    opj_metadata_by_name: dict[str, OpjWorksheetMetadata] = {}
    if not is_opju and worksheet_names and allow_parser_recovery:
        opj_rows_by_name, opj_dims_by_name, opj_metadata_by_name = _recover_worksheet_records_compat(
            data,
            set(worksheet_names),
            parse_metadata=precomputed_opj_metadata is None,
            metadata_by_name=precomputed_opj_metadata,
        )

    recovered_rows_by_name = _merge_record_maps(opju_rows_by_name, opj_rows_by_name)
    recovered_dims_by_name = _merge_record_maps(opju_dims_by_name, opj_dims_by_name)
    has_recovered_non_family_rows = any(
        bool(rows) and not name.startswith("origin_storage_family_") for name, rows in recovered_rows_by_name.items()
    )
    if not has_recovered_non_family_rows:
        has_recovered_non_family_rows = has_recovered_non_family_rows_raw

    if is_opju:
        recovered_metadata_by_name = {table.name: descriptor_table_metadata(table) for table in descriptor_tables}
        if allow_parser_recovery and not descriptor_tables_only:
            metadata_name_hints = set(opju_rows_by_name)
            if parser_backed_worksheet_names:
                metadata_name_hints.update(parser_backed_worksheet_names)
            if metadata_name_hints:
                recovered_metadata_by_name = {
                    **{
                        name: metadata
                        for name, metadata in _recover_opju_worksheet_metadata_compat(
                            data,
                            worksheet_names=metadata_name_hints,
                            path=input_path,
                            include_descriptor_tables=False,
                        ).items()
                        if name in recovered_rows_by_name
                    },
                    **recovered_metadata_by_name,
                }
    else:
        recovered_metadata_by_name = opj_metadata_by_name

    scan_worksheet_name_hints = set(parser_backed_worksheet_names)
    if is_opju:
        scan_worksheet_name_hints.update(
            {
                obj.name
                for obj in worksheet_objects_for_recovery
                if obj.object_kind == "worksheet" and _looks_like_worksheet_object_name(obj.name)
            }
        )
        scan_worksheet_name_hints.update({obj.name for obj in worksheet_objects_for_recovery if obj.parser_confirmed})

    return _extract_tabular_objects(
        input_path,
        out_dir,
        manifest,
        object_kind="worksheet",
        manifest_item_kind="worksheet",
        collection_path="books",
        collection_name="book",
        filename_base="book",
        missing_error="no_worksheet_objects",
        output_format=output_format,
        force=force,
        table_min_rows=table_min_rows,
        table_min_columns=table_min_columns,
        manifest_root=manifest_root,
        file_data=data,
        objects=objects_for_extract,
        allow_parser_recovery=allow_parser_recovery,
        allow_heuristic_scan=allow_heuristic_scan,
        recovered_rows_by_name=recovered_rows_by_name,
        recovered_dimensions_by_name=recovered_dims_by_name,
        recovered_metadata_by_name=recovered_metadata_by_name,
        metadata_item_kind="worksheet_metadata",
        recovered_non_family_rows_present=has_recovered_non_family_rows,
        parser_backed_worksheet_name_hints=(parser_backed_worksheet_names if is_opju else None),
        scan_worksheet_name_hints=scan_worksheet_name_hints,
        recovery_max_tables=recovery_max_tables,
        recovery_include_family_binary=recovery_include_family_binary,
        verified_parser_table_names=descriptor_table_names,
        recovered_source_ranges_by_name=descriptor_source_ranges,
        selected_object_keys=selected_object_keys,
    )


def extract_excel(
    input_path: Path,
    out_dir: Path,
    manifest: Manifest,
    *,
    output_format: str = "csv",
    force: bool = False,
    table_min_rows: int = 1,
    table_min_columns: int = 1,
    manifest_root: Path | None = None,
    file_data: bytes | None = None,
    objects: list[OriginObject] | None = None,
    allow_parser_recovery: bool | None = None,
    allow_heuristic_scan: bool = True,
    emit_unsupported_collection: bool = True,
    precomputed_opj_metadata: dict[str, OpjWorksheetMetadata] | None = None,
    selected_object_keys: set[tuple[int, str, str]] | None = None,
) -> int:
    """Extract excel-like objects."""
    data = file_data if file_data is not None else input_path.read_bytes()
    objects_for_extract = list(objects or [])
    if allow_parser_recovery is None:
        allow_parser_recovery = False

    recovered_rows_by_name: dict[str, list[list[str]]] = {}
    recovered_dimensions_by_name: dict[str, tuple[int, int]] = {}
    recovered_metadata_by_name: dict[str, OpjWorksheetMetadata] = {}
    if data.startswith(MAGIC_OPJ) and allow_parser_recovery:
        excel_names = {obj.name for obj in objects_for_extract if obj.object_kind == "excel"}
        (
            recovered_rows_by_name,
            recovered_dimensions_by_name,
            recovered_metadata_by_name,
            recovered_sheet_objects,
        ) = recover_excel_sheets_from_opj_sections(
            data,
            excel_names,
            metadata_by_name=precomputed_opj_metadata,
        )
        if recovered_sheet_objects:
            objects_for_extract = [
                obj for obj in objects_for_extract if obj.object_kind != "excel"
            ] + recovered_sheet_objects

    return _extract_tabular_objects(
        input_path,
        out_dir,
        manifest,
        object_kind="excel",
        manifest_item_kind="excel",
        collection_path="excel",
        collection_name="excel",
        filename_base="excel",
        missing_error="no_excel_objects",
        output_format=output_format,
        force=force,
        table_min_rows=table_min_rows,
        table_min_columns=table_min_columns,
        manifest_root=manifest_root,
        file_data=data,
        objects=objects_for_extract,
        allow_parser_recovery=allow_parser_recovery,
        allow_heuristic_scan=allow_heuristic_scan,
        recovered_rows_by_name=recovered_rows_by_name,
        recovered_dimensions_by_name=recovered_dimensions_by_name,
        recovered_metadata_by_name=recovered_metadata_by_name,
        metadata_item_kind="excel_metadata",
        emit_unsupported_collection=emit_unsupported_collection,
        selected_object_keys=selected_object_keys,
    )


def extract_matrices(
    input_path: Path,
    out_dir: Path,
    manifest: Manifest,
    *,
    output_format: str = "csv",
    force: bool = False,
    table_min_rows: int = 1,
    table_min_columns: int = 1,
    manifest_root: Path | None = None,
    file_data: bytes | None = None,
    objects: list[OriginObject] | None = None,
    allow_parser_recovery: bool | None = None,
    allow_heuristic_scan: bool = True,
    recovery_max_tables: int = 200,
    emit_unsupported_collection: bool = True,
    recovery_include_family_binary: bool = True,
    precomputed_opj_metadata: dict[str, OpjMatrixMetadata] | None = None,
    selected_object_keys: set[tuple[int, str, str]] | None = None,
) -> int:
    """Extract matrix-like objects."""
    data = file_data if file_data is not None else input_path.read_bytes()
    objects_for_extract = list(objects or [])
    if allow_parser_recovery is None:
        allow_parser_recovery = False

    is_opju = _is_opju_file(data, input_path)
    matrix_names = {obj.name for obj in objects_for_extract if obj.object_kind == "matrix"}
    opj_rows_by_name: dict[str, list[list[str]]] = {}
    opj_dims_by_name: dict[str, tuple[int, int]] = {}
    opj_metadata_by_name: dict[str, OpjMatrixMetadata] = {}
    synthetic_matrix_objects: list[OriginObject] = []

    if is_opju and not matrix_names and not allow_parser_recovery:
        discovered_rows, discovered_dims, supported_names = _recover_opju_matrix_rows_compat(
            data,
            matrix_names=set(),
            path=input_path,
            max_tables=recovery_max_tables,
            include_family_binary=recovery_include_family_binary,
        )
        supported_matrix_rows = {name: values for name, values in discovered_rows.items() if name in supported_names}
        if supported_matrix_rows:
            opj_rows_by_name = supported_matrix_rows
            opj_dims_by_name = {
                name: discovered_dims[name] for name in supported_matrix_rows if name in discovered_dims
            }
            for name in supported_matrix_rows:
                synthetic_matrix_objects.append(
                    ParserBackedDiscoveryRecord(
                        offset=0,
                        name=name,
                        length=0,
                        object_kind="matrix",
                        source_object_path=f"Matrix/{name}",
                        parser_rule="opju_matrix_recovery",
                        parser_confidence=0.95,
                        parser_confirmed=True,
                    )
                )

    if synthetic_matrix_objects:
        objects_for_extract = list(objects_for_extract)
        objects_for_extract.extend(synthetic_matrix_objects)
        matrix_names = {obj.name for obj in objects_for_extract if obj.object_kind == "matrix"}

    if not is_opju and matrix_names and allow_parser_recovery:
        opj_rows_by_name, opj_dims_by_name, opj_metadata_by_name = _recover_matrix_records_compat(
            data,
            matrix_names,
            parse_metadata=precomputed_opj_metadata is None,
            metadata_by_name=precomputed_opj_metadata,
        )

    if (
        not is_opju
        and not allow_parser_recovery
        and matrix_names
        and not opj_rows_by_name
        and not opj_dims_by_name
        and not opj_metadata_by_name
        and all(
            any(_is_matrix_like_candidate_name(candidate) for candidate in _iter_opj_name_candidates(name))
            for name in matrix_names
        )
    ):
        emit_unsupported_collection = False

    return _extract_tabular_objects(
        input_path,
        out_dir,
        manifest,
        object_kind="matrix",
        manifest_item_kind="matrix",
        collection_path="matrices",
        collection_name="matrix",
        filename_base="matrix",
        missing_error="no_matrix_objects",
        output_format=output_format,
        force=force,
        table_min_rows=table_min_rows,
        table_min_columns=table_min_columns,
        manifest_root=manifest_root,
        file_data=data,
        objects=objects_for_extract,
        allow_parser_recovery=allow_parser_recovery,
        allow_heuristic_scan=allow_heuristic_scan,
        recovered_rows_by_name=opj_rows_by_name,
        recovered_dimensions_by_name=opj_dims_by_name,
        recovered_metadata_by_name=opj_metadata_by_name,
        metadata_item_kind="matrix_metadata",
        emit_unsupported_collection=emit_unsupported_collection,
        recovery_max_tables=recovery_max_tables,
        recovery_include_family_binary=recovery_include_family_binary,
        selected_object_keys=selected_object_keys,
    )
