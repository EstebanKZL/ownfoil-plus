"""Etapa 4: indexes for the hot lookups of large libraries, the add_file existence
check, and the Prometheus /metrics endpoint."""
import base64
import importlib.util
import os
import re

import fixture
import pytest
from sqlalchemy import text

from db import Files, db

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _basic(user):
    token = base64.b64encode(f"{user}:{fixture.PASSWORDS[user]}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


# --- indexes -------------------------------------------------------------------------

@pytest.mark.parametrize("sql, index", [
    ("SELECT app_type, app_version, owned FROM apps WHERE title_id = 1", "ix_apps_title_id"),
    ("SELECT id FROM files ORDER BY added_at DESC LIMIT 50", "ix_files_added_at"),
    ("SELECT id FROM files WHERE library_id = 1", "ix_files_library_id"),
])
def test_hot_queries_use_their_index(shop_app, sql, index):
    with shop_app.app.app_context():
        plan = " ".join(r[-1] for r in db.session.execute(text("EXPLAIN QUERY PLAN " + sql)).all())
    assert index in plan, plan


def test_migration_adds_the_same_indexes_as_the_models(monkeypatch):
    path = os.path.join(ROOT, "app", "migrations", "versions", "d5e6f7a8b9c0_add_performance_indexes.py")
    spec = importlib.util.spec_from_file_location("perf_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    created = []
    monkeypatch.setattr(module.op, "create_index", lambda name, table, cols: created.append((name, table, cols)))
    module.upgrade()
    assert sorted(created) == [("ix_apps_title_id", "apps", ["title_id"]),
                               ("ix_files_added_at", "files", ["added_at"]),
                               ("ix_files_library_id", "files", ["library_id"])]
    model_indexes = {i.name for t in ("apps", "files") for i in db.metadata.tables[t].indexes}
    assert {name for name, _, _ in created} <= model_indexes
    assert module.down_revision == "c4d5e6f7a8b9"


def test_add_file_skips_a_known_path_with_one_lookup(shop_app, monkeypatch):
    import tasks
    import db as db_mod
    monkeypatch.setattr(db_mod, "get_library_file_paths",
                        lambda *a: pytest.fail("must not load every path of the library"))
    with shop_app.app.app_context():
        existing = Files.query.first()
        assert db_mod.file_path_in_db(existing.filepath)
        assert not db_mod.file_path_in_db(existing.filepath + ".missing")
        before = Files.query.count()
        tasks.add_file_task(shop_app.library_root, existing.filepath)
        assert Files.query.count() == before


# --- /metrics ------------------------------------------------------------------------

def _samples(body):
    out = {}
    for line in body.splitlines():
        if line and not line.startswith("#"):
            name_labels, value = line.rsplit(" ", 1)
            out[name_labels] = float(value)
    return out


def test_metrics_need_admin_credentials(shop_app):
    assert shop_app.client.get("/metrics").status_code == 401
    assert "Basic" in shop_app.client.get("/metrics").headers["WWW-Authenticate"]
    assert shop_app.client.get("/metrics", headers=_basic("shopper")).status_code == 401


def test_metrics_with_basic_auth(shop_app):
    resp = shop_app.client.get("/metrics", headers=_basic("admin"))
    assert resp.status_code == 200
    assert resp.mimetype == "text/plain"
    body = resp.get_data(as_text=True)
    samples = _samples(body)
    with shop_app.app.app_context():
        files = Files.query.count()
    assert samples["ownfoil_library_files"] == files
    assert samples["ownfoil_library_unidentified_files"] == 1
    assert samples["ownfoil_titles_owned"] == 1
    assert samples["ownfoil_users"] == 3
    assert 'ownfoil_tasks{status="failed"}' in samples
    assert any(k.startswith("ownfoil_files_by_verification_status{") for k in samples)
    assert any(k.startswith("ownfoil_info{version=") for k in samples)


def test_metrics_format_is_valid_exposition(shop_app):
    body = shop_app.client.get("/metrics", headers=_basic("admin")).get_data(as_text=True)
    name = r'[a-zA-Z_][a-zA-Z0-9_]*'
    sample = re.compile(rf'^{name}(\{{{name}="[^"]*"(,{name}="[^"]*")*\}})? -?[0-9.e+]+$')
    for line in body.strip().splitlines():
        if line.startswith("# HELP") or line.startswith("# TYPE"):
            continue
        assert sample.match(line), line
    assert body.endswith("\n")


def test_large_values_are_exact():
    import metrics
    assert metrics._number(41943040) == "41943040"
    assert metrics._number(123456789012345) == "123456789012345"
    assert metrics._number(1793510040.5) == "1793510040.5"
    assert metrics._number(0) == "0"


def test_metrics_with_a_bearer_token(shop_app, monkeypatch):
    monkeypatch.setenv("OWNFOIL_METRICS_TOKEN", "s3cret-token")
    ok = shop_app.client.get("/metrics", headers={"Authorization": "Bearer s3cret-token"})
    assert ok.status_code == 200
    bad = shop_app.client.get("/metrics", headers={"Authorization": "Bearer wrong"})
    assert bad.status_code == 401


def test_metrics_for_a_signed_in_admin(shop_app):
    shop_app.client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]})
    assert shop_app.client.get("/metrics").status_code == 200
