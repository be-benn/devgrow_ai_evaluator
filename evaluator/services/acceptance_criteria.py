import re
from typing import List


def normalize_acceptance_criteria(text: str) -> List[str]:
    """
    Split free-form acceptance criteria text into a clean list.

    Handles:
    - Newline-separated items
    - Numbered lists  (1. / 1) / 1:)
    - Bullet lists    (- / * / •)
    - Semicolons
    """
    if not text or not text.strip():
        return []

    # First split by newlines
    lines = text.splitlines()

    # If only one line, try splitting by semicolons or numbered patterns
    if len(lines) == 1:
        # Try semicolons
        parts = text.split(";")
        if len(parts) > 1:
            lines = parts
        else:
            # Try numbered pattern like "1. foo 2. bar"
            split = re.split(r"(?:^|\s)\d+[.):\-]\s+", text)
            if len(split) > 1:
                lines = split

    criteria = []
    for line in lines:
        # Strip bullet / number prefixes
        cleaned = re.sub(
            r"^\s*(?:\d+[.):\-]|[-*•])\s*",
            "",
            line.strip(),
        )
        cleaned = cleaned.strip()
        if cleaned:
            criteria.append(cleaned)

    return criteria
