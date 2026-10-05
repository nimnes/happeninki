import hashlib
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .http import RemoteError
from .store import validate_database

SNAPSHOT_PATTERN = re.compile(r"events-\d{8}T\d{12}Z-[a-f0-9]{8}\.db$")


class ReleaseState:
    """Immutable SQLite snapshots; a new upload never deletes the active snapshot."""
    tag = "events-db"

    def __init__(self, http, token, repository):
        if not token or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository or ""):
            raise ValueError("Release storage requires GITHUB_TOKEN and GITHUB_REPOSITORY")
        self.http = http
        self.headers = {"Authorization": f"Bearer {token}", "X-GitHub-Api-Version": "2022-11-28"}
        self.base = f"https://api.github.com/repos/{repository}"
        self.release = None
        self.last_hash = None

    def api(self, url, **kwargs):
        return self.http.request(url, headers=self.headers, service="GitHub state", **kwargs)

    def find_release(self):
        try:
            return self.api(f"{self.base}/releases/tags/{self.tag}")
        except RemoteError as exc:
            if exc.status == 404:
                return None
            raise

    def assets(self):
        result, page = [], 1
        while True:
            batch = self.api(f"{self.base}/releases/{self.release['id']}/assets?per_page=100&page={page}")
            result.extend(batch)
            if len(batch) < 100:
                return result
            page += 1

    def restore(self, path, initialize=False):
        self.release = self.find_release()
        if self.release is None:
            if not initialize:
                raise RuntimeError("State release is missing. Use an explicit first-launch initialization; do not silently reset history.")
            if Path(path).exists():
                raise RuntimeError("Refusing to initialize over an existing local database")
            return
        snapshots = sorted((a for a in self.assets() if SNAPSHOT_PATTERN.fullmatch(a["name"])), key=lambda a: a["name"])
        if not snapshots:
            if initialize and not Path(path).exists():
                return
            raise RuntimeError("State release contains no snapshots; refusing to reset history")
        latest = snapshots[-1]
        # JSON/base64 via the release asset URL isn't supported; octet-stream is.
        headers = {**self.headers, "Accept": "application/octet-stream"}
        content = self.http.request(latest["url"], headers=headers, service="GitHub state download", raw=True)
        expected = latest.get("digest")
        if expected and expected != "sha256:" + hashlib.sha256(content).hexdigest():
            raise RuntimeError("State snapshot checksum mismatch")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".restore")
        try:
            temporary.write_bytes(content)
            validate_database(temporary)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        self.last_hash = hashlib.sha256(content).hexdigest()

    def checkpoint(self, store):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / "events.db"
            store.snapshot(snapshot)
            validate_database(snapshot)
            content = snapshot.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if digest == self.last_hash:
            return
        if self.release is None:
            self.release = self.api(f"{self.base}/releases", method="POST", body={
                "tag_name": self.tag, "name": "Persistent event history", "make_latest": "false",
                "body": "Automatically managed SQLite snapshots for Happeninki. Contains public event data and publication history; no API credentials."
            }, retry=False)
        name = "events-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid.uuid4().hex[:8] + ".db"
        upload_url = self.release["upload_url"].split("{")[0] + "?name=" + name
        asset = self.http.request(upload_url, method="POST", body=content,
                                  headers={**self.headers, "Content-Type": "application/octet-stream"},
                                  service="GitHub state upload", retry=False)
        if asset.get("state") != "uploaded" or asset.get("size") != len(content):
            raise RuntimeError("GitHub did not confirm the state snapshot upload")
        self.last_hash = digest

    def prune(self, keep=3):
        if not self.release:
            return
        snapshots = sorted((a for a in self.assets() if SNAPSHOT_PATTERN.fullmatch(a["name"])), key=lambda a: a["name"])
        for asset in snapshots[:-keep]:
            self.api(f"{self.base}/releases/assets/{asset['id']}", method="DELETE")
