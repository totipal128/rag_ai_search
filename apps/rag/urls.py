from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.rag.views import AIModelViewSet, AskReportView

router = DefaultRouter()
router.register('ai-models', AIModelViewSet, basename='ai-model')

urlpatterns = [
    path('rag/ask/', AskReportView.as_view(), name='rag-ask'),
    path('', include(router.urls)),
]
