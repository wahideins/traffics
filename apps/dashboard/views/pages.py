"""View halaman penuh."""
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from ..services.constants import REFRESH_INTERVAL_MS
from ..services.context import build_dashboard_context
from ..services.params import parse_params


@require_GET
def index(request):
    params = parse_params(request.GET)
    context = build_dashboard_context(params, now=timezone.localtime())
    context["refresh_ms"] = REFRESH_INTERVAL_MS
    return render(request, "dashboard/index.html", context)
