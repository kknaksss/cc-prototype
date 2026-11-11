"""OpenAPI 문서 — 경로(/api 아래) · 설명 빠진 곳 0 · Bearer 표시가 동작(401 모양)을 안 바꾼다."""

from typing import Any

from app.api.deps import require_login
from app.openapi_docs import BEARER, _api_routes


def _spec(client) -> dict[str, Any]:
    r = client.get("/api/openapi.json")
    assert r.status_code == 200
    return r.json()


def test_docs_paths(client):
    assert client.get("/api/docs").status_code == 200
    assert client.get("/api/redoc").status_code == 200
    assert client.get("/api/openapi.json").status_code == 200
    for old in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"):
        r = client.get(old)
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "not_found"


def test_docs_open_without_login_and_title(client):
    spec = _spec(client)
    assert spec["info"]["title"] == "CCC procedure API"
    assert spec["info"]["version"] == "0.1.0"
    assert "https://ccc.medisolveai.xyz" in spec["info"]["description"]
    assert "/api/interpret" in spec["info"]["description"]


def test_every_operation_has_summary_description_and_tag(client):
    spec = _spec(client)
    tags = {t["name"] for t in spec["tags"]}
    missing = []
    for path, item in spec["paths"].items():
        for method, op in item.items():
            for key in ("summary", "description"):
                if not str(op.get(key) or "").strip():
                    missing.append(f"{method.upper()} {path} · {key}")
            if not op.get("tags") or not set(op["tags"]) <= tags:
                missing.append(f"{method.upper()} {path} · tags")
            for p in op.get("parameters", []):
                if not str(p.get("description") or "").strip():
                    missing.append(f"{method.upper()} {path} · param {p['name']}")
    assert missing == []
    assert all(str(t.get("description") or "").strip() for t in spec["tags"])


def _walk_properties(node: Any, where: str, out: list[str]) -> None:
    if isinstance(node, dict):
        for name, prop in (node.get("properties") or {}).items():
            if not str(prop.get("description") or "").strip():
                out.append(f"{where}.{name}")
        for k, v in node.items():
            _walk_properties(v, f"{where}.{k}", out)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _walk_properties(v, f"{where}[{i}]", out)


def test_every_schema_property_has_description(client):
    spec = _spec(client)
    out: list[str] = []
    _walk_properties(spec["components"]["schemas"], "schemas", out)
    _walk_properties(spec["paths"], "paths", out)  # openapi_extra 로 실은 multipart 칸까지
    assert out == []


def test_no_422_documented(client):
    """검증 오류는 400 invalid_request(main 처리기) — FastAPI 기본 422 를 문서에 남기지 않는다."""
    spec = _spec(client)
    assert all("422" not in op.get("responses", {}) for item in spec["paths"].values() for op in item.values())
    assert "HTTPValidationError" not in spec["components"]["schemas"]


def test_bearer_security_matches_require_login(client):
    spec = _spec(client)
    scheme = spec["components"]["securitySchemes"][BEARER]
    assert (scheme["type"], scheme["scheme"]) == ("http", "bearer")

    def needs(dep) -> bool:
        return dep.call is require_login or any(needs(x) for x in dep.dependencies)

    routes = [r for r in _api_routes(client.app.routes) if r.include_in_schema]
    n_ops = sum(len(item) for item in spec["paths"].values())
    assert sum(len(r.methods) for r in routes) == n_ops  # 문서의 operation 을 다 봤다
    secured = 0
    for r in routes:
        for m in r.methods:
            op = spec["paths"][r.path_format][m.lower()]
            assert (op.get("security") == [{BEARER: []}]) is needs(r.dependant), f"{m} {r.path_format}"
            secured += needs(r.dependant)
    # 로그인 없는 곳 = login · health · stream(?token=) · 공개 문진 2 — 나머지는 모두 Bearer
    assert secured == n_ops - 5
    assert spec["paths"]["/api/auth/me"]["get"]["security"] == [{BEARER: []}]
    assert spec["paths"]["/api/visits/{visit_id}/home"]["post"]["security"] == [{BEARER: []}]
    assert "security" not in spec["paths"]["/api/auth/login"]["post"]
    assert "security" not in spec["paths"]["/api/health"]["get"]
    assert "security" not in spec["paths"]["/api/board/stream"]["get"]  # ?token= — 헤더 아님


def test_security_is_docs_only(client):
    """보안 표시는 문서에만 — 401 모양 · 공개 경로는 그대로."""
    r = client.get("/api/auth/me")
    assert r.status_code == 401
    assert r.json() == {"error": {"code": "unauthorized", "message": "로그인이 필요해요"}}
    assert "www-authenticate" not in r.headers
    assert client.get("/api/health").status_code == 200


def _codes(op: dict, status: str) -> set[str]:
    """응답 표 설명의 `- \\`code\\` — …` 줄에서 코드만."""
    text = op.get("responses", {}).get(status, {}).get("description", "")
    return {line.split("`")[1] for line in text.splitlines() if line.startswith("- `")}


def test_error_tables_match_dependencies(client):
    """require_login ↔ 401 unauthorized · require_real_board ↔ 403 fake_board — 양쪽 다 맞아야(리뷰 「조용히 통과」 2)."""
    from app.api.deps import require_real_board

    spec = _spec(client)

    def has(dep, fn) -> bool:
        return dep.call is fn or any(has(x, fn) for x in dep.dependencies)

    # 의존성 밖에서 같은 오류를 내는 곳 — SSE 는 ?token= 을 직접 검증 · 공개 문진 제출은 라우트 안에서 fake_board 검사
    unauth_extra = {("GET", "/api/board/stream")}
    fake_extra = {("POST", "/api/public/questionnaire")}
    bad = []
    for r in _api_routes(client.app.routes):
        if not r.include_in_schema:
            continue
        for m in r.methods:
            key = (m, r.path_format)
            op = spec["paths"][r.path_format][m.lower()]
            if (has(r.dependant, require_login) or key in unauth_extra) != ("unauthorized" in _codes(op, "401")):
                bad.append(f"{m} {r.path_format} · 401 unauthorized")
            if (has(r.dependant, require_real_board) or key in fake_extra) != ("fake_board" in _codes(op, "403")):
                bad.append(f"{m} {r.path_format} · 403 fake_board")
    assert bad == []
