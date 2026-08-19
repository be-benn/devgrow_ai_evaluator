from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


# ── Chunk-level LLM response ────────────────────────────────
class ChunkEvaluationResult(BaseModel):
    """Validates per-chunk LLM output (V1-style findings, no scores)."""

    strengths: List[str] = Field(default_factory=list)
    issues: List[str] = Field(default_factory=list)
    evidence: List[str] = Field(default_factory=list)


# ── Final rubric score ──────────────────────────────────────
class RubricScore(BaseModel):
    """Validates the final scoring LLM response."""

    requirement_coverage: int = Field(ge=0, le=40)
    correctness: int = Field(ge=0, le=25)
    code_quality: int = Field(ge=0, le=20)
    best_practices: int = Field(ge=0, le=15)
    criteria_status: str
    summary: str

    @field_validator("criteria_status")
    @classmethod
    def validate_criteria_status(cls, v: str) -> str:
        allowed = {"Met", "Partially Met", "Not Met"}
        return v if v in allowed else "Not Met"


# ── Parsed code fragment ────────────────────────────────────
class ParsedCodeFragment(BaseModel):
    """One structural unit of changed code extracted via tree-sitter."""

    filename: str
    node_name: str = ""
    node_type: str = ""
    source_code: str
    start_line: int = 0
    end_line: int = 0
    context: str = ""  # e.g. "class MyClass > method do_thing"


# ── API request ─────────────────────────────────────────────
class EvaluationRequest(BaseModel):
    """Incoming evaluation request payload."""

    project_title: str
    project_description: str
    task_title: str
    task_description: str
    acceptance_criteria: str  # raw text, normalized into list by the service
    repository_path: str
    base_commit: str
    target_commit: str
    branch: Optional[str] = None
    difficulty: str = "MEDIUM"


# ── API response (V1-compatible) ────────────────────────────
class EvaluationResponse(BaseModel):
    """Final evaluation output, preserving V1 contract."""

    score: int
    status: str
    summary: str
    issues: List[str] = Field(default_factory=list)
    strengths: List[str] = Field(default_factory=list)
    rubric: dict = Field(default_factory=dict)
