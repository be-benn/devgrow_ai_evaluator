from django.urls import path

from evaluator.views import evaluate_code, update_scoring_metrics

urlpatterns = [
    path("evaluate/", evaluate_code, name="evaluate_code"),
    path("scoring-metrics/", update_scoring_metrics, name="scoring_metrics"),
]
