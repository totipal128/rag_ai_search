from rest_framework.permissions import AllowAny
from rest_framework.viewsets import ModelViewSet

from apps.report.models import Report
from apps.report.pagination import ReportPagination
from apps.report.serializers import ReportSerializer


class ReportViewSet(ModelViewSet):
    queryset = Report.objects.all().order_by('-id')
    serializer_class = ReportSerializer
    permission_classes = [AllowAny]
    authentication_classes = []
    pagination_class = ReportPagination
