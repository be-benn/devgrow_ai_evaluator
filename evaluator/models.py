from django.db import models


class EvaluationResult(models.Model):
    """Stores a completed evaluation result, keyed by commit + task."""

    repository_path = models.TextField()
    base_commit = models.CharField(max_length=64)
    target_commit = models.CharField(max_length=64)
    task_title = models.CharField(max_length=512)

    score = models.IntegerField()
    status = models.CharField(max_length=20)
    summary = models.TextField()
    issues = models.JSONField(default=list)
    strengths = models.JSONField(default=list)
    rubric = models.JSONField(default=dict)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "repository_path",
                    "base_commit",
                    "target_commit",
                    "task_title",
                ],
                name="unique_evaluation_per_commit_task",
            ),
        ]

    def __str__(self):
        return (
            f"EvaluationResult("
            f"task={self.task_title!r}, "
            f"score={self.score}, "
            f"target={self.target_commit[:8]})"
        )

    @classmethod
    def get_cached(cls, repository_path, base_commit, target_commit, task_title):
        """Return the cached result or None."""
        try:
            return cls.objects.get(
                repository_path=repository_path,
                base_commit=base_commit,
                target_commit=target_commit,
                task_title=task_title,
            )
        except cls.DoesNotExist:
            return None


class ScoringMetric(models.Model):
    """
    Additional scoring metrics beyond the hardcoded defaults
    (requirement_coverage, correctness).
    """

    name = models.CharField(max_length=100, unique=True)
    display_name = models.CharField(max_length=100)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.display_name

    @classmethod
    def get_extra_metrics(cls):
        """Return additional (non-default) metrics, capped at 3."""
        return list(cls.objects.all()[:3])
