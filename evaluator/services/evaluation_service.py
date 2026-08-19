import logging
import re
from typing import List

from pydantic import ValidationError

from evaluator.schemas import (
    ChunkEvaluationResult,
    EvaluationRequest,
    EvaluationResponse,
    RubricScore,
)
from evaluator.services.acceptance_criteria import normalize_acceptance_criteria
from evaluator.services.git_service import GitService
from evaluator.services.parser_service import parse_changed_code
from evaluator.services.chunker_service import create_chunks
from evaluator.services.llm_service import get_llm_json_response

logger = logging.getLogger(__name__)


def evaluate(request: EvaluationRequest) -> EvaluationResponse:
    """
    Main evaluation pipeline:

    1. Normalize acceptance criteria text → list
    2. Git diff → changed files + line ranges
    3. Tree-sitter parse → extract changed code with structural context
    4. Structure-aware chunking
    5. LLM evaluation per chunk (Pydantic-validated)
    6. Append/consolidate chunk results
    7. Final LLM evaluation (V1-style rubric, Pydantic-validated)
    8. Deterministic score computation
    9. Return V1-compatible output
    """

    # ── Step 1: Normalize acceptance criteria ────────────────
    criteria_list = normalize_acceptance_criteria(
        request.acceptance_criteria
    )
    if not criteria_list:
        return EvaluationResponse(
            score=0,
            status="Not Met",
            summary="No acceptance criteria provided.",
            issues=["No acceptance criteria to evaluate against."],
            strengths=[],
            rubric={},
        )

    logger.info("Step 1: %d acceptance criteria parsed.", len(criteria_list))

    # ── Step 2: Git diff ────────────────────────────────────
    try:
        git_service = GitService(request.repository_path)
        diff_result = git_service.get_diff(
            request.base_commit,
            request.target_commit,
            branch=request.branch,
        )
    except Exception as e:
        logger.error("Git diff failed: %s", e)
        return EvaluationResponse(
            score=0,
            status="Not Met",
            summary=f"Git analysis failed: {e}",
            issues=[f"Git error: {e}"],
            strengths=[],
            rubric={},
        )

    changes = diff_result.get("changes", [])
    if not changes:
        return EvaluationResponse(
            score=0,
            status="Not Met",
            summary="No code changes found between the commits.",
            issues=["No changed files detected in the commit diff."],
            strengths=[],
            rubric={},
        )

    logger.info("Step 2: %d changed file(s) from git diff.", len(changes))

    # ── Step 3: Tree-sitter parse ───────────────────────────
    all_fragments = []
    for change in changes:
        file_path = change.get("new_path") or change.get("old_path")
        if not file_path:
            continue

        content = git_service.read_file_content(file_path)
        if content is None:
            continue

        fragments = parse_changed_code(
            file_path=file_path,
            content=content,
            change_type=change["change_type"],
            added_lines=change.get("added_lines", []),
            deleted_lines=change.get("deleted_lines", []),
        )
        all_fragments.extend(fragments)

    if not all_fragments:
        return EvaluationResponse(
            score=0,
            status="Not Met",
            summary="No parseable code changes found.",
            issues=["Changed files could not be parsed or contained no code."],
            strengths=[],
            rubric={},
        )

    logger.info(
        "Step 3: %d code fragment(s) extracted via tree-sitter.",
        len(all_fragments),
    )

    # ── Step 4: Structure-aware chunking ─────────────────────
    chunks = create_chunks(all_fragments)
    total_chunks = len(chunks)
    logger.info("Step 4: %d chunk(s) created.", total_chunks)

    # ── Step 5: LLM evaluation per chunk ─────────────────────
    all_strengths = []
    all_issues = []
    all_evidence = []

    criteria_text = "\n".join(
        f"  {i+1}. {c}" for i, c in enumerate(criteria_list)
    )

    for i, chunk in enumerate(chunks):
        logger.info("Step 5: Evaluating chunk %d/%d...", i + 1, total_chunks)

        chunk_result = _evaluate_chunk(
            chunk=chunk,
            chunk_index=i + 1,
            total_chunks=total_chunks,
            project_title=request.project_title,
            project_description=request.project_description,
            task_title=request.task_title,
            task_description=request.task_description,
            criteria_text=criteria_text,
            difficulty=request.difficulty,
        )

        all_strengths.extend(chunk_result.strengths)
        all_issues.extend(chunk_result.issues)
        all_evidence.extend(chunk_result.evidence)

    # ── Step 6: Consolidate (deduplicate) ────────────────────
    unique_strengths = _deduplicate(all_strengths)
    unique_issues = _deduplicate(all_issues)
    unique_evidence = _deduplicate(all_evidence)

    logger.info(
        "Step 6: Consolidated — %d issues, %d strengths.",
        len(unique_issues),
        len(unique_strengths),
    )

    # ── Step 7: Final LLM evaluation (V1-style rubric) ───────
    rubric = _final_scoring(
        project_title=request.project_title,
        project_description=request.project_description,
        task_title=request.task_title,
        task_description=request.task_description,
        criteria_text=criteria_text,
        unique_issues=unique_issues,
        unique_strengths=unique_strengths,
        unique_evidence=unique_evidence,
    )

    # ── Step 8: Deterministic score computation ──────────────
    final_score = min(
        rubric.requirement_coverage
        + rubric.correctness
        + rubric.code_quality
        + rubric.best_practices,
        100,
    )

    logger.info(
        "Step 8: Final score = %d, status = %s.",
        final_score, rubric.criteria_status,
    )

    # ── Step 9: V1-compatible output ─────────────────────────
    return EvaluationResponse(
        score=final_score,
        status=rubric.criteria_status,
        summary=rubric.summary,
        issues=unique_issues,
        strengths=unique_strengths[:5],
        rubric={
            "requirement_coverage": rubric.requirement_coverage,
            "correctness": rubric.correctness,
            "code_quality": rubric.code_quality,
            "best_practices": rubric.best_practices,
        },
    )


# ── Private helpers ─────────────────────────────────────────


def _evaluate_chunk(
    chunk: str,
    chunk_index: int,
    total_chunks: int,
    project_title: str,
    project_description: str,
    task_title: str,
    task_description: str,
    criteria_text: str,
    difficulty: str,
) -> ChunkEvaluationResult:
    """
    Send one chunk to the LLM for evaluation.
    Validates the response with Pydantic.
    """
    prompt = f"""
You are a Senior Code Reviewer. Analyze Part {chunk_index}/{total_chunks} of the submitted code.

**PROJECT:** {project_title}
**PROJECT DESCRIPTION:** {project_description}
**TASK:** {task_title}
**TASK DESCRIPTION:** {task_description}
**DIFFICULTY:** {difficulty}

**ACCEPTANCE CRITERIA:**
{criteria_text}

**ANALYSIS INSTRUCTIONS:**
1. Evaluate the code against EACH acceptance criterion listed above.
2. Report ONLY what you can DIRECTLY observe in this code chunk.
3. DO NOT report issues about code that may exist in other chunks.
4. DO NOT assign scores — only report observable facts.
5. Focus on: Logic Errors, Hardcoding, Syntax issues, and Criteria implementation.

**OUTPUT JSON ONLY:**
{{
  "strengths": ["List specific strengths DIRECTLY visible in THIS chunk"],
  "issues": ["List specific issues DIRECTLY visible in THIS chunk"],
  "evidence": ["Direct code quotes or references supporting your findings"]
}}

**CODE CHUNK:**
{chunk}
"""
    try:
        raw = get_llm_json_response(prompt)
        return ChunkEvaluationResult(**raw)
    except ValidationError as e:
        logger.warning(
            "Chunk %d/%d Pydantic validation failed: %s",
            chunk_index, total_chunks, e,
        )
        # Attempt graceful extraction from malformed response
        return _extract_chunk_result_gracefully(raw if 'raw' in dir() else {})
    except Exception as e:
        logger.error(
            "Chunk %d/%d evaluation failed: %s",
            chunk_index, total_chunks, e,
        )
        return ChunkEvaluationResult(
            issues=[f"Chunk {chunk_index} analysis failed: {e}"],
            strengths=[],
            evidence=[],
        )


def _final_scoring(
    project_title: str,
    project_description: str,
    task_title: str,
    task_description: str,
    criteria_text: str,
    unique_issues: list,
    unique_strengths: list,
    unique_evidence: list,
) -> RubricScore:
    """
    Final scoring LLM call using V1-style rubric.
    Validates the response with Pydantic.
    """
    prompt = f"""
You are a Code Evaluation Judge. Score the submitted code using a FIXED rubric.

**PROJECT:** {project_title}
**PROJECT DESCRIPTION:** {project_description}
**TASK:** {task_title}
**TASK DESCRIPTION:** {task_description}

**ACCEPTANCE CRITERIA:**
{criteria_text}

**CONSOLIDATED FINDINGS:**
Issues   : {unique_issues}
Strengths: {unique_strengths}
Evidence : {unique_evidence}

**SCORING RUBRIC — assign points within each stated range:**
- requirement_coverage : 0–40  (Does the code implement what was asked?)
- correctness          : 0–25  (Is the logic correct and free of bugs?)
- code_quality         : 0–20  (Is the code clean, readable, well-structured?)
- best_practices       : 0–15  (Does it follow conventions for its language/framework?)

**RULES:**
- Base scores ONLY on the consolidated findings above. Do NOT invent new issues.
- DO NOT return a total score. The total will be computed separately in code.
- criteria_status: "Met" if requirement_coverage >= 30, "Partially Met" if >= 15, else "Not Met".

**OUTPUT JSON ONLY:**
{{
    "requirement_coverage": 36,
    "correctness": 20,
    "code_quality": 17,
    "best_practices": 11,
    "criteria_status": "Met",
    "summary": "One sentence summarising the overall evaluation."
}}
"""
    try:
        raw = get_llm_json_response(prompt)
        return RubricScore(**raw)
    except ValidationError as e:
        logger.warning("Final scoring Pydantic validation failed: %s", e)
        return _extract_rubric_gracefully(raw if 'raw' in dir() else {})
    except Exception as e:
        logger.error("Final scoring failed: %s", e)
        return RubricScore(
            requirement_coverage=0,
            correctness=0,
            code_quality=0,
            best_practices=0,
            criteria_status="Not Met",
            summary=f"Final scoring failed: {e}",
        )


def _extract_chunk_result_gracefully(raw: dict) -> ChunkEvaluationResult:
    """Best-effort extraction when Pydantic validation fails."""
    return ChunkEvaluationResult(
        strengths=raw.get("strengths", []) if isinstance(raw.get("strengths"), list) else [],
        issues=raw.get("issues", []) if isinstance(raw.get("issues"), list) else [],
        evidence=raw.get("evidence", []) if isinstance(raw.get("evidence"), list) else [],
    )


def _extract_rubric_gracefully(raw: dict) -> RubricScore:
    """Best-effort extraction when Pydantic validation fails."""
    def clamp(val, lo, hi):
        try:
            return max(lo, min(hi, int(val)))
        except (TypeError, ValueError):
            return lo

    return RubricScore(
        requirement_coverage=clamp(raw.get("requirement_coverage", 0), 0, 40),
        correctness=clamp(raw.get("correctness", 0), 0, 25),
        code_quality=clamp(raw.get("code_quality", 0), 0, 20),
        best_practices=clamp(raw.get("best_practices", 0), 0, 15),
        criteria_status=raw.get("criteria_status", "Not Met"),
        summary=raw.get("summary", "Scoring completed with validation warnings."),
    )


def _deduplicate(items: List[str]) -> List[str]:
    """
    Deduplicate findings by keyword overlap.
    Same approach as V1's consolidate_findings.
    """
    seen_word_sets = []
    unique = []
    for item in items:
        if not isinstance(item, str):
            continue
        words = set(re.sub(r"[^\w\s]", "", item.lower()).split())
        if not any(len(words & seen) >= 3 for seen in seen_word_sets):
            unique.append(item)
            seen_word_sets.append(words)
    return unique
