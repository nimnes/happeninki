import json
import time
import random
import logging
import math
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


LOG = logging.getLogger(__name__)
GOOGLE_TRANSIENT_STATUSES = {408, 429, 500, 502, 503, 504}
GOOGLE_API_STATUSES = {
    "INTERNAL", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "INVALID_ARGUMENT",
    "PERMISSION_DENIED", "UNAUTHENTICATED", "NOT_FOUND", "DEADLINE_EXCEEDED",
}


def google_retry_delay(header, detail, attempt):
    """Honor server cooldowns without logging response bodies or source text."""
    delay = 5 * (2 ** attempt) + random.uniform(0, 1)
    if isinstance(header, str):
        try:
            after = float(header)
        except ValueError:
            try:
                date = parsedate_to_datetime(header)
                if date.tzinfo is None:
                    date = date.replace(tzinfo=timezone.utc)
                after = (date - datetime.now(timezone.utc)).total_seconds()
            except (ValueError, TypeError, OverflowError):
                after = 0
        if math.isfinite(after) and after >= 0:
            delay = max(delay, after)
    error = detail.get("error", {}) if isinstance(detail, dict) else {}
    details = error.get("details", []) if isinstance(error, dict) else []
    for item in details if isinstance(details, list) else []:
        if not isinstance(item, dict) or item.get("@type") != "type.googleapis.com/google.rpc.RetryInfo":
            continue
        value = item.get("retryDelay", "")
        if isinstance(value, str) and value.endswith("s"):
            try:
                after = float(value[:-1])
            except ValueError:
                continue
            if math.isfinite(after) and after >= 0:
                delay = max(delay, after)
    return delay


class SafeRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        redirected = super().redirect_request(request, response, code, message, headers, new_url)
        if redirected and urlsplit(request.full_url).netloc != urlsplit(new_url).netloc:
            redirected.remove_header("Authorization")
            redirected.remove_header("X-goog-api-key")
        return redirected


class RemoteError(RuntimeError):
    def __init__(self, service, status=None, retry_after=None, description="", api_status=""):
        self.service = service
        self.transient = service.lower() == "google" and (status is None or status in GOOGLE_TRANSIENT_STATUSES)
        self.status = status
        self.retry_after = retry_after
        self.description = description
        label = f" ({api_status})" if isinstance(api_status, str) and api_status in GOOGLE_API_STATUSES else ""
        super().__init__((f"{service}: HTTP {status}" if status else f"{service}: network request failed") + label)


class RequestDeadlineExceeded(RuntimeError):
    """No new request was started because the run budget was exhausted."""


class HttpClient:
    def __init__(self, deadline=None):
        self.deadline = deadline

    def remaining(self):
        remaining = self.deadline - time.monotonic() if self.deadline is not None else None
        if remaining is not None and remaining <= 0:
            raise RequestDeadlineExceeded('Run budget exhausted')
        return remaining

    def retry_pause(self, delay):
        remaining = self.remaining()
        if remaining is not None and delay >= remaining:
            raise RequestDeadlineExceeded('Insufficient run budget for retry')
        time.sleep(delay)

    def request(self, url, *, method="GET", body=None, headers=None, service="Source",
                timeout=45, retry=True, raw=False):
        payload = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        request_headers = {"User-Agent": "Happeninki/1.0 (+https://github.com/nimnes/happeninki)",
                           "Accept": "application/json"}
        if body is not None:
            request_headers["Content-Type"] = "application/json"
        request_headers.update(headers or {})
        google = service.lower() == 'google'
        attempts = (4 if google else 3) if retry else 1
        request_deadline = time.monotonic() + 180 if google else None
        for attempt in range(attempts):
            remaining = self.remaining()
            if google:
                operation_remaining = request_deadline - time.monotonic()
                if operation_remaining <= 0:
                    raise RemoteError(service)
                remaining = min(remaining, operation_remaining) if remaining is not None else operation_remaining
            request_timeout = min(timeout, remaining) if remaining is not None else timeout
            if google:
                request_timeout = min(request_timeout, 40)
            try:
                request = Request(url, data=payload, headers=request_headers, method=method)
                with build_opener(SafeRedirects()).open(request, timeout=request_timeout) as response:
                    data = response.read()
                return data if raw else json.loads(data) if data else None
            except HTTPError as exc:
                # Never include request URLs: Telegram embeds its secret in the URL.
                after = exc.headers.get("Retry-After")
                after = int(after) if after and after.isdigit() else None
                description = ""
                detail = {}
                try:
                    detail = json.loads(exc.read())
                    if isinstance(detail, dict):
                        description = str(detail.get("description", ""))
                        if isinstance(detail.get("parameters"), dict):
                            after = detail["parameters"].get("retry_after", after)
                except (ValueError, OSError):
                    pass
                if google:
                    error_info = detail.get("error", {}) if isinstance(detail, dict) else {}
                    api_status = error_info.get("status", "") if isinstance(error_info, dict) else ""
                    error = RemoteError(service, exc.code, api_status=api_status)
                    if not retry or exc.code not in GOOGLE_TRANSIENT_STATUSES or attempt == attempts - 1:
                        raise error from None
                    delay = google_retry_delay(exc.headers.get("Retry-After"), detail, attempt)
                    if delay > 60 or time.monotonic() + delay + 1 >= request_deadline:
                        raise error from None
                    LOG.warning("%s; retry %d/%d in %.1fs", error, attempt + 1, attempts - 1, delay)
                    self.retry_pause(delay)
                    continue
                error = RemoteError(service, exc.code, after, description)
                if not retry or exc.code not in {429, 500, 502, 503, 504} or attempt == attempts - 1:
                    raise error from None
                if after and after > 30:
                    raise error from None
                self.retry_pause(after or 2 ** attempt)
            except (URLError, TimeoutError, OSError):
                if attempt == attempts - 1:
                    raise RemoteError(service) from None
                if google:
                    delay = 5 * (2 ** attempt) + random.uniform(0, 1)
                    if time.monotonic() + delay + 1 >= request_deadline:
                        raise RemoteError(service) from None
                    LOG.warning("%s: network request failed; retry %d/%d in %.1fs",
                                service, attempt + 1, attempts - 1, delay)
                    self.retry_pause(delay)
                else:
                    self.retry_pause(2 ** attempt)
            except (json.JSONDecodeError, UnicodeDecodeError):
                raise RuntimeError(f"{service}: invalid JSON response") from None
