"""The backend serves the built frontend from the same port as the API."""

from __future__ import annotations

import re

import pytest


@pytest.fixture(scope="module")
def shell_html(stack) -> str:
    return stack.http.get("/").text


@pytest.fixture(scope="module")
def asset_paths(shell_html) -> list[str]:
    paths = sorted(set(re.findall(r'(?:href|src)="(/assets/[^"]+)"', shell_html)))
    assert paths, "the shell references no /assets/ files -- was the frontend built?"
    return paths


def test_root_serves_the_app_shell(stack):
    response = stack.http.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.text.lstrip().lower().startswith("<!doctype html")
    assert "Draftbench" in response.text


@pytest.mark.parametrize("path", ["/session/abc123", "/session/s_deadbeef?host=1"])
def test_client_side_routes_are_served_by_the_shell(stack, shell_html, path):
    # A candidate opens an invite link cold: there is no file behind this URL.
    response = stack.http.get(path)
    assert response.status_code == 200
    assert response.text == shell_html


def test_every_asset_the_shell_references_is_served(stack, asset_paths):
    for path in asset_paths:
        response = stack.http.get(path)
        assert response.status_code == 200, path
        expected = "css" if path.endswith(".css") else "javascript"
        assert expected in response.headers["content-type"], path
        assert len(response.content) > 0, path


def test_fingerprinted_assets_are_cached_but_the_shell_is_not(stack, asset_paths):
    assert "immutable" in stack.http.get(asset_paths[0]).headers["cache-control"]
    assert "immutable" not in stack.http.get("/").headers.get("cache-control", "")


def test_a_missing_asset_is_a_404_not_the_html_shell(stack):
    # Answering with HTML makes the browser fail with "Unexpected token '<'".
    response = stack.http.get("/assets/does-not-exist-abc123.js")
    assert response.status_code == 404
    assert "<html" not in response.text.lower()


def test_the_api_still_wins_over_the_frontend_catch_all(stack):
    response = stack.http.post("/sessions")
    assert response.status_code == 201
    assert response.headers["content-type"].startswith("application/json")


def test_the_production_bundle_does_not_hardcode_the_dev_backend_url(stack, asset_paths):
    # In production the frontend must talk to the origin that served it. If the
    # dev fallback (http://localhost:8000) leaks into the bundle, the app works
    # on the developer's machine and nowhere else.
    js_paths = [p for p in asset_paths if p.endswith(".js")]
    assert js_paths
    for path in js_paths:
        assert "localhost:8000" not in stack.http.get(path).text, path
