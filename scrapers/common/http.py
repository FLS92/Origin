import json
import subprocess
import time

import requests

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"


def session():
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "fr-FR,fr;q=0.9"})
    return s


class _CurlResponse:
    """Minimal requests.Response shim, used when the local Python's OpenSSL/LibreSSL
    is too old to negotiate TLS with a given host (seen on this dev machine — its
    system Python links LibreSSL 2.8.3, while curl uses macOS SecureTransport and
    just works). Not needed on a normal CI runner with a modern Python, but keeps
    this scraper runnable everywhere without silently skipping sites."""

    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


def _curl_get(url, headers=None, timeout=20):
    cmd = ["curl", "-sL", "--compressed", "-A", USER_AGENT, "--max-time", str(timeout),
           "-w", "\n__HTTP_STATUS__%{http_code}"]
    for k, v in (headers or {}).items():
        cmd += ["-H", f"{k}: {v}"]
    cmd.append(url)
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
    body, _, status = out.stdout.rpartition("__HTTP_STATUS__")
    status_code = int(status.strip() or 0)
    return _CurlResponse(status_code, body)


def get(session_, url, **kwargs):
    kwargs.setdefault("timeout", 20)
    last_exc = None
    for attempt in range(3):
        try:
            resp = session_.get(url, **kwargs)
            if resp.status_code == 429:
                time.sleep(2 * (attempt + 1))
                continue
            return resp
        except requests.exceptions.SSLError:
            return _curl_get(url, headers=dict(session_.headers), timeout=kwargs["timeout"])
        except requests.RequestException as exc:
            last_exc = exc
            time.sleep(1.5 * (attempt + 1))
    raise last_exc


def decode_json_body(resp):
    """Parse a response body as JSON, tolerant of a leading UTF-8 BOM (some
    WooCommerce/PHP stacks emit one, which trips up resp.json())."""
    raw = resp.content if hasattr(resp, "content") else resp.text.encode("utf-8")
    return json.loads(raw.decode("utf-8-sig"))
