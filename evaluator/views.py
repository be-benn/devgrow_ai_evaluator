import logging

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from evaluator.models import ScoringMetric
from evaluator.schemas import EvaluationRequest
from evaluator.serializers import (
    EvaluationRequestSerializer,
    EvaluationResponseSerializer,
    ScoringMetricSerializer,
)
from evaluator.services.evaluation_service import evaluate

logger = logging.getLogger(__name__)


@api_view(["POST"])
def evaluate_code(request):
    """
    POST /api/evaluate/

    Accepts project + task context, acceptance criteria, and git commit info.
    Returns a V1-compatible evaluation with score, status, issues, strengths,
    and rubric breakdown.
    """
    serializer = EvaluationRequestSerializer(data=request.data)

    if not serializer.is_valid():
        return Response(
            {"error": "Invalid request.", "details": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        eval_request = EvaluationRequest(**serializer.validated_data)
    except Exception as e:
        return Response(
            {"error": f"Request validation failed: {e}"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        result = evaluate(eval_request)
    except Exception as e:
        logger.exception("Evaluation pipeline failed.")
        return Response(
            {"error": f"Evaluation failed: {e}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    response_serializer = EvaluationResponseSerializer(result.model_dump())
    return Response(response_serializer.data, status=status.HTTP_200_OK)


@api_view(["POST"])
def update_scoring_metrics(request):
    """
    POST /api/scoring-metrics/

    Manages additional scoring metrics beyond the defaults
    (requirement_coverage, correctness are always present).

    Maximum 3 additional metrics accepted (5 total with defaults).

    Request body:
        {"metrics": [{"name": "...", "display_name": "..."}, ...]}

    Returns all active metrics (defaults + additional).
    """
    metrics_data = request.data.get("metrics")

    if not isinstance(metrics_data, list) or not metrics_data:
        return Response(
            {"error": "A non-empty 'metrics' list is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Reject attempts to override hardcoded defaults
    reserved = {"requirement_coverage", "correctness"}
    metrics_data = [
        m for m in metrics_data
        if m.get("name") not in reserved
    ]

    truncated = len(metrics_data) > 3
    metrics_data = metrics_data[:3]

    serializer = ScoringMetricSerializer(data=metrics_data, many=True)

    if not serializer.is_valid():
        return Response(
            {"error": "Invalid metrics.", "details": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Replace additional metrics atomically
    ScoringMetric.objects.all().delete()
    ScoringMetric.objects.bulk_create([
        ScoringMetric(**item) for item in serializer.validated_data
    ])

    # Build full response: defaults + extras
    defaults = [
        {"name": "requirement_coverage", "display_name": "Requirement Coverage"},
        {"name": "correctness", "display_name": "Code Correctness"},
    ]
    extras = [
        {"name": m.name, "display_name": m.display_name}
        for m in ScoringMetric.get_extra_metrics()
    ]

    response_data = {
        "metrics": ScoringMetricSerializer(
            defaults + extras, many=True
        ).data,
    }

    if truncated:
        response_data["warning"] = (
            "Maximum 3 additional metrics allowed (5 total). "
            "Only the first 3 were saved."
        )

    return Response(response_data, status=status.HTTP_200_OK)
