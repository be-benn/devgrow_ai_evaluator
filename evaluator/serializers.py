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
    target_commit = serializers.CharField(allow_blank=True)
    branch = serializers.CharField(required=False, allow_blank=True)
    difficulty = serializers.CharField(required=False, default="MEDIUM")


class EvaluationResponseSerializer(serializers.Serializer):
    """DRF serializer for the evaluation API response."""

    score = serializers.IntegerField()
    status = serializers.CharField()
    summary = serializers.CharField()
    issues = serializers.ListField(child=serializers.CharField())
    strengths = serializers.ListField(child=serializers.CharField())
    rubric = serializers.DictField()


class ScoringMetricSerializer(serializers.Serializer):
    """Serializer for a single scoring metric."""

    name = serializers.CharField(max_length=100)
    display_name = serializers.CharField(max_length=100)
