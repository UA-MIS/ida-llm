"""Health-endpoint tests.

These exist because the probe semantics are a DEPLOYMENT contract, not an app
detail: if /healthz ever starts touching the database, a brief DB blip becomes a
cluster-wide rolling restart. The first test is what stops that regression.
"""

from fastapi.testclient import TestClient

from ida_api.app import app

client = TestClient(app)


def test_healthz_is_ok_without_a_database():
    # No DATABASE_URL is configured in this test process. Liveness must still pass.
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readyz_reports_not_ready_without_a_database():
    # And readiness must NOT pass -- a pod that cannot reach its DB should be
    # pulled from the Service, not restarted and not serving.
    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["status"] == "not-ready"


def test_runs_endpoint_shape():
    response = client.get("/api/runs")
    assert response.status_code == 200
    assert response.json() == {"runs": []}
