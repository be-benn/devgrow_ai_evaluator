from rest_framework import serializers


class EvaluationRequestSerializer(serializers.Serializer):
    """DRF serializer for the evaluation API request."""

    project_title = serializers.CharField()
    project_description = serializers.CharField()
    task_title = serializers.CharField()
    task_description = serializers.CharField()
    acceptance_criteria = serializers.CharField()
    repository_path = serializers.CharField()
    base_commit = serializers.CharField()
    target_commit = serializers.CharField()
    branch = serializers.CharField(required=False, allow_blank=True)
    difficulty = serializers.CharField(required=False, default="MEDIUM")


class RubricSerializer(serializers.Serializer):
    """Nested rubric scores."""

    requirement_coverage = serializers.IntegerField()
    correctness = serializers.IntegerField()
    code_quality = serializers.IntegerField()
    best_practices = serializers.IntegerField()


class EvaluationResponseSerializer(serializers.Serializer):
    """DRF serializer for the evaluation API response (V1-compatible)."""

    score = serializers.IntegerField()
    status = serializers.CharField()
    summary = serializers.CharField()
    issues = serializers.ListField(child=serializers.CharField())
    strengths = serializers.ListField(child=serializers.CharField())
    rubric = RubricSerializer()
