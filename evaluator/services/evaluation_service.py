import logging
import os
import re
import tempfile
from typing import List

from pydantic import ValidationError

from evaluator.schemas import (
    ChunkEvaluationResult,
    EvaluationRequest,
    EvaluationResponse,
    RubricScore,
)
from evaluator.services.acceptance_criteria import (
    normalize_acceptance_criteria,
)
from evaluator.services.git_service import GitService
from evaluator.services.parser_service import parse_changed_code
from evaluator.services.chunker_service import create_chunks
from evaluator.services.llm_service import get_llm_json_response


logger = logging.getLogger(__name__)


ZERO_RUBRIC = {
    "requirement_coverage": 0,
    "correctness": 0,
}


def evaluate(request: EvaluationRequest) -> EvaluationResponse:
    """
    Public entry point for evaluation.

    repository_path supports:
    1. Local Git repository path
    2. Remote Git repository URL

    Evaluation modes:

    1. base_commit + target_commit
       -> Git diff identifies changed files
       -> complete target version of changed files is evaluated

    2. base_commit + target_commit=""
       -> complete supported source files from base_commit are evaluated
    """

    repository_value = request.repository_path

    # ── Remote repository URL ───────────────────────────────
    if GitService.is_repository_url(repository_value):

        try:
            with tempfile.TemporaryDirectory() as temp_dir:

                repository_dir = os.path.join(
                    temp_dir,
                    "repository",
                )

                cloned_path = GitService.clone_repository(
                    repository_value,
                    repository_dir,
                )

                logger.info(
                    "Repository cloned to temporary path: %s",
                    cloned_path,
                )

                return _run_evaluation(
                    request=request,
                    repository_path=cloned_path,
                )

        except Exception as e:
            logger.error(
                "Repository preparation failed: %s",
                e,
            )

            return EvaluationResponse(
                score=0,
                status="Not Met",
                summary=f"Repository preparation failed: {e}",
                issues=[
                    f"Repository error: {e}"
                ],
                strengths=[],
                rubric=ZERO_RUBRIC.copy(),
            )

    # ── Local repository path ───────────────────────────────
    return _run_evaluation(
        request=request,
        repository_path=repository_value,
    )


def _run_evaluation(
    request: EvaluationRequest,
    repository_path: str,
) -> EvaluationResponse:
    """
    Main evaluation pipeline.

    1. Normalize acceptance criteria
    2. Perform Git analysis
    3. Identify files in student scope
    4. Read complete source from selected revision
    5. Parse complete files
    6. Create chunks
    7. Evaluate chunks using LLM
    8. Consolidate findings
    9. Final scoring
    10. Return evaluation response
    """

    # ── Step 1: Normalize acceptance criteria ───────────────
    criteria_list = normalize_acceptance_criteria(
        request.acceptance_criteria
    )

    if not criteria_list:
        return EvaluationResponse(
            score=0,
            status="Not Met",
            summary="No acceptance criteria provided.",
            issues=[
                "No acceptance criteria to evaluate against."
            ],
            strengths=[],
            rubric=ZERO_RUBRIC.copy(),
        )

    logger.info(
        "Step 1: %d acceptance criteria parsed.",
        len(criteria_list),
    )

    # ── Step 2: Git analysis ────────────────────────────────
    try:
        git_service = GitService(
            repository_path
        )

        # ----------------------------------------------------
        # CASE 1:
        # target_commit is supplied.
        #
        # Git diff determines which files belong to
        # the submitted student change.
        # ----------------------------------------------------
        if request.target_commit:

            diff_result = git_service.get_diff(
                request.base_commit,
                request.target_commit,
                branch=request.branch,
            )

            base_sha = diff_result["base_commit"]
            target_sha = diff_result["target_commit"]

            changes = diff_result.get(
                "changes",
                [],
            )

            logger.info(
                "Diff evaluation: %s -> %s",
                base_sha,
                target_sha,
            )

            if not changes:
                return EvaluationResponse(
                    score=0,
                    status="Not Met",
                    summary=(
                        "No code changes found between "
                        "the base and target commits."
                    ),
                    issues=[],
                    strengths=[],
                    rubric=ZERO_RUBRIC.copy(),
                )

        # ----------------------------------------------------
        # CASE 2:
        # target_commit == ""
        #
        # Evaluate the complete base branch.
        # ----------------------------------------------------
        else:

            base_sha = git_service._resolve_commit(
                request.base_commit
            )

            # Reuse the existing target-reading flow.
            target_sha = base_sha

            files = git_service.get_files_at_revision(
                request.base_commit
            )

            changes = [
                {
                    "change_type": "added",
                    "old_path": None,
                    "new_path": file_path,
                    "added_lines": [],
                    "deleted_lines": [],
                }
                for file_path in files
            ]

            logger.info(
                "Single-branch evaluation: %s",
                base_sha,
            )

            if not changes:
                return EvaluationResponse(
                    score=0,
                    status="Not Met",
                    summary=(
                        "No supported source files found "
                        "in the supplied base branch."
                    ),
                    issues=[],
                    strengths=[],
                    rubric=ZERO_RUBRIC.copy(),
                )

    except Exception as e:
        logger.error(
            "Git analysis failed: %s",
            e,
        )

        return EvaluationResponse(
            score=0,
            status="Not Met",
            summary=f"Git analysis failed: {e}",
            issues=[
                f"Git error: {e}"
            ],
            strengths=[],
            rubric=ZERO_RUBRIC.copy(),
        )

    logger.info(
        "Resolved base commit: %s",
        base_sha,
    )

    logger.info(
        "Evaluation revision: %s",
        target_sha,
    )

    logger.info(
        "Step 2: %d file(s) selected for evaluation.",
        len(changes),
    )

    # ── Step 3: Read COMPLETE source + parse ────────────────
    all_fragments = []

    for change in changes:

        # Deleted-file evaluation is postponed for now.
        if change.get("change_type") == "deleted":
            continue

        file_path = (
            change.get("new_path")
            or change.get("old_path")
        )

        if not file_path:
            continue

        # Read the COMPLETE file from the selected target revision.
        #
        # Diff mode:
        #   target_sha = student's target branch
        #
        # Single-branch mode:
        #   target_sha = base_sha
        content = git_service.read_file_at_revision(
            target_sha,
            file_path,
        )

        if content is None:
            logger.warning(
                "Unable to read '%s' from revision '%s'.",
                file_path,
                target_sha,
            )
            continue

        # IMPORTANT:
        #
        # Git diff already determined that this file belongs
        # to the student's change scope.
        #
        # We now evaluate the COMPLETE target-side file so the
        # LLM can also understand unchanged methods/classes that
        # the student's new implementation depends on.
        #
        # Treating the file as "added" makes the existing parser
        # return the complete file without changing parser_service.py.
        fragments = parse_changed_code(
            file_path=file_path,
            content=content,
            change_type="added",
            added_lines=[],
            deleted_lines=[],
        )

        all_fragments.extend(
            fragments
        )

    if not all_fragments:
        return EvaluationResponse(
            score=0,
            status="Not Met",
            summary="No parseable code changes found.",
            issues=[
                "Selected files could not be parsed "
                "or contained no supported code."
            ],
            strengths=[],
            rubric=ZERO_RUBRIC.copy(),
        )

    logger.info(
        "Step 3: %d code fragment(s) extracted.",
        len(all_fragments),
    )

    # ── Step 4: Structure-aware chunking ────────────────────
    chunks = create_chunks(
        all_fragments
    )

    total_chunks = len(chunks)

    logger.info(
        "Step 4: %d chunk(s) created.",
        total_chunks,
    )

    # ── Step 5: LLM evaluation per chunk ────────────────────
    all_strengths = []
    all_issues = []
    all_evidence = []

    criteria_text = "\n".join(
        f"  {i + 1}. {criterion}"
        for i, criterion in enumerate(
            criteria_list
        )
    )

    for i, chunk in enumerate(chunks):

        logger.info(
            "Step 5: Evaluating chunk %d/%d...",
            i + 1,
            total_chunks,
        )

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

        all_strengths.extend(
            chunk_result.strengths
        )

        all_issues.extend(
            chunk_result.issues
        )

        all_evidence.extend(
            chunk_result.evidence
        )

    # ── Step 6: Consolidate findings ────────────────────────
    unique_strengths = _deduplicate(
        all_strengths
    )

    unique_issues = _deduplicate(
        all_issues
    )

    unique_evidence = _deduplicate(
        all_evidence
    )

    logger.info(
        "Step 6: Consolidated — %d issues, %d strengths.",
        len(unique_issues),
        len(unique_strengths),
    )

    # ── Step 7: Final LLM scoring ───────────────────────────
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

    # ── Step 8: Functional score ────────────────────────────
    #
    # Only requirement coverage + correctness affect
    # the final score.
    #
    # Maximum:
    # requirement_coverage = 40
    # correctness          = 25
    # total                = 65
    #
    functional_score = (
        rubric.requirement_coverage
        + rubric.correctness
    )

    final_score = round(
        (functional_score / 200) * 100
    )

    logger.info(
        "Step 8: Final score = %d, status = %s.",
        final_score,
        rubric.criteria_status,
    )

    # ── Step 9: Response ────────────────────────────────────
    return EvaluationResponse(
        score=final_score,
        status=rubric.criteria_status,
        summary=rubric.summary,
        issues=unique_issues,
        strengths=unique_strengths[:5],
        rubric={
            "requirement_coverage":
                rubric.requirement_coverage,
            "correctness":
                rubric.correctness,
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
6. If a referenced method, class, configuration, or behavior is not included
   in this chunk, DO NOT assume it is missing, incorrect, or a stub.
7. Treat missing context as insufficient evidence, not as a confirmed issue.
8. Only report an issue when the defective implementation is directly visible
   in the supplied code.
9. Do not report an acceptance criterion as missing merely because its
   implementation is not visible in this chunk. Another chunk may contain it.



**OUTPUT JSON ONLY:**
{{
  "strengths": [
    "List specific strengths DIRECTLY visible in THIS chunk"
  ],
  "issues": [
    "List specific issues DIRECTLY visible in THIS chunk"
  ],
  "evidence": [
    "Direct code quotes or references supporting your findings"
  ]
}}

**CODE CHUNK:**
{chunk}
"""

    try:
        raw = get_llm_json_response(
            prompt
        )

        return ChunkEvaluationResult(
            **raw
        )

    except ValidationError as e:
        logger.warning(
            "Chunk %d/%d Pydantic validation failed: %s",
            chunk_index,
            total_chunks,
            e,
        )

        return _extract_chunk_result_gracefully(
            raw if "raw" in dir() else {}
        )

    except Exception as e:
        logger.error(
            "Chunk %d/%d evaluation failed: %s",
            chunk_index,
            total_chunks,
            e,
        )

        return ChunkEvaluationResult(
            issues=[
                f"Chunk {chunk_index} analysis failed: {e}"
            ],
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
- requirement_coverage : 0–100
- correctness          : 0–100

**RULES:**
- Base scores ONLY on the consolidated findings above.
- DO NOT invent new implementation details, defects, or assumptions.
- When required functionality is absent from the complete evaluated submission
  scope, state that clearly rather than saying it is "not present in this chunk".
- If requirement_coverage is 0 because none of the requested functionality
  is implemented, correctness must also be 0.
- DO NOT return a total score.
- criteria_status:
    "Met" if requirement_coverage >= 30,
    "Partially Met" if requirement_coverage >= 15,
    else "Not Met".

**OUTPUT JSON ONLY. Return these fields:**
- requirement_coverage: integer from 0 to 100
- correctness: integer from 0 to 100
- criteria_status: one of "Met", "Partially Met", or "Not Met"
- summary: one concise sentence based only on the consolidated findings
"""

    try:
        raw = get_llm_json_response(
            prompt
        )

        return RubricScore(
            **raw
        )

    except ValidationError as e:
        logger.warning(
            "Final scoring Pydantic validation failed: %s",
            e,
        )

        return _extract_rubric_gracefully(
            raw if "raw" in dir() else {}
        )

    except Exception as e:
        logger.error(
            "Final scoring failed: %s",
            e,
        )

        return RubricScore(
            requirement_coverage=0,
            correctness=0,
            criteria_status="Not Met",
            summary=f"Final scoring failed: {e}",
        )


def _extract_chunk_result_gracefully(
    raw: dict,
) -> ChunkEvaluationResult:

    return ChunkEvaluationResult(
        strengths=(
            raw.get("strengths", [])
            if isinstance(
                raw.get("strengths"),
                list,
            )
            else []
        ),
        issues=(
            raw.get("issues", [])
            if isinstance(
                raw.get("issues"),
                list,
            )
            else []
        ),
        evidence=(
            raw.get("evidence", [])
            if isinstance(
                raw.get("evidence"),
                list,
            )
            else []
        ),
    )


def _extract_rubric_gracefully(
    raw: dict,
) -> RubricScore:

    def clamp(val, lo, hi):
        try:
            return max(
                lo,
                min(
                    hi,
                    int(val),
                ),
            )
        except (TypeError, ValueError):
            return lo

    return RubricScore(
        requirement_coverage=clamp(
            raw.get(
                "requirement_coverage",
                0,
            ),
            0,
            100,
        ),
        correctness=clamp(
            raw.get(
                "correctness",
                0,
            ),
            0,
            100,
        ),
        criteria_status=raw.get(
            "criteria_status",
            "Not Met",
        ),
        summary=raw.get(
            "summary",
            "Scoring completed with validation warnings.",
        ),
    )


def _deduplicate(
    items: List[str],
) -> List[str]:

    seen_word_sets = []
    unique = []

    for item in items:

        if not isinstance(
            item,
            str,
        ):
            continue

        words = set(
            re.sub(
                r"[^\w\s]",
                "",
                item.lower(),
            ).split()
        )

        if not any(
            len(words & seen) >= 3
            for seen in seen_word_sets
        ):
            unique.append(
                item
            )

            seen_word_sets.append(
                words
            )

    return unique