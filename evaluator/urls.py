from django.urls import path

from evaluator.views import evaluate_code

urlpatterns = [
    path("evaluate/", evaluate_code, name="evaluate_code"),
]
