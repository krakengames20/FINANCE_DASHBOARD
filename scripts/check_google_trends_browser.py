"""Opt-in real-browser check against local fixture data; never contacts Google.

python scripts/check_google_trends_browser.py
Requires installed Chrome, Edge, or Playwright Chromium.
"""
import json
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.data import google_trends as gt
from src.data import google_trends_browser as b

current = {'status': 200, 'hits': 0}
data = {'default': {'timelineData': [
    {'time': '1791244800', 'value': [50, 10, 5]},
    {'time': '1791331200', 'value': [100, 20, 10], 'isPartial': True},
]}}

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass
    def do_GET(self):
        status, body, content_type = 200, b'<html><body>Local test</body></html>', 'text/html'
        if self.path.startswith('/trends/explore?'):
            body = b'''<html><body><script>
fetch('/trends/api/widgetdata/relatedsearches').catch(()=>{});
fetch('/trends/api/widgetdata/multiline').then(()=>fetch('/trends/api/widgetdata/multiline')).catch(()=>{});
</script></body></html>'''
        elif self.path.startswith('/trends/api/widgetdata/'):
            current['hits'] += 1
            status = current['status']
            body = (")]}'\n" + json.dumps(data)).encode()
            content_type = 'application/json'
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.end_headers()
        self.wfile.write(body)

server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
gt.BASE_URL = f'http://127.0.0.1:{server.server_port}/trends'
try:
    Path('.cache').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir='.cache') as directory:
        b.BROWSER_DIR = Path(directory) / 'browser'
        b.MIN_INTERVAL = 0
        for window in gt.WINDOWS:
            with b.request_lock():
                result = b.BrowserTrendsClient().fetch(gt.build_query('ChatGPT,Claude,Gemini', window))
            assert result.values.iloc[1].tolist() == [100, 20, 10]
            assert result.partial.tolist() == [False, True]
            print('PASS real browser JSON capture:', window, flush=True)
        assert current['hits'] == 3, current
        current['status'] = 429
        for _ in range(2):
            with b.request_lock():
                try:
                    b.BrowserTrendsClient().fetch(gt.build_query('ChatGPT,Claude,Gemini', '1 year'))
                except gt.TrendsRateLimitError:
                    pass
                else:
                    raise AssertionError('429 was not handled')
        assert current['hits'] == 4, current
        print('PASS one timeline per fetch, suppressed related requests/retries, shared 429 cooldown', flush=True)
finally:
    server.shutdown()
    server.server_close()
