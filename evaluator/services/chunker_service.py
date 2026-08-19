from typing import List

from evaluator.config import CHUNK_SIZE_LIMIT, CHUNK_OVERLAP
from evaluator.schemas import ParsedCodeFragment


def create_chunks(
    fragments: List[ParsedCodeFragment],
    chunk_size: int = CHUNK_SIZE_LIMIT,
    overlap: int = CHUNK_OVERLAP,
) -> List[str]:
    """
    Group parsed code fragments into chunks suitable for LLM evaluation.

    - If total size fits within chunk_size → single chunk.
    - Otherwise, group fragments keeping related ones together
      (same file, same class context), splitting at structural boundaries.
    - Never splits mid-function unless a single function exceeds the limit.

    Returns a list of formatted chunk strings, each containing
    code with contextual headers.
    """
    if not fragments:
        return []

    formatted = [_format_fragment(f) for f in fragments]
    total_size = sum(len(f) for f in formatted)

    # Fits in a single chunk
    if total_size <= chunk_size:
        return ["\n\n".join(formatted)]

    # Need to split into multiple chunks
    return _split_into_chunks(formatted, chunk_size, overlap)


def _format_fragment(fragment: ParsedCodeFragment) -> str:
    """Format a single fragment with its context header."""
    header_parts = [f"# File: {fragment.filename}"]
    if fragment.context:
        header_parts.append(f"# Context: {fragment.context}")
    if fragment.node_name and fragment.node_name != "(entire file)":
        header_parts.append(
            f"# {fragment.node_type}: {fragment.node_name} "
            f"(lines {fragment.start_line}-{fragment.end_line})"
        )
    header = "\n".join(header_parts)
    return f"{header}\n{fragment.source_code}"


def _split_into_chunks(
    formatted_fragments: List[str],
    chunk_size: int,
    overlap: int,
) -> List[str]:
    """
    Pack fragments into chunks greedily by size, splitting at
    fragment boundaries. If a single fragment exceeds chunk_size,
    sub-split it by lines.
    """
    chunks = []
    current_parts = []
    current_size = 0

    for fragment_text in formatted_fragments:
        frag_size = len(fragment_text)

        # Single fragment too large — sub-split by lines
        if frag_size > chunk_size:
            # Flush current chunk first
            if current_parts:
                chunks.append("\n\n".join(current_parts))
                current_parts = []
                current_size = 0
            sub_chunks = _split_text_smartly(
                fragment_text, chunk_size, overlap
            )
            chunks.extend(sub_chunks)
            continue

        # Would exceed limit — flush and start new chunk
        if current_size + frag_size + 2 > chunk_size:  # +2 for \n\n join
            if current_parts:
                chunks.append("\n\n".join(current_parts))
            current_parts = [fragment_text]
            current_size = frag_size
        else:
            current_parts.append(fragment_text)
            current_size += frag_size + 2

    # Flush remaining
    if current_parts:
        chunks.append("\n\n".join(current_parts))

    return chunks


def _split_text_smartly(
    content: str,
    chunk_size: int = CHUNK_SIZE_LIMIT,
    overlap: int = CHUNK_OVERLAP,
) -> List[str]:
    """
    Character-based splitter with newline-alignment and overlap.
    Same approach as V1's split_content_smartly.
    """
    if not content:
        return []
    if len(content) < chunk_size:
        return [content]

    chunks = []
    start = 0
    while start < len(content):
        end = min(start + chunk_size, len(content))
        if end < len(content):
            newline_pos = content.rfind("\n", start, end)
            if newline_pos != -1 and newline_pos > (start + chunk_size // 2):
                end = newline_pos + 1
        chunks.append(content[start:end])
        next_start = end - overlap
        if next_start <= start:
            next_start = end
        start = next_start
        if start >= len(content):
            break

    return chunks
