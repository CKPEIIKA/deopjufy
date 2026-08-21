"""Security and dependency-surface checks for native mode."""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

from deopjufier import app, commands, extract
from tests.test_core_unit_coverage_utils import _repo_root

REPO_ROOT = _repo_root(Path(__file__))
PACKAGE_ROOT = REPO_ROOT / "deopjufier"

BAD_IMPORT_PREFIXES = (
    "socket",
    "urllib",
    "requests",
    "httpx",
    "aiohttp",
    "smtplib",
    "ftplib",
    "paramiko",
    "http",
)

BAD_TELEMETRY_KEYWORDS = (
    "telemetry",
    "sentry",
    "opentelemetry",
    "prometheus",
    "datadog",
)

BAD_RUNTIME_IMPORT_PREFIXES = (
    "subprocess",
    "pexpect",
    "os.system",
    "os.popen",
)

BAD_RUNTIME_COMMAND_PATTERNS = (
    re.compile(r"(^|\\W)convert[-_]opju(\\W|$)", re.IGNORECASE),
    re.compile(r"(^|\\W)origin\\s+viewer(\\W|$)", re.IGNORECASE),
    re.compile(r"(^|\\W)originviewer(\\W|$)", re.IGNORECASE),
    re.compile(r"(^|\\W)wine(\\W|$)", re.IGNORECASE),
    re.compile(r"(^|\\W)rscript(\\W|$)", re.IGNORECASE),
    re.compile(r"(^|\\W)originpro(\\W|$)", re.IGNORECASE),
)


def _iter_imported_modules(node: ast.AST) -> list[str]:
    imports: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Import):
            imports.extend(alias.name for alias in child.names)
        elif isinstance(child, ast.ImportFrom) and child.module is not None:
            if child.level == 0:
                imports.append(child.module)
    return imports


def _module_imports(module_path: Path) -> list[str]:
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
    return _iter_imported_modules(tree)


def test_native_package_has_no_network_imports() -> None:
    offenders: list[tuple[Path, str]] = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = _iter_imported_modules(tree)
        for name in imports:
            for prefix in BAD_IMPORT_PREFIXES:
                if name == prefix or name.startswith(f"{prefix}."):
                    offenders.append((path, name))
                    break

    assert not offenders, f"Network-related imports found in native package: {offenders}"


def test_native_package_has_no_telemetry_modules() -> None:
    offenders: list[tuple[Path, str]] = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        text = path.read_text(encoding="utf-8").lower()
        for keyword in BAD_TELEMETRY_KEYWORDS:
            if keyword in text:
                if f" {keyword} " in f" {text} ":
                    offenders.append((path, keyword))
                    break

    assert not offenders, f"Telemetry-like text found in native package: {offenders}"


def test_native_package_has_no_runtime_assisted_helpers() -> None:
    import_offenders: list[tuple[Path, str]] = []
    command_offenders: list[tuple[Path, str]] = []

    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for name in _iter_imported_modules(tree):
            for forbidden in BAD_RUNTIME_IMPORT_PREFIXES:
                if name == forbidden or name.startswith(f"{forbidden}."):
                    import_offenders.append((path, name))
                    break

        text = path.read_text(encoding="utf-8").lower()
        for pattern in BAD_RUNTIME_COMMAND_PATTERNS:
            if pattern.search(text):
                command_offenders.append((path, pattern.pattern))
                break

    assert not import_offenders, f"External runtime helper imports found in native package: {import_offenders}"
    assert not command_offenders, f"External runtime helper markers found in native package: {command_offenders}"


def test_cli_heuristic_policy_rules_live_in_support_module() -> None:
    inspect_module = PACKAGE_ROOT / "commands" / "inspect.py"
    list_module = PACKAGE_ROOT / "commands" / "list.py"
    forbidden_tokens = (
        "_OPJ_HEURISTIC_KIND_LIMIT_BYTES",
        "_OPJU_EXHAUSTIVE_HEURISTIC_KIND_LIMIT",
        "_DEFAULT_OPJ_HEURISTIC_KIND_LIMIT",
        "_DEFAULT_OPJU_HEURISTIC_KIND_LIMIT",
        "_coerce_list_heuristic_limit(",
        "32 * 1024 * 1024",
    )

    for module_path in (inspect_module, list_module):
        text = module_path.read_text(encoding="utf-8")
        found = [token for token in forbidden_tokens if token in text]
        assert not found, f"{module_path} contains duplicated heuristic policy literals/helpers: {found}"

    list_tree = ast.parse(list_module.read_text(encoding="utf-8"), filename=str(list_module))
    inspect_tree = ast.parse(inspect_module.read_text(encoding="utf-8"), filename=str(inspect_module))
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_coerce_list_heuristic_kind_limit"
        for node in ast.walk(list_tree)
    ), "list.py must call shared _coerce_list_heuristic_kind_limit helper from support.py"

    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_coerce_default_heuristic_kind_limit"
        for node in ast.walk(inspect_tree)
    ), "inspect.py must call shared _coerce_default_heuristic_kind_limit helper from support.py"


def test_opj_and_opju_modules_do_not_cross_import_parser_implementations() -> None:
    opj_module = PACKAGE_ROOT / "opj" / "__init__.py"
    opju_module = PACKAGE_ROOT / "opju" / "__init__.py"

    opj_imports = _module_imports(opj_module)
    opju_imports = _module_imports(opju_module)

    assert not any(name == "deopjufier.opju" or name.startswith("deopjufier.opju.") for name in opj_imports), (
        f"OPJ parser unexpectedly imports OPJU parser helpers: {opj_imports}"
    )
    assert not any(name == "deopjufier.opj" or name.startswith("deopjufier.opj.") for name in opju_imports), (
        f"OPJU parser unexpectedly imports OPJ parser helpers: {opju_imports}"
    )


def test_coverage_scope_is_frozen_to_package() -> None:
    project_toml = REPO_ROOT / "pyproject.toml"
    data = tomllib.loads(project_toml.read_text(encoding="utf-8"))
    coverage = data.get("tool", {}).get("coverage", {})
    run = coverage.get("run", {})

    assert run.get("source") == ["deopjufier"]
    assert "refs/*" in run.get("omit", [])
    assert "tests/*" in run.get("omit", [])


def test_coverage_make_targets_exclude_refs() -> None:
    makefile = REPO_ROOT / "Makefile"
    lines = makefile.read_text(encoding="utf-8").splitlines()
    targets = {"coverage", "coverage-report", "coverage-gate"}
    target_blocks: dict[str, list[str]] = {}
    current = None
    for line in lines:
        if not line.startswith(("\t", " ")):
            match = line.rstrip().split(":")[0]
            if match in targets:
                current = match
                target_blocks[current] = []
            else:
                current = None
            continue
        if current is not None and line.strip():
            target_blocks[current].append(line)

    for target in sorted(targets):
        block = target_blocks.get(target)
        assert block, f"Missing {target} target in Makefile"
        assert any("--cov-omit=refs/*" in line for line in block), (
            f"{target} target no longer omits refs/* from coverage"
        )

    assert not any("--cov-fail-under" in line for line in target_blocks["coverage-report"]), (
        "coverage-report should be non-gating and must not pass --cov-fail-under"
    )


def test_root_fixture_layout_is_separated_from_project_root() -> None:
    repo_root = REPO_ROOT
    disallowed = [
        path.name for path in repo_root.iterdir() if path.is_file() and path.suffix.lower() in {".opj", ".opju"}
    ]
    assert not disallowed, f"Origin fixtures must stay in the synthetic fixture directory, not repo root: {disallowed}"

    synthetic_dir = repo_root / "tests" / "fixtures" / "synthetic"
    has_synthetic_fixtures = any(path.suffix.lower() in {".opj", ".opju"} for path in synthetic_dir.iterdir())
    assert has_synthetic_fixtures, "Expected the author-generated synthetic fixture directory to provide inputs."


def test_public_api_allows_only_stable_entrypoints() -> None:
    assert all(not item.startswith("_") for item in app.__all__)
    assert all(not item.startswith("_") for item in commands.__all__)
    assert all(not item.startswith("_") for item in extract.__all__)
