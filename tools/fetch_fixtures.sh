#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)
REGISTRY_FILE="$SCRIPT_DIR/zenodo_fixtures.sha256"
TARGET_DIR="${1:-$REPO_ROOT/refs/public/zenodo}"

usage() {
    cat <<'USAGE'
Usage: fetch_fixtures.sh [TARGET_DIR]

Download known public Zenodo fixtures listed in tools/zenodo_fixtures.sha256
into TARGET_DIR (defaults to refs/public/zenodo).

If a fixture already exists and a checksum is provided, it is verified and
re-downloaded only when it does not match.
USAGE
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    usage
    exit 0
fi

if [[ ! -f "$REGISTRY_FILE" ]]; then
    echo "registry file not found: $REGISTRY_FILE" >&2
    exit 1
fi

mkdir -p "$TARGET_DIR"

while IFS= read -r line; do
    case "$line" in
        ""|"#"*)
            continue
            ;;
    esac

    record_id=$(awk '{print $1}' <<<"$line")
    filename=$(awk '{print $2}' <<<"$line")
    expected_sha=$(awk '{print $3}' <<<"$line")

    if [[ -z "$record_id" || -z "$filename" ]]; then
        echo "invalid registry line: $line" >&2
        exit 1
    fi

    destination="$TARGET_DIR/$filename"
    url="https://zenodo.org/records/$record_id/files/$filename/content"

    if [[ -f "$destination" ]]; then
        if [[ -n "$expected_sha" && "$expected_sha" != "-" ]]; then
            if sha256sum --check --status <<<"$expected_sha  $destination"; then
                echo "already present: $filename"
                continue
            fi
        else
            echo "already present (no checksum): $filename"
            continue
        fi
    fi

    echo "downloading: $filename"
    curl -L --fail --show-error --silent "$url" -o "$destination"

    if [[ -n "$expected_sha" && "$expected_sha" != "-" ]]; then
        if ! sha256sum --check --status <<<"$expected_sha  $destination"; then
            echo "checksum mismatch: $filename" >&2
            exit 1
        fi
    fi

done < "$REGISTRY_FILE"

echo "fixture sync complete: $(realpath "$TARGET_DIR")"
