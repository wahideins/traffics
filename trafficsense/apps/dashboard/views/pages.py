"""View halaman penuh."""
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.views.decorators.http import require_GET
from django.contrib import messages

from ..services.constants import REFRESH_INTERVAL_MS
from ..services.context import build_dashboard_context
from ..services.params import parse_params


def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard:index')  # Tambahkan namespace 'dashboard:'

    if request.method == 'POST':
        username_input = request.POST.get('username')
        password_input = request.POST.get('password')
        
        user = authenticate(request, username=username_input, password=password_input)
        if user is not None:
            login(request, user)
            next_url = request.GET.get('next')
            if next_url:
                return redirect(next_url)
            return redirect('dashboard:index')  # Tambahkan namespace 'dashboard:'
        else:
            messages.error(request, 'Username atau password salah.')

    return render(request, 'dashboard/login.html')


def logout_view(request):
    logout(request)
    return redirect('login')


@login_required(login_url='login')
def index(request):
    params = parse_params(request.GET)
    context = build_dashboard_context(params, now=timezone.localtime())
    context["refresh_ms"] = REFRESH_INTERVAL_MS
    return render(request, "dashboard/index.html", context)