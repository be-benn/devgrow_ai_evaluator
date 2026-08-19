import os
import re
from typing import List, Optional

from evaluator.config import LANGUAGE_EXTENSION_MAP
from evaluator.schemas import ParsedCodeFragment

# ── Optional tree-sitter import ─────────────────────────────
try:
    from tree_sitter_language_pack import get_parser as _ts_get_parser
    TREE_SITTER_AVAILABLE = True
except Exception:
    TREE_SITTER_AVAILABLE = False

_PARSER_CACHE: dict = {}


# ── Target node types per language ──────────────────────────
_DEFAULT_NODE_TYPES = {
    "function_declaration", "function_definition",
    "method_definition", "method_declaration",
    "class_declaration", "class_definition",
}

_LANGUAGE_NODE_TYPES = {
    "python": {
        "function_definition", "class_definition", "decorated_definition",
    },
    "javascript": _DEFAULT_NODE_TYPES,
    "typescript": _DEFAULT_NODE_TYPES,
    "tsx": _DEFAULT_NODE_TYPES,
    "java": {
        "method_declaration", "class_declaration",
        "constructor_declaration",
    },
    "go": {
        "function_declaration", "method_declaration",
        "type_declaration",
    },
    "ruby": {
        "method", "class", "module", "singleton_method",
    },
    "c": {
        "function_definition", "struct_specifier",
    },
    "cpp": {
        "function_definition", "class_specifier",
        "struct_specifier",
    },
    "c_sharp": {
        "method_declaration", "class_declaration",
        "constructor_declaration",
    },
    "php": {
        "method_declaration", "class_declaration",
        "function_definition",
    },
    "rust": {
        "function_item", "impl_item", "struct_item",
    },
    "kotlin": {
        "function_declaration", "class_declaration",
    },
    "swift": {
        "function_declaration", "class_declaration",
    },
    "scala": {
        "function_definition", "class_definition",
        "object_definition",
    },
}


def _get_parser(language_name: str):
    """Cached tree-sitter parser lookup."""
    if not TREE_SITTER_AVAILABLE:
        return None
    if language_name in _PARSER_CACHE:
        return _PARSER_CACHE[language_name]
    try:
        parser = _ts_get_parser(language_name)
    except Exception:
        parser = None
    _PARSER_CACHE[language_name] = parser
    return parser


def _node_text(node, source_bytes: bytes) -> str:
    return source_bytes[node.start_byte:node.end_byte].decode(
        "utf-8", errors="ignore"
    )


def _node_name(node, source_bytes: bytes) -> str:
    name_node = node.child_by_field_name("name")
    if name_node is not None:
        return _node_text(name_node, source_bytes)
    # For decorated definitions, try the inner node
    for child in node.children:
        inner_name = child.child_by_field_name("name")
        if inner_name is not None:
            return _node_text(inner_name, source_bytes)
    return ""


def _overlaps(
    node_start: int, node_end: int, changed_ranges: list
) -> bool:
    """Check if a node's line range overlaps any changed line range."""
    for line_range in changed_ranges:
        if (
            isinstance(line_range, list)
            and len(line_range) == 2
            and node_start <= line_range[1]
            and node_end >= line_range[0]
        ):
            return True
    return False


def parse_changed_code(
    file_path: str,
    content: str,
    change_type: str,
    added_lines: list,
    deleted_lines: list,
) -> List[ParsedCodeFragment]:
    """
    Parse a single file's changed code using tree-sitter.

    For newly added files: returns the entire file as a single fragment.
    For modified files: finds AST nodes overlapping changed line ranges
    and extracts their source code with structural context.
    Falls back to regex-based extraction if tree-sitter unavailable.
    """
    # Newly added files — include everything
    if change_type == "added":
        return [ParsedCodeFragment(
            filename=file_path,
            node_name="(entire file)",
            node_type="file",
            source_code=content,
            start_line=1,
            end_line=content.count("\n") + 1,
            context="new file",
        )]

    # Deleted files — nothing to evaluate
    if change_type == "deleted":
        return []

    # Modified / renamed / copied — extract changed structural nodes
    changed_ranges = added_lines  # focus on new code in target

    ext = os.path.splitext(file_path)[1].lower()
    language_name = LANGUAGE_EXTENSION_MAP.get(ext)

    if language_name:
        fragments = _parse_with_treesitter(
            file_path, content, language_name, changed_ranges
        )
        if fragments is not None:
            return fragments

    # Fallback: regex-based extraction
    return _parse_with_regex(file_path, content, changed_ranges)


def _parse_with_treesitter(
    file_path: str,
    content: str,
    language_name: str,
    changed_ranges: list,
) -> Optional[List[ParsedCodeFragment]]:
    """
    Tree-sitter based extraction. Returns None if parser unavailable.
    """
    parser = _get_parser(language_name)
    if parser is None:
        return None

    source_bytes = content.encode("utf-8", errors="ignore")
    try:
        tree = parser.parse(source_bytes)
    except Exception:
        return None

    target_types = _LANGUAGE_NODE_TYPES.get(
        language_name, _DEFAULT_NODE_TYPES
    )

    fragments = []
    _walk_for_changed_nodes(
        node=tree.root_node,
        source_bytes=source_bytes,
        target_types=target_types,
        changed_ranges=changed_ranges,
        file_path=file_path,
        fragments=fragments,
        class_context=None,
    )

    # If no structural nodes found but lines changed, extract raw changed lines
    if not fragments and changed_ranges:
        fragments = _extract_raw_changed_lines(
            file_path, content, changed_ranges
        )

    return fragments


def _walk_for_changed_nodes(
    node,
    source_bytes: bytes,
    target_types: set,
    changed_ranges: list,
    file_path: str,
    fragments: list,
    class_context: Optional[str],
):
    """Recursively walk AST and collect nodes overlapping changed lines."""
    node_type = node.type
    start_line = node.start_point[0] + 1  # tree-sitter is 0-indexed
    end_line = node.end_point[0] + 1
    name = _node_name(node, source_bytes)

    # Track class context
    current_class = class_context
    if node_type in {"class_definition", "class_declaration"} and name:
        current_class = name

    if (
        node_type in target_types
        and _overlaps(start_line, end_line, changed_ranges)
    ):
        context = ""
        if current_class and node_type not in {
            "class_definition", "class_declaration"
        }:
            context = f"class {current_class} > {node_type} {name}"
        elif name:
            context = f"{node_type} {name}"

        fragments.append(ParsedCodeFragment(
            filename=file_path,
            node_name=name or "(anonymous)",
            node_type=node_type,
            source_code=_node_text(node, source_bytes),
            start_line=start_line,
            end_line=end_line,
            context=context,
        ))
        # Don't recurse into children of matched nodes
        # (we already have the full source)
        return

    for child in node.children:
        _walk_for_changed_nodes(
            child, source_bytes, target_types, changed_ranges,
            file_path, fragments, current_class,
        )


def _parse_with_regex(
    file_path: str, content: str, changed_ranges: list
) -> List[ParsedCodeFragment]:
    """
    Regex fallback: find function/class definitions overlapping
    changed lines and extract their bodies.
    """
    lines = content.split("\n")
    total_lines = len(lines)

    # Find structural boundaries via regex
    boundary_pattern = re.compile(
        r"^(?:(?:export\s+)?(?:default\s+)?(?:const|async\s+function|function|class|def|async\s+def))\s+\w",
        re.MULTILINE,
    )

    # Build line-number-indexed boundaries
    boundaries = []
    for match in boundary_pattern.finditer(content):
        line_num = content[:match.start()].count("\n") + 1
        boundaries.append(line_num)

    if not boundaries:
        # No structural boundaries found; extract raw changed lines
        return _extract_raw_changed_lines(file_path, content, changed_ranges)

    fragments = []
    for i, start in enumerate(boundaries):
        end = boundaries[i + 1] - 1 if i + 1 < len(boundaries) else total_lines

        if _overlaps(start, end, changed_ranges):
            block_lines = lines[start - 1:end]
            block_text = "\n".join(block_lines)
            # Extract name from first line
            name_match = re.match(
                r"(?:.*\s)?(?:def|function|class|const)\s+(\w+)",
                block_lines[0] if block_lines else "",
            )
            name = name_match.group(1) if name_match else "(block)"

            fragments.append(ParsedCodeFragment(
                filename=file_path,
                node_name=name,
                node_type="regex_block",
                source_code=block_text,
                start_line=start,
                end_line=end,
                context=f"{file_path}:{start}-{end}",
            ))

    if not fragments:
        fragments = _extract_raw_changed_lines(
            file_path, content, changed_ranges
        )

    return fragments


def _extract_raw_changed_lines(
    file_path: str, content: str, changed_ranges: list
) -> List[ParsedCodeFragment]:
    """
    Last-resort fallback: extract raw changed lines with a few
    lines of surrounding context.
    """
    lines = content.split("\n")
    total_lines = len(lines)
    context_padding = 3
    fragments = []

    for line_range in changed_ranges:
        if not isinstance(line_range, list) or len(line_range) != 2:
            continue
        start = max(1, line_range[0] - context_padding)
        end = min(total_lines, line_range[1] + context_padding)
        block = "\n".join(lines[start - 1:end])
        fragments.append(ParsedCodeFragment(
            filename=file_path,
            node_name=f"lines {line_range[0]}-{line_range[1]}",
            node_type="raw_lines",
            source_code=block,
            start_line=start,
            end_line=end,
            context=f"{file_path}:{start}-{end}",
        ))

    return fragments
