"""SPEC-008 §8 Swagger — T29(외부 tag · ExtApiKey · security · 오류 표 · 설명 문장)."""

from app.api.docs import STATUS_TEXT, T_EXT
from app.openapi_docs import BEARER, EXT_KEY

OPS = {("get", "/api/ext/menu"), ("post", "/api/ext/customers/lookup"), ("post", "/api/ext/reservations")}


def _spec(client):
    return client.get("/api/openapi.json").json()


def test_t29_ext_swagger(client):
    spec = _spec(client)
    tags = {t["name"]: t["description"] for t in spec["tags"]}
    assert "X-Api-Key" in tags[T_EXT] and "직원 로그인 토큰으로는 열리지 않는다" in tags[T_EXT]
    assert spec["components"]["securitySchemes"][EXT_KEY] == {
        "type": "apiKey", "in": "header", "name": "X-Api-Key",
        "description": "연동처별 API 키(링키 · 차티 각각). 직원 Bearer 와 다르다."}
    assert BEARER in spec["components"]["securitySchemes"]
    ext_ops = {(m, p) for p, item in spec["paths"].items() for m, op in item.items() if T_EXT in op.get("tags", [])}
    assert ext_ops == OPS
    for m, p in OPS:
        op = spec["paths"][p][m]
        assert op["tags"] == [T_EXT] and op["security"] == [{EXT_KEY: []}]
        e401 = op["responses"]["401"]["description"]
        assert "`ext_unauthorized`" in e401 and "`unauthorized`" not in e401 and "X-Api-Key" in e401
        assert e401.split("- `ext_unauthorized` — ")[1].startswith("직원 로그인이 아니라 `X-Api-Key`")
        assert "`too_many_requests`" in op["responses"]["429"]["description"]
        assert "`http_error`" in op["responses"]["405"]["description"]
        e500 = op["responses"]["500"]["description"]  # 수정 2(검수 r2 N1)
        assert e500.startswith(STATUS_TEXT[500]) and "`internal_error`" in e500 and "IP 카운트 안 함" in e500
        assert "duplicated_visitor" not in str(op) and "candidate" not in str(op["responses"])
    others = [op for p, item in spec["paths"].items() for m, op in item.items() if (m, p) not in OPS]
    assert all(op.get("security") != [{EXT_KEY: []}] for op in others)
    resv = spec["paths"]["/api/ext/reservations"]["post"]
    assert resv["responses"]["503"]["description"].startswith(STATUS_TEXT[503]) and STATUS_TEXT[503] == "지금 쓸 수 없음"
    assert "`ext_not_configured`" in resv["responses"]["503"]["description"]
    assert "0명 갈래에서 KOS 중복 검사에 걸리면 409, 아니면 200 이라 그 이메일이 KOS 에 있는지가 드러난다" in resv["description"]
    assert "KOS 에 등록된 띄어쓰기 그대로" in resv["description"]  # 보정 1 N2 — 공백 무시를 약속하지 않는다
    look = spec["paths"]["/api/ext/customers/lookup"]["post"]
    assert "고객이 낸 돈이 아니다" in look["description"] and "`IN_USE`" in look["description"]
    assert "부가세 포함 여부는 표기하지 않는다" in look["description"]
    assert "**모두 같은 응답**" in look["responses"]["404"]["description"]
    assert "`syncedAt`" in spec["paths"]["/api/ext/menu"]["get"]["description"]
    section = spec["info"]["description"].split("## 외부 연동 API — `/api/ext/*`\n", 1)[1]
    assert "처리하지 못한 예외 = `500 internal_error`(본문에 예외 문구 없음 · 호출 기록 1줄 · IP 카운트 안 함)" in section
    assert section.startswith("email 이 없는 기존 고객은 조회하면 `404` 다. "
                              "그 고객을 처음 예약하면 KOS 에 고객이 하나 더 생길 수 있다(데스크가 정리한다).\n"
                              "이름은 KOS 에 저장된 띄어쓰기 그대로 보내야 한다(띄어쓰기가 다르면 찾지 못해 `404`).")  # 수정 1 W2
    # 수정 1 W3 · W4 — 예약 502 · 409 kos_rejected 줄 · 조회 400 줄에 start 없음
    assert "`start`" not in look["responses"]["400"]["description"] and "`start`" in resv["responses"]["400"]["description"]
    r502 = resv["responses"]["502"]["description"]
    assert "이름 검색은 4xx 도 502" in r502 and "일정 id 없음" in r502 and "다시 읽기" not in r502
    assert "중복 검사 · 고객 만들기 · 예약 쓰기 단계" in resv["responses"]["409"]["description"]
    params = [x for p, item in spec["paths"].items() if p.startswith("/api/ext") for op in item.values()
              for x in op.get("parameters", [])]
    assert {x["name"] for x in params} == {"X-Api-Key"} and all(x["in"] == "header" for x in params)
