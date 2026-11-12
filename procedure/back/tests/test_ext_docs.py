"""SPEC-008 §8 Swagger — T29(외부 tag · ExtApiKey · security · 오류 표 · 설명 문장 · 0.3.0 외부 여섯)."""

from app.api.docs import STATUS_TEXT, T_EXT
from app.openapi_docs import BEARER, EXT_KEY

OPS = {("get", "/api/ext/menu"), ("post", "/api/ext/customers/lookup"), ("post", "/api/ext/reservations"),
       ("get", "/api/ext/availability"), ("post", "/api/ext/customers/visits"), ("post", "/api/ext/customers/reservations")}
OVERLAP = "오늘 이미 시작한 일정은 과거 시술과 예약 내역 둘 다에 나온다"


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
        assert "외부 경로 전부 합산" in op["responses"]["429"]["description"]  # 고침 1 W4 — 「세 엔드포인트」 아님
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
    # 이름 · 이메일은 경로 · 질의에 없다 — 질의 칸은 가능 시간대 `date` 하나만(고침 1 W3)
    params = [((m, p), x) for p, item in spec["paths"].items() if p.startswith("/api/ext") for m, op in item.items()
              for x in op.get("parameters", [])]
    assert {(x["name"], x["in"]) for _, x in params} == {("X-Api-Key", "header"), ("date", "query")}
    assert [k for k, x in params if x["in"] != "header"] == [("get", "/api/ext/availability")]
    assert all(x["in"] in ("header", "query") for _, x in params)


def test_t29_add1_docs(client):
    """0.3.0 새 셋 — 설명 문장(가능 시간대 규칙 · 오늘 겹침 · 50 · 메모 · 의사 없음 · reservationId null · KOS 비용) · 표."""
    spec = _spec(client)
    av = spec["paths"]["/api/ext/availability"]["get"]
    vi = spec["paths"]["/api/ext/customers/visits"]["post"]
    cr = spec["paths"]["/api/ext/customers/reservations"]["post"]
    def flat(op):  # 줄바꿈 · 들여쓰기를 한 칸으로
        return " ".join(op["description"].split())

    d = flat(av)
    assert "목록에 없어도 예약이 될 수 있다" in d and "그 사이 다른 예약이 끼면 `409 slot_full`" in d
    assert "오늘(KST) ~ 오늘 + 90일" in d and "기본 예약 그룹 하나" in d and "KOS 공개 칸 정원 조회 1번" in d
    assert any(x["name"] == "date" and x["in"] == "query" and x["required"] for x in av["parameters"])
    a400 = av["responses"]["400"]["description"]  # 고침 2 W1 — 없음 = `query.date:` · 그 밖 = `date:`(SPEC §6.6 표)
    assert "`date` 없음(message `query.date: …`)" in a400 and "빈 문자열" in a400 and "(message `date: <이유>`)" in a400
    assert av["responses"]["503"]["description"].startswith(STATUS_TEXT[503])
    assert "`kos_unavailable`" in av["responses"]["502"]["description"]
    for op in (vi, cr):
        assert OVERLAP in flat(op) and "KOS 에 등록된 띄어쓰기 그대로" in flat(op)
        assert "바이트까지 같다" in flat(op) and "= 2번(`404` · `409` 이면 1번)" in flat(op)
        assert {"400", "404", "409", "502"} <= set(op["responses"])
        assert "**모두 같은 응답**" in op["responses"]["404"]["description"]
    assert "최근 50건까지" in flat(vi) and "예약 메모 · 상담 메모 · 의사 이름은 내지 않는다" in flat(vi)
    assert "**null**" in flat(cr) and "취소 · 부도 포함" in flat(cr)
    section = spec["info"]["description"].split("## 외부 연동 API — `/api/ext/*`\n", 1)[1]
    assert "**경로 여섯**" in section and "`GET /api/ext/availability?date=`" in section and "외부 경로 전부 합산" in section
    assert "셋" not in section.replace("오프셋", "")
