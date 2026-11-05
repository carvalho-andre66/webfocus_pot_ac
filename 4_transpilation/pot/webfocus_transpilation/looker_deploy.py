"""Upload a local LookML tree to a Looker project through the API.

Looker keeps the written files on the dev branch of the user that owns the API
credentials. There is no commit call in this module: the caller opens the
project in Development Mode as that user.

The file writes follow the request the Looker IDE and looker-cli use:
POST or PUT /api/4.0/projects/{project_id}/files with JSON fields 'path' and
'content'. Those routes are not in the published API reference.
"""

from __future__ import annotations

import json
import os
import posixpath
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

DEFAULT_PROJECT_ID = "webfocus_pot"
API_PREFIX = "/api/4.0"
REQUEST_TIMEOUT_SECONDS = 120
_PROJECT_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,127}$")
_FOLDER_TYPES = frozenset({"folder"})


class LookerConfigError(Exception):
    """Credentials or a project id are missing or not usable."""


class LookerApiError(Exception):
    """A Looker HTTP call returned an error status or could not be completed."""

    def __init__(self, status: int, method: str, path: str, body: str) -> None:
        """Record the status and a short body excerpt. 'path' is the API path, not a secret."""
        self.status = status
        self.detail = " ".join(body.split())[:500]
        super().__init__(f"Looker {method} {path} returned {status}: {self.detail}")


def _already_exists(error: LookerApiError) -> bool:
    """True when Looker refused a create because the file is already there.

    This instance answers 400 with 'File already exists'. Other deployments answer 409.
    """
    if error.status == 409:
        return True
    return error.status == 400 and "already exists" in error.detail.lower()


@dataclass(frozen=True)
class LookerCredentials:
    """API3 credentials for one Looker instance."""

    base_url: str
    client_id: str
    client_secret: str
    verify_ssl: bool


@dataclass(frozen=True)
class DeployResult:
    """What one upload did, plus the IDE link to print."""

    project_id: str
    project_created: bool
    created: tuple[str, ...]
    updated: tuple[str, ...]
    user_label: str
    project_url: str


@dataclass(frozen=True)
class HttpResult:
    """Status and raw body from one HTTP call."""

    status: int
    body: bytes


class Transport(Protocol):
    """Sends one HTTP request and returns the status and body, including error statuses."""

    def send(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResult:
        """Perform the request. Raise LookerApiError only when no HTTP response arrives."""


class UrllibTransport:
    """Transport backed by urllib. HTTP error statuses come back as HttpResult."""

    def __init__(self, verify_ssl: bool) -> None:
        """Store whether TLS certificates should be checked."""
        self._verify_ssl = verify_ssl

    def send(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResult:
        """Send the request. A refused connection or TLS failure raises LookerApiError."""
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        context = None if self._verify_ssl else ssl._create_unverified_context()
        try:
            with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                return HttpResult(response.status, response.read())
        except urllib.error.HTTPError as exc:
            return HttpResult(exc.code, exc.read())
        except urllib.error.URLError as exc:
            raise LookerApiError(0, method, url, str(exc.reason)) from exc


def credentials_from_env(environ: Mapping[str, str] | None = None) -> LookerCredentials:
    """Read LOOKERSDK_BASE_URL, LOOKERSDK_CLIENT_ID, and LOOKERSDK_CLIENT_SECRET.

    LOOKERSDK_VERIFY_SSL defaults to true. Any other value than 'false' keeps verification on.
    """
    source = os.environ if environ is None else environ
    base_url = source.get("LOOKERSDK_BASE_URL", "").strip().rstrip("/")
    client_id = source.get("LOOKERSDK_CLIENT_ID", "").strip()
    client_secret = source.get("LOOKERSDK_CLIENT_SECRET", "").strip()
    missing = [
        name
        for name, value in (
            ("LOOKERSDK_BASE_URL", base_url),
            ("LOOKERSDK_CLIENT_ID", client_id),
            ("LOOKERSDK_CLIENT_SECRET", client_secret),
        )
        if not value
    ]
    if missing:
        raise LookerConfigError(
            "Missing " + ", ".join(missing) + ". Set them in .env (see .env.example)."
        )
    if not base_url.startswith(("https://", "http://")):
        raise LookerConfigError("LOOKERSDK_BASE_URL must start with https:// or http://.")
    verify_ssl = source.get("LOOKERSDK_VERIFY_SSL", "true").strip().lower() != "false"
    return LookerCredentials(base_url, client_id, client_secret, verify_ssl)


def check_project_id(project_id: str) -> str:
    """Return the project id, or raise LookerConfigError when it is not a Looker project id."""
    if not _PROJECT_ID.fullmatch(project_id):
        raise LookerConfigError(
            "Project id must start with a letter and contain only letters, digits, '_' and '-'."
        )
    return project_id


def project_id_from_env(environ: Mapping[str, str] | None = None) -> str:
    """Read 'LOOKER_PROJECT_ID' or 'LOOKERSDK_PROJECT_ID' from env, falling back to 'webfocus_pot'."""
    source = os.environ if environ is None else environ
    configured = source.get("LOOKER_PROJECT_ID") or source.get("LOOKERSDK_PROJECT_ID") or ""
    configured = configured.strip()
    return check_project_id(configured) if configured else DEFAULT_PROJECT_ID


def project_files_url(base_url: str, project_id: str) -> str:
    """IDE link for the project file browser. Strips a trailing /api/4.0 from the base URL."""
    root = base_url.rstrip("/")
    for suffix in ("/api/4.0", "/api"):
        if root.endswith(suffix):
            root = root[: -len(suffix)]
            break
    return f"{root}/projects/{project_id}/files"


def collect_lookml(directory: Path) -> dict[str, str]:
    """Read every .lkml file under 'directory'. Keys are relative paths with '/' separators.

    Dotfiles are skipped. Raises FileNotFoundError when the directory is missing or has no
    .lkml files.
    """
    if not directory.is_dir():
        raise FileNotFoundError(f"LookML directory not found: {directory}")
    files: dict[str, str] = {}
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.name.startswith(".") or path.suffix != ".lkml":
            continue
        files[path.relative_to(directory).as_posix()] = path.read_text(encoding="utf-8")
    if not files:
        raise FileNotFoundError(f"No .lkml files in {directory}")
    return files


def parent_directories(paths: Mapping[str, str] | list[str]) -> list[str]:
    """Unique parent directories of the paths, shallowest first."""
    found: set[str] = set()
    for path in paths:
        parent = posixpath.dirname(path)
        while parent and parent != ".":
            found.add(parent)
            parent = posixpath.dirname(parent)
    return sorted(found, key=lambda item: (item.count("/"), item))


def user_label(payload: Mapping[str, object]) -> str:
    """A short label from a Looker /user payload."""
    name = str(payload.get("display_name") or "").strip()
    email = str(payload.get("email") or "").strip()
    if name and email:
        return f"{name} ({email})"
    return name or email or "the user that owns the API credentials"


class LookerClient:
    """Authenticated session against one Looker instance."""

    def __init__(self, credentials: LookerCredentials, transport: Transport | None = None) -> None:
        """Store credentials. Authentication happens in login(), not here."""
        self.credentials = credentials
        self._transport = transport if transport is not None else UrllibTransport(credentials.verify_ssl)
        self._token = ""

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> LookerClient:
        """Build a client from the environment and log in."""
        client = cls(credentials_from_env(environ))
        client.login()
        return client

    def login(self) -> None:
        """Exchange the API3 client id and secret for a session token."""
        form = urllib.parse.urlencode(
            {"client_id": self.credentials.client_id, "client_secret": self.credentials.client_secret}
        ).encode("utf-8")
        payload = self._request(
            "POST",
            "/login",
            form=form,
            authenticated=False,
        )
        token = payload.get("access_token") if isinstance(payload, dict) else None
        if not isinstance(token, str) or not token:
            raise LookerApiError(200, "POST", "/login", "Login response did not include access_token.")
        self._token = token

    def use_dev_workspace(self) -> None:
        """Point this session at the dev workspace so file writes land on the dev branch."""
        self._request("PATCH", "/session", json_body={"workspace_id": "dev"})

    def current_user_label(self) -> str:
        """Display name and email of the authenticated user. A failed call returns a generic label."""
        try:
            payload = self._request("GET", "/user", query={"fields": "display_name,email"})
        except LookerApiError:
            return "the user that owns the API credentials"
        if not isinstance(payload, dict):
            return "the user that owns the API credentials"
        return user_label(payload)

    def ensure_project(self, project_id: str) -> bool:
        """Create the project when it is missing. Return True when this call created it."""
        try:
            self._request("GET", f"/projects/{_quote(project_id)}")
        except LookerApiError as exc:
            if exc.status != 404:
                raise
            self._request("POST", "/projects", json_body={"name": project_id})
            return True
        return False

    def file_paths(self, project_id: str) -> set[str]:
        """Relative paths of files currently in the project. Folders are omitted."""
        payload = self._request("GET", f"/projects/{_quote(project_id)}/files")
        if not isinstance(payload, list):
            raise LookerApiError(200, "GET", f"/projects/{project_id}/files", "Expected a list of files.")
        paths: set[str] = set()
        for item in payload:
            if not isinstance(item, dict):
                continue
            if str(item.get("type") or "") in _FOLDER_TYPES:
                continue
            raw = str(item.get("path") or "").lstrip("/")
            if raw:
                paths.add(raw)
        return paths

    def ensure_directory(self, project_id: str, directory: str) -> bool:
        """Create one project directory. Return False when this Looker has no directories route.

        An existing directory is not an error.
        """
        try:
            self._request(
                "POST",
                f"/projects/{_quote(project_id)}/directories",
                json_body={"path": directory},
            )
        except LookerApiError as exc:
            if exc.status == 404:
                return False
            if exc.status == 409 or "already exist" in str(exc).lower():
                return True
            raise
        return True

    def write_file(self, project_id: str, path: str, contents: str, *, exists: bool) -> str:
        """Create or replace one file. Return 'created' or 'updated'.

        A 409 on create means the file is already there, so the call updates it.
        A 404 on update means the listing was stale, so the call creates it.
        """
        body = {"path": path, "content": contents}
        files_path = f"/projects/{_quote(project_id)}/files"
        if exists:
            try:
                self._request("PUT", files_path, json_body=body)
            except LookerApiError as exc:
                if exc.status != 404:
                    raise
                self._request("POST", files_path, json_body=body)
                return "created"
            return "updated"
        try:
            self._request("POST", files_path, json_body=body)
        except LookerApiError as exc:
            if not _already_exists(exc):
                raise
            self._request("PUT", files_path, json_body=body)
            return "updated"
        return "created"

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Mapping[str, str] | None = None,
        form: bytes | None = None,
        query: Mapping[str, str] | None = None,
        authenticated: bool = True,
    ) -> object:
        """Send one API call and return the decoded JSON body, or None when the body is empty."""
        headers: dict[str, str] = {}
        if authenticated:
            if not self._token:
                raise LookerConfigError("Log in before calling the Looker API.")
            headers["Authorization"] = f"token {self._token}"
        body: bytes | None
        if json_body is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        else:
            body = form
            if form is not None:
                headers["Content-Type"] = "application/x-www-form-urlencoded"
        url = self.credentials.base_url + API_PREFIX + path
        if query:
            url = url + "?" + urllib.parse.urlencode(query)
        result = self._transport.send(method, url, headers, body, REQUEST_TIMEOUT_SECONDS)
        text = result.body.decode("utf-8", errors="replace")
        if result.status >= 400:
            raise LookerApiError(result.status, method, path, text)
        if not text.strip():
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise LookerApiError(result.status, method, path, "Response was not JSON.") from exc


def deploy(client: LookerClient, project_id: str, files: Mapping[str, str]) -> DeployResult:
    """Switch to dev mode, reuse or create the project, and write every file.

    Files that exist only in Looker are left in place. Parent directories are created
    before the files that live in them. When the directories route is absent, file
    writes continue on their own.
    """
    check_project_id(project_id)
    if not files:
        raise LookerConfigError("No LookML files to upload.")
    client.use_dev_workspace()
    user = client.current_user_label()
    created_project = client.ensure_project(project_id)
    directories_supported = True
    for directory in parent_directories(files):
        if not directories_supported:
            break
        directories_supported = client.ensure_directory(project_id, directory)
    existing = client.file_paths(project_id)
    created: list[str] = []
    updated: list[str] = []
    for path in sorted(files):
        action = client.write_file(project_id, path, files[path], exists=path in existing)
        if action == "created":
            created.append(path)
        else:
            updated.append(path)
    return DeployResult(
        project_id=project_id,
        project_created=created_project,
        created=tuple(created),
        updated=tuple(updated),
        user_label=user,
        project_url=project_files_url(client.credentials.base_url, project_id),
    )


def _quote(value: str) -> str:
    """Encode one URL path segment, including slashes."""
    return urllib.parse.quote(value, safe="")
