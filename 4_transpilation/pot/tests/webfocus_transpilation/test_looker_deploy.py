"""Looker upload: file collection, request shape, and create-versus-update."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from webfocus_transpilation.looker_deploy import (
    HttpResult,
    LookerApiError,
    LookerClient,
    LookerConfigError,
    LookerCredentials,
    collect_lookml,
    credentials_from_env,
    deploy,
    parent_directories,
    project_files_url,
    project_id_from_env,
)


class ScriptedTransport:
    """Returns queued HTTP results and records each call."""

    def __init__(self, responses: list[tuple[int, object]]) -> None:
        """Queue (status, JSON-able body) pairs. A None body is an empty response."""
        self._responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, str], bytes | None]] = []

    def send(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResult:
        """Pop the next scripted response."""
        self.calls.append((method, url, headers, body))
        status, payload = self._responses.pop(0)
        raw = b"" if payload is None else json.dumps(payload).encode("utf-8")
        return HttpResult(status, raw)


def _client(transport: ScriptedTransport) -> LookerClient:
    """A client pointed at a fake instance."""
    credentials = LookerCredentials("https://looker.example", "id", "secret", True)
    return LookerClient(credentials, transport)


def _json_body(call: tuple[str, str, dict[str, str], bytes | None]) -> dict[str, str]:
    """Decode the JSON body of one recorded call."""
    assert call[3] is not None
    return json.loads(call[3].decode("utf-8"))


def test_collect_lookml_uses_relative_paths_and_skips_other_files(tmp_path: Path) -> None:
    """Nested .lkml files are keyed by their path. Notes and dotfiles stay out."""
    (tmp_path / "views" / "sales").mkdir(parents=True)
    (tmp_path / "manifest.lkml").write_text("constant: c {}", encoding="utf-8")
    (tmp_path / "views" / "sales" / "orders.view.lkml").write_text("view: orders {}", encoding="utf-8")
    (tmp_path / "README.md").write_text("skip", encoding="utf-8")
    (tmp_path / ".hidden.lkml").write_text("view: hidden {}", encoding="utf-8")

    files = collect_lookml(tmp_path)

    assert files == {
        "manifest.lkml": "constant: c {}",
        "views/sales/orders.view.lkml": "view: orders {}",
    }


def test_collect_lookml_rejects_an_empty_directory(tmp_path: Path) -> None:
    """A folder with no LookML is a failed upload, not an empty project write."""
    with pytest.raises(FileNotFoundError):
        collect_lookml(tmp_path)


def test_credentials_require_the_three_looker_variables() -> None:
    """A partial environment names the variables that are still missing."""
    with pytest.raises(LookerConfigError, match="LOOKERSDK_CLIENT_SECRET"):
        credentials_from_env({"LOOKERSDK_BASE_URL": "https://looker.example", "LOOKERSDK_CLIENT_ID": "id"})


def test_project_files_url_drops_an_api_suffix() -> None:
    """The link opens the IDE, so an API base URL loses its /api/4.0 suffix."""
    assert project_files_url("https://looker.example/api/4.0", "webfocus_pot") == (
        "https://looker.example/projects/webfocus_pot/files"
    )


def test_parent_directories_are_shallowest_first() -> None:
    """A nested view creates its parents before the deeper directory."""
    assert parent_directories(["views/sales/orders.view.lkml", "manifest.lkml"]) == [
        "views",
        "views/sales",
    ]


def test_project_id_from_env_reads_variable_or_falls_back_to_default() -> None:
    """Configured variable wins; empty or missing falls back to 'webfocus_pot'."""
    assert project_id_from_env({"LOOKER_PROJECT_ID": "client_sales_poc"}) == "client_sales_poc"
    assert project_id_from_env({"LOOKERSDK_PROJECT_ID": "sdk_project"}) == "sdk_project"
    assert project_id_from_env({}) == "webfocus_pot"
    assert project_id_from_env({"LOOKER_PROJECT_ID": "   "}) == "webfocus_pot"


def test_project_id_from_env_rejects_invalid_names() -> None:
    """Names not conforming to Looker project id syntax are caught early."""
    with pytest.raises(LookerConfigError):
        project_id_from_env({"LOOKER_PROJECT_ID": "123_invalid_start"})


def test_login_sends_the_token_on_the_next_call() -> None:
    """Login posts the API3 secret as a form, then later calls use the access token."""
    transport = ScriptedTransport(
        [
            (200, {"access_token": "token-1"}),
            (200, {"workspace_id": "dev"}),
        ]
    )
    client = _client(transport)
    client.login()
    client.use_dev_workspace()

    login = transport.calls[0]
    assert login[0] == "POST"
    assert login[1].endswith("/api/4.0/login")
    assert b"client_secret=secret" in (login[3] or b"")
    assert "Authorization" not in login[2]
    assert transport.calls[1][2]["Authorization"] == "token token-1"


def test_write_file_posts_content_and_puts_when_the_path_exists() -> None:
    """New files are POST, existing files are PUT, and the text field is 'content'."""
    transport = ScriptedTransport([(200, {"path": "a.view.lkml"}), (200, {"path": "b.view.lkml"})])
    client = _client(transport)
    client._token = "token-1"

    assert client.write_file("webfocus_pot", "views/a.view.lkml", "view: a {}", exists=False) == "created"
    assert client.write_file("webfocus_pot", "b.view.lkml", "view: b {}", exists=True) == "updated"

    created = transport.calls[0]
    updated = transport.calls[1]
    assert created[0] == "POST"
    assert created[1].endswith("/api/4.0/projects/webfocus_pot/files")
    assert _json_body(created) == {"path": "views/a.view.lkml", "content": "view: a {}"}
    assert updated[0] == "PUT"
    assert _json_body(updated)["content"] == "view: b {}"


def test_create_conflict_falls_back_to_update() -> None:
    """A 409 means the listing was stale and the file is already in the project."""
    transport = ScriptedTransport(
        [
            (409, {"message": "already exists"}),
            (200, {"path": "a.view.lkml"}),
        ]
    )
    client = _client(transport)
    client._token = "token-1"

    assert client.write_file("webfocus_pot", "a.view.lkml", "view: a {}", exists=False) == "updated"
    assert [call[0] for call in transport.calls] == ["POST", "PUT"]


def test_create_400_already_exists_falls_back_to_update() -> None:
    """This Looker answers 400 'File already exists' for a duplicate create; the file is updated."""
    transport = ScriptedTransport(
        [
            (400, {"message": "File already exists", "documentation_url": "x"}),
            (200, {"path": "manifest.lkml"}),
        ]
    )
    client = _client(transport)
    client._token = "token-1"

    assert client.write_file("webfocus_pot", "manifest.lkml", "constant: c {}", exists=False) == "updated"
    assert [call[0] for call in transport.calls] == ["POST", "PUT"]


def test_other_400_errors_are_not_treated_as_existing() -> None:
    """A 400 for any other reason is raised, not silently turned into an update."""
    transport = ScriptedTransport([(400, {"message": "Invalid LookML path"})])
    client = _client(transport)
    client._token = "token-1"

    with pytest.raises(LookerApiError, match="Invalid LookML path"):
        client.write_file("webfocus_pot", "bad.view.lkml", "view: a {}", exists=False)
    assert len(transport.calls) == 1


def test_manifest_listed_as_project_type_counts_as_an_existing_file() -> None:
    """Looker lists manifest.lkml with type 'project'; it must not be dropped as a folder."""
    transport = ScriptedTransport([(200, [{"path": "manifest.lkml", "type": "project"}])])
    client = _client(transport)
    client._token = "token-1"

    assert "manifest.lkml" in client.file_paths("webfocus_pot")


def test_deploy_reuses_a_project_and_leaves_unrelated_files() -> None:
    """An existing project is not recreated, and a file we did not upload is not deleted."""
    transport = ScriptedTransport(
        [
            (200, {"workspace_id": "dev"}),
            (200, {"display_name": "Ada", "email": "ada@example.com"}),
            (200, {"id": "webfocus_pot"}),
            (200, None),
            (200, [
                {"path": "manifest.lkml", "type": "project"},
                {"path": "views", "type": "folder"},
                {"path": "kept.view.lkml", "type": "view"},
            ]),
            (200, {"path": "manifest.lkml"}),
            (200, {"path": "views/orders.view.lkml"}),
        ]
    )
    client = _client(transport)
    client._token = "token-1"

    result = deploy(
        client,
        "webfocus_pot",
        {"manifest.lkml": "constant: c {}", "views/orders.view.lkml": "view: orders {}"},
    )

    assert result.project_created is False
    assert result.updated == ("manifest.lkml",)
    assert result.created == ("views/orders.view.lkml",)
    assert result.user_label == "Ada (ada@example.com)"
    assert result.project_url == "https://looker.example/projects/webfocus_pot/files"
    methods = [call[0] for call in transport.calls]
    assert "DELETE" not in methods
    assert methods[3] == "POST"
    assert transport.calls[3][1].endswith("/directories")
    assert _json_body(transport.calls[3]) == {"path": "views"}


def test_deploy_creates_a_missing_project() -> None:
    """A 404 on the project lookup is followed by a create."""
    transport = ScriptedTransport(
        [
            (200, {"workspace_id": "dev"}),
            (200, {"display_name": "Ada", "email": "ada@example.com"}),
            (404, {"message": "Not found"}),
            (200, {"id": "webfocus_pot", "name": "webfocus_pot"}),
            (200, []),
            (200, {"path": "manifest.lkml"}),
        ]
    )
    client = _client(transport)
    client._token = "token-1"

    result = deploy(client, "webfocus_pot", {"manifest.lkml": "constant: c {}"})

    assert result.project_created is True
    assert result.created == ("manifest.lkml",)
    assert transport.calls[3][0] == "POST"
    assert transport.calls[3][1].endswith("/api/4.0/projects")
    assert _json_body(transport.calls[3]) == {"name": "webfocus_pot"}


def test_api_error_includes_the_status_and_not_the_secret() -> None:
    """A failed login surfaces the status text and leaves the client secret out of the message."""
    transport = ScriptedTransport([(401, {"message": "Not authorized"})])
    client = _client(transport)

    with pytest.raises(LookerApiError, match="401") as caught:
        client.login()

    assert "secret" not in str(caught.value)
