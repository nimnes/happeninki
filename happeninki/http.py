import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class SafeRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        redirected = super().redirect_request(request, response, code, message, headers, new_url)
        if redirected and urlsplit(request.full_url).netloc != urlsplit(new_url).netloc:
            redirected.remove_header("Authorization")
        return redirected


class RemoteError(RuntimeError):
    def __init__(self, service, status=None, retry_after=None, description=""):
        self.status = status
        self.retry_after = retry_after
        self.description = description
        super().__init__(f"{service}: HTTP {status}" if status else f"{service}: network request failed")


class HttpClient:
    def request(self, url, *, method="GET", body=None, headers=None, service="Source",
                timeout=45, retry=True, raw=False):
        payload = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        request_headers = {"User-Agent": "Happeninki/1.0 (+https://github.com/nimnes/happeninki)",
                           "Accept": "application/json"}
        if body is not None:
            request_headers["Content-Type"] = "application/json"
        request_headers.update(headers or {})
        attempts = 3 if retry else 1
        for attempt in range(attempts):
            try:
                request = Request(url, data=payload, headers=request_headers, method=method)
                with build_opener(SafeRedirects()).open(request, timeout=timeout) as response:
                    data = response.read()
                return data if raw else json.loads(data) if data else None
            except HTTPError as exc:
                # Never include request URLs: Telegram embeds its secret in the URL.
                after = exc.headers.get("Retry-After")
                after = int(after) if after and after.isdigit() else None
                description = ""
                try:
                    detail = json.loads(exc.read())
                    if isinstance(detail, dict):
                        description = str(detail.get("description", ""))
                        if isinstance(detail.get("parameters"), dict):
                            after = detail["parameters"].get("retry_after", after)
                except (ValueError, OSError):
                    pass
                error = RemoteError(service, exc.code, after, description)
                if not retry or exc.code not in {429, 500, 502, 503, 504} or attempt == attempts - 1:
                    raise error from None
                if after and after > 30:
                    raise error from None
                time.sleep(after or 2 ** attempt)
            except (URLError, TimeoutError, OSError):
                if attempt == attempts - 1:
                    raise RemoteError(service) from None
                time.sleep(2 ** attempt)
            except (json.JSONDecodeError, UnicodeDecodeError):
                raise RuntimeError(f"{service}: invalid JSON response") from None
