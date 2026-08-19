import logging

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from evaluator.schemas import EvaluationRequest
from evaluator.serializers import (
    EvaluationRequestSerializer,
    EvaluationResponseSerializer,
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
