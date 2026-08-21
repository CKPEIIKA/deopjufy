from deopjufier.commands.simple_shared import *


def cmd_strings(args):
    _ensure_file(args.file)
    if getattr(args, "decoded", False):
        data = args.file.read_bytes()
        if not data.startswith(b"CPYUA"):
            raise UnsupportedFileError("--decoded requires a recognized OPJU file")
        values = (
            item.value
            for item in iter_opju_decoded_strings(
                data,
                encoding=args.encoding,
                min_length=args.min_length,
            )
        )
    else:
        values = iter_strings(args.file, encoding=args.encoding, min_length=args.min_length)
    if args.quiet:
        return EXIT_SUCCESS
    for value in values:
        try:
            print(value)
        except OSError:
            # In constrained environments, long textual output may exceed the
            # process' output sink capacity; degrade to partial output without
            # hard-failing the command contract.
            break
    return EXIT_SUCCESS


def cmd_images(args):
    session = _build_session(args.file)
    detection = session.detection
    as_json = getattr(args, "json", False)
    if detection.detected_type not in {"opj", "opju"}:
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
    use_parser_only_images = (
        detection.detected_type == "opj" and session.size_bytes > _EXTRACT_LARGE_FILE_HEURISTIC_LIMIT_BYTES
    )
    extract_images(
        args.file,
        outdir,
        manifest,
        force=args.force,
        objects=(
            session.objects(collect_heuristics=not use_parser_only_images) if detection.detected_type == "opj" else None
        ),
        manifest_root=outdir,
    )
    paths = sorted(item.path for item in manifest.items if item.status == "extracted" and item.path)
    if as_json:
        payload = manifest.to_dict()
        payload["input"]["detected_type"] = detection.detected_type
        payload["status"] = "ok" if paths else "unsupported"
        if not args.quiet:
            print(json.dumps(payload, indent=2, sort_keys=True))
        return EXIT_UNSUPPORTED if not paths else EXIT_SUCCESS

    if not args.quiet:
        for path in paths:
            print(path)
    if not paths:
        if not args.quiet:
            print(f"deopjufy: no images found in {args.file}", file=sys.stderr)
        return EXIT_UNSUPPORTED
    return EXIT_SUCCESS


def cmd_table_scan(args):
    _ensure_file(args.file)
    if args.quiet:
        count = sum(
            1
            for _ in scan_numeric_tables(
                args.file,
                min_rows=args.min_rows,
                min_columns=args.min_columns,
            )
        )
    elif args.format == "json" or getattr(args, "json", False):
        rows = [
            {
                "table_id": table_id,
                "row_in_table": row_in_table,
                "offset": offset,
                "columns": len(values),
                "values": values,
            }
            for table_id, row_in_table, offset, values in scan_numeric_tables(
                args.file, min_rows=args.min_rows, min_columns=args.min_columns
            )
        ]
        json.dump(rows, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        count = len(rows)
    else:
        delimiter = "\t" if args.format == "tsv" else ","
        count = write_tables_csv(
            args.file,
            sys.stdout,
            min_rows=args.min_rows,
            min_columns=args.min_columns,
            delimiter=delimiter,
        )

    if count == 0:
        print("# no numeric table rows detected", file=sys.stderr)
        detection = detect_file(args.file)
        if detection.detected_type in SUPPORTED_TYPES:
            return EXIT_UNSUPPORTED
        return EXIT_SUCCESS

    return EXIT_SUCCESS


def _walk_element_payload(element):
    return {
        "kind": element.kind,
        "name": element.name,
        "start_offset": element.start_offset,
        "end_offset": element.end_offset,
        "length": max(0, element.end_offset - element.start_offset),
        "metadata": element.metadata,
    }


def cmd_walk(args):
    _ensure_file(args.file)
    detection = detect_file(args.file)
    if detection.detected_type not in {"opj", "opju"}:
        raise UnsupportedFileError("walk requires a recognized .opj or .opju file")

    payload = args.file.read_bytes()
    if detection.detected_type == "opju":
        elements = walk_opju_file(payload)
    else:
        try:
            elements = walk_opj_file(payload, tolerant=True)
        except OpjStreamError as exc:
            raise UnsupportedFileError(f"OPJ stream walk failed: {exc}") from exc

    output = [_walk_element_payload(element) for element in elements]

    if getattr(args, "json", False):
        if not args.quiet:
            print(json.dumps(output, indent=2, sort_keys=True))
        return EXIT_SUCCESS

    if not output:
        if not args.quiet:
            print("# no walkable Origin elements found", file=sys.stderr)
        return EXIT_SUCCESS

    for element in output:
        if args.quiet:
            continue
        line = (
            f"{element['kind']}\t{element['start_offset']}\t"
            f"{element['end_offset']}\t{element['length']}\t"
            f"{element['name'] or ''}"
        )
        print(line)

    return EXIT_SUCCESS


def cmd_dump_block(args):
    _ensure_file(args.file)
    if args.offset < 0 or args.length < 0:
        raise ValueError("offset and length must be non-negative")

    block = dump_range(args.file, args.offset, args.length)
    if not block and args.length > 0:
        raise CorruptedInputError("offset/length outside file range")

    if not args.quiet:
        sys.stdout.buffer.write(block)
    return EXIT_SUCCESS


def cmd_compare(args):
    result = compare_manifests(args.left, args.right, compare_bytes=args.compare_bytes)
    if getattr(args, "json", False):
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        _print_compare_summary(result)
    return EXIT_SUCCESS if result["match"] else EXIT_GENERAL


def cmd_strings_payload(manifest):
    return _coerce_counts_by_artifact(manifest)


__all__ = [
    "cmd_compare",
    "cmd_dump_block",
    "cmd_images",
    "cmd_strings",
    "cmd_strings_payload",
    "cmd_table_scan",
    "cmd_walk",
]
