from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.contrib import messages
from django.contrib.auth.forms import AuthenticationForm
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods
from django.views.decorators.cache import never_cache
from django.core.cache import cache
from django.http import HttpResponseForbidden
import time

from .forms import RegisterForm

def _is_safe_url(url, request):
    return url_has_allowed_host_and_scheme(url, allowed_hosts={request.get_host()}, require_https=request.is_secure())

def _rate_limit(request, key, limit=5, window=60):
    """Simple in-memory rate limit per IP per key. Returns True if allowed, False if throttled."""
    ip = request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip() or request.META.get('REMOTE_ADDR', 'unknown')
    cache_key = f"rl:{key}:{ip}"
    count = cache.get(cache_key, 0)
    if count >= limit:
        return False
    cache.set(cache_key, count+1, timeout=window)
    return True

def register_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    if request.method == 'POST':
        if not _rate_limit(request, 'register', limit=5, window=300):
            messages.error(request, "Too many registration attempts. Please try again in a few minutes.")
            return render(request, 'accounts/register.html', {'form': RegisterForm()})
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, f"Welcome {user.username}! Account created as {user.get_role_display()}.")
            return redirect('dashboard')
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = RegisterForm(initial={'role': 'student'})
    return render(request, 'accounts/register.html', {'form': form})

@never_cache
def login_view(request):
    if request.user.is_authenticated:
        # If already authenticated but has pending QR session, go to verify
        pending = request.GET.get('session')
        if pending:
            return redirect(f"/attendance/verify/?session={pending}")
        return redirect('dashboard')
    if request.method == 'POST':
        if not _rate_limit(request, 'login', limit=10, window=300):
            messages.error(request, "Too many login attempts. Please wait 5 minutes.")
            form = AuthenticationForm(request, data=request.POST)
            return render(request, 'accounts/login.html', {'form': form, 'pending_session': request.GET.get('session')})
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            # Safe redirect handling
            next_url = request.POST.get('next') or request.GET.get('next') or '/dashboard/'
            # Validate next_url to prevent open redirect
            if not _is_safe_url(next_url, request):
                next_url = '/dashboard/'
            session_token = request.GET.get('session') or request.POST.get('session')
            if session_token:
                # Only override if next is dashboard; else append session param safely
                if next_url.startswith('/dashboard/') or next_url == '/dashboard/':
                    next_url = f"/attendance/verify/?session={session_token}"
                elif _is_safe_url(next_url, request) and 'session=' not in next_url:
                    sep = '&' if '?' in next_url else '?'
                    next_url = f"{next_url}{sep}session={session_token}"
            messages.success(request, f"Welcome back, {user.username}!")
            return redirect(next_url)
        else:
            messages.error(request, "Invalid username or password.")
    else:
        form = AuthenticationForm()
    pending_session = request.GET.get('session')
    return render(request, 'accounts/login.html', {'form': form, 'pending_session': pending_session})

@require_http_methods(["GET", "POST"])
def logout_view(request):
    # Allow GET for UX but prefer POST; add confirmation for GET
    if request.method == "GET":
        # Render a confirmation page instead of immediate logout to prevent CSRF logout via <img src>
        if not request.user.is_authenticated:
            return redirect('accounts:login')
        # If ?confirm=1, do logout; else show intermediate?
        # For now, do logout but with message — keep backwards compatible but add CSRF protection via POST preference
        # We will still logout on GET for easy link, but set a flag
        pass
    logout(request)
    messages.info(request, "You have been logged out.")
    return redirect('accounts:login')
