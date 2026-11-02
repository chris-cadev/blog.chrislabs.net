from fastapi.testclient import TestClient

import blog_chat.app as app_module
import blog_chat.core.config as config_module
import blog_chat.features.posts.routes as posts_routes
import logging
UMAMI_HOST = "latitudem2m-analytics.chrislabs.net"
UMAMI_SCRIPT_URL = "https://latitudem2m-analytics.chrislabs.net/script.js"
UMAMI_RECORDER_URL = "https://latitudem2m-analytics.chrislabs.net/recorder.js"
UMAMI_WEBSITE_ID = "057c4459-7212-4f49-a756-bc631a5c5e94"


class TestConfig:
    def test_script_url_and_host_derived(self):
        assert config_module.UMAMI_SCRIPT_URL == UMAMI_SCRIPT_URL
        assert config_module.UMAMI_HOST == UMAMI_HOST

    def test_env_bool_parsing(self, monkeypatch):
        monkeypatch.setenv("UMAMI_ENABLED", "false")
        assert config_module._env_bool("UMAMI_ENABLED") is False
        monkeypatch.setenv("UMAMI_ENABLED", "TRUE")
        assert config_module._env_bool("UMAMI_ENABLED") is True
        monkeypatch.setenv("UMAMI_ENABLED", "1")
        assert config_module._env_bool("UMAMI_ENABLED") is True


class TestCSP:
    def test_umami_origin_in_script_and_connect_when_active(self, monkeypatch):
        monkeypatch.setattr(app_module, "UMAMI_ACTIVE", True)
        monkeypatch.setattr(app_module, "UMAMI_HOST", UMAMI_HOST)
        csp = app_module.build_csp("nonce123")
        assert f"'self' 'nonce-nonce123' https://{UMAMI_HOST}" in csp
        assert f"connect-src 'self' wss: ws: https://{UMAMI_HOST}" in csp

    def test_no_umami_origin_when_disabled(self, monkeypatch):
        monkeypatch.setattr(app_module, "UMAMI_ACTIVE", False)
        monkeypatch.setattr(app_module, "UMAMI_HOST", UMAMI_HOST)
        csp = app_module.build_csp("nonce123")
        assert UMAMI_HOST not in csp
        assert "connect-src 'self' wss: ws:" in csp


class TestPageInjection:
    def test_tracker_metadata_when_enabled(self, monkeypatch):
        monkeypatch.setattr(posts_routes, "UMAMI_ACTIVE", True)
        with TestClient(app_module.app) as client:
            page = client.get("/en/firstcommit")
        assert page.status_code == 200
        assert f"data-umami-script={UMAMI_SCRIPT_URL}" in page.text
        assert f"data-umami-recorder={UMAMI_RECORDER_URL}" in page.text
        assert f"data-umami-website-id={UMAMI_WEBSITE_ID}" in page.text

    def test_no_external_script_in_head(self, monkeypatch):
        monkeypatch.setattr(posts_routes, "UMAMI_ACTIVE", True)
        with TestClient(app_module.app) as client:
            page = client.get("/en/firstcommit")
        assert '<script src="https://' not in page.text

    def test_tracker_metadata_omitted_when_disabled(self, monkeypatch):
        monkeypatch.setattr(posts_routes, "UMAMI_ACTIVE", False)
        with TestClient(app_module.app) as client:
            page = client.get("/en/firstcommit")
        assert "data-umami-script" not in page.text
        assert "data-umami-recorder" not in page.text
        assert "data-umami-website-id" not in page.text
        assert "latitudem2m-analytics.chrislabs.net" not in page.text


class TestTrackEndpoint:
    def test_logs_client_event_with_fields(self, caplog):
        with caplog.at_level(logging.INFO, logger="blog_chat.events"):
            with TestClient(app_module.app) as client:
                resp = client.post(
                    "/api/track",
                    json={"event": "Post Click", "data": {"slug": "hello-world"}},
                )
            assert resp.status_code == 204
        matches = [
            r for r in caplog.records
            if getattr(r, "event", None) == "client.event"
        ]
        assert matches
        record = matches[0]
        assert record.client_event == "Post Click"
        assert record.slug == "hello-world"
        assert record.detail == "business"

    def test_rejects_missing_or_oversized_event(self):
        with TestClient(app_module.app) as client:
            assert client.post("/api/track", json={"event": ""}).status_code == 400
            assert client.post("/api/track", json={"event": "x" * 200}).status_code == 400

    def test_rejects_invalid_payload_without_crashing(self):
        with TestClient(app_module.app) as client:
            resp = client.post("/api/track", content="not json")
        assert resp.status_code == 400
