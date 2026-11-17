"""SPEC-008 §8 Swagger — T29(외부 tag · ExtApiKey · security · 오류 표 · 설명 문장 · 0.3.0 외부 여섯) · T70(0.4.0 열셋)."""

from app.api.docs import STATUS_TEXT, T_EXT
from app.openapi_docs import BEARER, EXT_KEY

OPS = {("get", "/api/ext/menu"), ("post", "/api/ext/customers/lookup"), ("post", "/api/ext/reservations"),
       ("get", "/api/ext/availability"), ("post", "/api/ext/customers/visits"), ("post", "/api/ext/customers/reservations"),
       # 0.4.0(charty 1차) — 일곱
       ("get", "/api/ext/reservations/board"), ("get", "/api/ext/reservations/{reservationId}"),
       ("put", "/api/ext/customers/{customerId}/language"), ("put", "/api/ext/reservations/{reservationId}/order-memo"),
       ("put", "/api/ext/reservations/{reservationId}/consultation-memo"), ("get", "/api/ext/clinic"),
       ("get", "/api/ext/clinics/{clinicId}/staff")}
STAFF_OPS = {("post", "/api/ext/customers/lookup"), ("get", "/api/ext/reservations/{reservationId}"),
             ("put", "/api/ext/customers/{customerId}/language"), ("put", "/api/ext/reservations/{reservationId}/order-memo"),
             ("put", "/api/ext/reservations/{reservationId}/consultation-memo")}
PATH_PARAMS = {("reservationId", "path"), ("customerId", "path"), ("clinicId", "path")}
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
    # 0.4.0 — 넓힘(지우지 않음): + 열람 헤더(다섯 operation 에만) · 경로 정수 칸 셋. name · email 이 질의 · 경로에 생기면 실패
    assert {(x["name"], x["in"]) for _, x in params} == {("X-Api-Key", "header"), ("date", "query"),
                                                        ("X-Ext-Staff-Id", "header")} | PATH_PARAMS
    assert [k for k, x in params if x["in"] == "query"] == [("get", "/api/ext/availability")]
    assert {k for k, x in params if x["name"] == "X-Ext-Staff-Id"} == STAFF_OPS
    assert all(x["in"] in ("header", "query", "path") for _, x in params)
    assert all(x["schema"].get("type") == "integer" for _, x in params if x["in"] == "path")


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
    assert "**경로 열셋**" in section and "`GET /api/ext/availability?date=`" in section and "외부 경로 전부 합산" in section
    assert "셋" not in section.replace("오프셋", "").replace("열셋", "").replace("쓰기 셋", "")  # 0.4.0 열셋 · 쓰기 셋


def test_t70_charty1_docs(client):
    """0.4.0 일곱 + lookup — 공통 응답 줄 · 설명 문장 · 옛 문장 없음 · 헤더 설명."""
    spec = _spec(client)
    flat = lambda t: " ".join(t.split())  # noqa: E731
    for m, p in OPS:
        op = spec["paths"][p][m]
        assert {"401", "429", "405", "500"} <= set(op["responses"]), (m, p)
        assert op["summary"] and op["description"]
    look = spec["paths"]["/api/ext/customers/lookup"]["post"]
    d = flat(look["description"])
    assert "사용 중 장만 남은 묶음도 나온다" in d and "`inUseCount`" in d and "사용 중 장도 센다" in d
    assert "`prepaidCards: null`" in d and "`partialErrors: [\"prepaidCards\"]`" in d and "`customerId`" in d
    assert "`body: …`" in flat(look["responses"]["400"]["description"])
    resp = spec["components"]["schemas"]["ExtLookupResponse"]
    for text in (d, str(resp)):
        assert "AVAILABLE` 이 0장인 묶음은 KOS 가 주지 않는다" not in text and "사용 가능한 묶음" not in text
    board = flat(spec["paths"]["/api/ext/reservations/board"]["get"]["description"])
    assert "희망 상담사" in board and "가장 늦게 배정된 방" in board and "따로 정한다" in board
    assert "화면을 자주 불러도 확인 호출은 늘지 않는다" in board
    detail = spec["paths"]["/api/ext/reservations/{reservationId}"]["get"]
    assert "과거 시술 경로" in flat(detail["description"]) and "`reservation_gone`" in detail["responses"]["404"]["description"]
    assert "`reservation_not_found`" in detail["responses"]["404"]["description"]
    lang = flat(spec["paths"]["/api/ext/customers/{customerId}/language"]["put"]["description"])
    assert "덮어쓰기 위험" in lang and "KOS 먼저" in lang
    assert "예약 메모(`reservation.memo`)와 다른 칸" in flat(
        spec["paths"]["/api/ext/reservations/{reservationId}/order-memo"]["put"]["description"])
    assert "「차트 메모」 = 이 상담 메모" in flat(
        spec["paths"]["/api/ext/reservations/{reservationId}/consultation-memo"]["put"]["description"])
    assert "전역 유일하지 않다" in flat(spec["paths"]["/api/ext/clinic"]["get"]["description"])
    staff = spec["paths"]["/api/ext/clinics/{clinicId}/staff"]["get"]
    assert "역할 이름(`roleName`)으로 구분한다" in flat(staff["description"])
    staff_doc = flat(staff["description"])
    assert "`kosAccountId`" in staff_doc and "이메일 · 실명 · KOS id 는 내지 않는다" not in staff_doc
    item = spec["components"]["schemas"]["ExtStaff"]["properties"]
    assert all(item[k].get("description") for k in ("email", "realName", "kosAccountId"))
    assert "`clinic_not_found`" in staff["responses"]["404"]["description"]
    for m, p in STAFF_OPS:
        h = next(x for x in spec["paths"][p][m]["parameters"] if x["name"] == "X-Ext-Staff-Id")
        assert "신고한 값" in h["description"] and "검증하지 않는다" in h["description"] and not h.get("required")
        assert ("없는 것으로 본다" if p.endswith("lookup") else "`400 invalid_request`") in h["description"]
    section = spec["info"]["description"].split("## 외부 연동 API — `/api/ext/*`\n", 1)[1]
    assert "`X-Ext-Staff-Id" in section and "/api/ext/clinics/{clinicId}/staff" in section
    assert "예외 — 직원 목록 `kosAccountId` 는 직원의 KOS 계정 id 문자열" in section  # 0.4.7 앱 설명 id 줄
