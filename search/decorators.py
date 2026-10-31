from functools import wraps

from django.http import JsonResponse


def staff_json(view):
    """Like user_passes_test(is_staff) but answers with JSON 403 instead of a login redirect."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        user = request.user
        if not (user.is_authenticated and user.is_staff):
            return JsonResponse({'error': 'Staff login required.'}, status=403)
        return view(request, *args, **kwargs)
    return wrapper
