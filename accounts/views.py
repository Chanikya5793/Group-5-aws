from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie


def _safe_next_url(request):
    """Return a safe local redirect target from ?next=... or POSTed next."""
    next_url = (request.POST.get('next') or request.GET.get('next') or '').strip()
    if not next_url:
        return ''

    if url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    return ''


@never_cache
@ensure_csrf_cookie
@csrf_protect
def login_view(request):
    User = get_user_model()
    next_url = _safe_next_url(request)

    if request.user.is_authenticated:
        return redirect(next_url or 'dashboard')

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            return redirect(next_url or 'dashboard')
        else:
            messages.error(request, 'Invalid username or password.')

    real_login_available = User.objects.filter(username='de0e9b2c').exists()
    return render(request, 'accounts/login.html', {
        'next': next_url,
        'real_login_available': real_login_available,
    })


def logout_view(request):
    logout(request)
    return redirect('login')
