from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.core import signing
from django.conf import settings
import time
from urllib.parse import quote

# Lightweight human verification: returns a small JS page that posts to /__human_verify/
# On success the server sets a signed cookie 'human_verified' (httponly) valid for 24h.

def human_challenge(request):
    next_url = request.GET.get('next', request.get_full_path())
    # Keep the next_url safe to include in JS (percent-encode)
    encoded_next = quote(next_url, safe='')
    html = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Human verification required</title>
</head>
<body>
  <h2>Human verification required</h2>
  <p>We have detected unusual automated requests from your network. Please prove you are human to continue.</p>
  <button id="verify">I'm human</button>
  <p id="status"></p>
  <script>
    document.getElementById('verify').addEventListener('click', function() {
      fetch('/__human_verify/?next=' + '{encoded_next}', { method: 'POST', credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' }})
        .then(function(r) { return r.json(); })
        .then(function(j) {
          if (j && j.status === 'ok') {
            window.location = decodeURIComponent('{encoded_next}');
          } else {
            document.getElementById('status').innerText = j && j.error ? j.error : 'Verification failed.';
          }
        })
        .catch(function(e) { document.getElementById('status').innerText = 'Network error'; });
    });
  </script>
</body>
</html>
""".replace('{encoded_next}', encoded_next)
    return HttpResponse(html, content_type='text/html')


@csrf_exempt
def human_verify(request):
    # Simple verification endpoint that sets a signed cookie when called via POST
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    next_url = request.GET.get('next', '/')
    # Create signed token with timestamp
    token = signing.dumps({'ts': int(time.time())})
    resp = JsonResponse({'status': 'ok', 'next': next_url})
    secure_flag = not settings.DEBUG
    resp.set_cookie('human_verified', token, max_age=24 * 3600, httponly=True, secure=secure_flag, samesite='Lax')
    return resp
