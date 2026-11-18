"""Despliegue de un solo servicio: el backend sirve el frontend exportado en la misma URL que la API."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture()
def site(tmp_path):
    out = tmp_path / "out"
    (out / "deals").mkdir(parents=True)
    (out / "_next" / "static").mkdir(parents=True)
    (out / "index.html").write_text("INICIO", encoding="utf-8")
    (out / "index.txt").write_text("RSC-INICIO", encoding="utf-8")
    (out / "404.html").write_text("NO-EXISTE", encoding="utf-8")
    (out / "deals" / "_.html").write_text("EXPEDIENTE", encoding="utf-8")
    (out / "deals" / "_.txt").write_text("RSC-EXPEDIENTE", encoding="utf-8")
    (out / "deals" / "new.html").write_text("NUEVA", encoding="utf-8")
    (out / "_next" / "static" / "app.js").write_text("js", encoding="utf-8")
    (tmp_path / "secreto.txt").write_text("NO", encoding="utf-8")
    return out


@pytest.fixture()
def client(settings, site):
    return TestClient(create_app(settings.__class__(**{**settings.__dict__, "frontend_dir": site})))


def test_pages_are_served_from_the_same_url_as_the_api(client):
    assert client.get("/").text == "INICIO"
    assert client.get("/deals/new").text == "NUEVA"
    # Cualquier operación usa la página exportada única; el id se lee en el navegador
    assert client.get("/deals/deal-3f2a9c1b7e4d").text == "EXPEDIENTE"
    assert client.get("/deals/demo-123").headers["cache-control"] == "no-cache"
    nav = client.get("/deals/deal-3f2a9c1b7e4d.txt?_rsc=abc")
    assert nav.text == "RSC-EXPEDIENTE" and nav.headers["content-type"].startswith("text/x-component")
    static = client.get("/_next/static/app.js")
    assert static.text == "js" and "immutable" in static.headers["cache-control"]


def test_api_keeps_working_and_unknown_paths_404(client):
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/api/no-existe").status_code == 404
    missing = client.get("/otra/ruta")
    assert missing.status_code == 404 and missing.text == "NO-EXISTE"
    assert client.get("/deals/a/b").status_code == 404


def test_no_path_traversal(client):
    for path in ("/../secreto.txt", "/%2e%2e/secreto.txt", "/deals/..%2f..%2fsecreto.txt", "/..%5csecreto.txt"):
        assert client.get(path).text != "NO"  # el archivo fuera de out/ nunca se entrega


def test_without_frontend_dir_only_the_api_is_served(settings):
    client = TestClient(create_app(settings))
    assert client.get("/").status_code == 404
    assert client.get("/api/health").status_code == 200
