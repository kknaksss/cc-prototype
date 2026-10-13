# cc/back — cc PoC 백엔드 (SPEC-001 0.2.1)

데스크 현황판 · 직원 페이지(5직군)가 함께 보는 관제 상태(고객 · 동선 단계 · 로그)를 들고, 변경을 SSE 로 알린다.
업무 흐름의 정본은 프로필 레포 `reference/2026-10-12-cc-prototype/workflow.md`, 계약은 SPEC-001 0.2.0.
FastAPI · uv · Python 3.12 · SQLite 파일 하나(`CC_DB_PATH`). **KOS API 는 부르지 않는다** — 조작마다 KOS 반영 자리에
`## ============kos api 연동 필요 ====` 주석만 있다(`app/domain/board.py`).

## 설치

```bash
cd cc/back
cp .env.example .env      # CC_CAPTURE_DIR(캡처 절대경로) 등을 채운다 — .env 는 git 에 넣지 않는다
uv sync
```

| env | 뜻 | 기본 |
|---|---|---|
| `CC_SCENARIO_DIR` | 시나리오 파일(`seed.json` + `events/<scheduleId>.json`) — 시드 build 입력 | `data/scenario` |
| `CC_KOS_STAFF_PATH` | KOS `getAccounts` 응답 저장본(직원 · 직군). 시드 build 에만 필요 | `data/kos-staff.json` |
| `CC_CAPTURE_DIR` | (0.2.1 부터 안 씀 — 캡처는 시나리오 만들 때 researcher 가 읽는다) | — |
| `CC_BACK_PORT` | 포트 | 8600 |
| `CC_DB_PATH` | SQLite 파일(상대경로면 `cc/back` 기준). 시드는 같은 폴더 `seed.json` | `data/cc.db` |
| `CC_FRONT_ORIGIN` | CORS · 통역 WS 로 허용할 front 주소(이것 하나만) | `http://localhost:3600` |
| `SONIOX_API_KEY` | 통역 | — |

## 시드

```bash
uv run python -m app.seed build --date 2026-10-09   # 시나리오 → 개원 전: 예약 전부(booked/canceled) · 접수 · 단계 · 로그 없음
uv run python -m app.seed save                       # 「이걸 시드로」 — 지금 DB → data/seed.json (이전 것은 seed.<시각>.json)
```

- 시나리오 형식: 프로필 레포 `orchestration/work/sts-prototype/scenario-format.md`. `seed.json` = 「아침에 KOS 에서 받아 온 것」
  (예약 · 고객 · 보유 시술권 · 지난 방문 · 오늘 근무 `staffIds`), `events/<scheduleId>.json` = 「진행하다 KOS 에서 들어오는 것」
  — **상담 완료**(상담 단계 [종료] 때: 상담 기록 · 오더 메모 · 상담사가 넣은 시술(수납필요) · 결제 금액) · **결제 완료**([결제 완료] 때: 시술권) ·
  **시술 완료**(시술 단계 [종료] 때: 담당자 메모)
- 직원 = `staffIds`(+ 이벤트 상담사) · 직군 = `kos-staff.json` roleTags. `staffIds` 가 없으면 이벤트 등장 직원 + COORDINATOR 활성 직원
- [초기화] = `POST /api/admin/reset` → DB 를 `seed.json` 으로. 시각은 「지금 − 저장 때 경과」로 다시 계산한다
- `data/` 에는 실데이터(직원 실명 · 이메일 · 메모 원문)가 들어간다 — git 에 넣지 않는다(`.gitignore`). API 응답에는 이메일이 없다

## 실행

```bash
uv run uvicorn app.main:app --port 8600
```

## API (SPEC-001 0.2.0 §5 · §7)

JSON camelCase. 시각은 전부 **epoch ms**(숫자). 조작 응답은 `{"version": n}`, 실패는 4xx + `{"error": {"code", "message"}}`
(막는 조건은 400, 없는 id 는 404). 조작이 성공하면 SSE `GET /api/events` 로 `event: state` · `data: {"version": n}` → 화면은 자기 GET 을 다시 부른다.

### 값 사전

| 이름 | 값 |
|---|---|
| 직군 `role` | `의사` · `상담사` · `피부관리사` · `간호사` · `코디` (데스크 계정은 `데스크`) |
| 틀 `frame` | `assigned` 배정형(의사 · 상담사 · 피부관리사) · `rounds` 순회형(간호사 · 코디) · `desk` |
| 고객 `location` | `null`(접수 전 · 귀가) · `"reception"`(접수대기실) · 방 id(`c01`… · `t01`… · `s01`…) |
| `flowStep` | `RESERVED` `RECEPTION` `CONSULTATION_WAITING` `CONSULTATION` `PROCEDURE_WAITING` `PROCEDURE` `PROCEDURE_DONE` `COMPLETED` |
| 단계 `kind` | `consult`(상담) · `doctor_consult`(원장 상담) · `procedure`(시술 — 시술권 1장 = 한 줄) |
| 단계 `state` | `planned`(예정) · `assigned`(대기 — 배정됨) · `in_progress`(진행 중) · `done`(완료) · `skipped`(진행 안 함) |
| 고객 `status.key` | `reception`(접수 후 대기) · `wait` · `consult`(상담 · 원장 상담 진행 중) · `treat`(시술 진행 중) |
| 고객 `status.label` | 진행 중 단계 이름 · 「○○ 대기」(배정 직원) · 「다음 단계 대기」 · 「원장 대기 · 세팅 준비」 · 「귀가 대기」 · 「접수 후 대기」 |
| 고객 `status.need` | 순회형 손 필요: `next`(다음 단계 대기) · `discharge`(귀가 대기) · `null` |
| 예약 `st` | `booked` · `checked` · `canceled` |
| 단계 `paymentRequired` | `true` = 수납필요(상담사가 넣은 시술, [결제 완료] 전) |
| `unpaidAmount` | 미결제 금액(원, 정수) — 상담 완료 때 이벤트의 결제 합계, [결제 완료] 뒤 0. 고객 · 방(그 방 고객 합) · 환자 상세 |
| 단계 배정 직군 | consult → 상담사 · doctor_consult → 의사 · procedure → 의사 또는 피부관리사 |

### 읽기

`GET /api/board`

```json
{
  "rooms": [{"id": "c03", "name": "관리실 03", "col": 3, "row": 6, "cs": 1, "cap": 1, "unpaidAmount": 0},
            {"id": "reception", "name": "접수대기실", "col": 2, "row": 4, "cs": 2, "cap": 0, "unpaidAmount": 0}],
  "corridors": [{"row": 3}, {"row": 7}],
  "customers": [{
    "scheduleId": "4eea…", "name": "XIAO SI", "isNew": true, "nationality": "TW",
    "location": "c03", "prevRoom": null, "flowStep": "CONSULTATION_WAITING",
    "receptionAt": 1791875155135, "completedAt": null, "since": 1791875155147, "unpaidAmount": 0, "paid": false,
    "status": {"key": "wait", "label": "상담사A 대기", "need": null},
    "steps": [{"stepId": "st1", "order": 1, "kind": "consult", "label": "상담", "kosSequence": null, "ticketId": null,
               "assigneeId": "6a91…", "assigneeName": "상담사A", "state": "assigned",
               "assignedAt": 1791875155147, "startedAt": null, "endedAt": null, "paymentRequired": false}]
  }],
  "staff": [{"staffId": "6a91…", "name": "상담사A", "role": "상담사", "frame": "assigned",
             "work": [{"stepId": "st1", "scheduleId": "4eea…", "customerName": "XIAO SI", "location": "c03",
                       "kind": "consult", "label": "상담", "state": "assigned"}]}],
  "resv": [{"scheduleId": "4eea…", "time": "10:00", "name": "XIAO SI", "isNew": true, "nationality": "TW",
            "procedure": "", "doctor": "", "st": "checked"}],
  "version": 4,
  "now": 1791875160000
}
```

- `customers` 에는 귀가한 고객도 남는다(`location: null` · `flowStep: COMPLETED` · `status: null`)
- 예약 `procedure` · `doctor` 는 KOS 예약 칸 그대로 — 10-09 는 비어 있다(`requestedProcedures` · `reservation.doctor` 0/177)

`GET /api/staff` → `[{"staffId": "desk", "name": "데스크", "role": "데스크", "frame": "desk"}, {"staffId": "6a85…", "name": "의사A", "role": "의사", "frame": "assigned"}, …]`

`POST /api/login {"staffId": "6a85…", "password": "…"}` → `{"staffId": "6a85…", "name": "의사A", "role": "의사", "frame": "assigned", "home": "/staff"}` (비밀번호는 검증하지 않음, 데스크는 `home: "/desk"`)

`GET /api/staff/{staffId}/home` — 배정형

```json
{"frame": "assigned",
 "current": null,
 "next": [{"stepId": "st1", "scheduleId": "4eea…", "kind": "consult", "label": "상담", "state": "assigned",
           "assignedAt": 1791875155147, "startedAt": null, "endedAt": null,
           "name": "XIAO SI", "nationality": "TW", "isNew": true, "location": "c03", "time": "10:00",
           "status": {"key": "wait", "label": "상담사A 대기", "need": null}}],
 "done": []}
```

순회형

```json
{"frame": "rounds",
 "patients": [{"scheduleId": "4eea…", "name": "XIAO SI", "nationality": "TW", "isNew": true, "location": "c05",
               "prevRoom": null, "time": "10:00", "status": {"key": "wait", "label": "다음 단계 대기", "need": "next"},
               "need": "next", "since": 1791875155147,
               "procedures": [{"stepId": "st2", "label": "리쥬란 힐러 2cc", "state": "done", "assigneeName": "의사A"},
                              {"stepId": "st3", "label": "리쥬란 아이 2cc", "state": "planned", "assigneeName": null}]}],
 "summary": {"wait": 1, "consult": 0, "treat": 0, "needNext": 1, "needDischarge": 0}}
```

`GET /api/patients/{scheduleId}?staffId=…` — `staffId` 를 주면 그 직원의 버튼(`myActions`)이 온다

```json
{"scheduleId": "4eea…", "name": "XIAO SI", "nationality": "TW", "sex": "여", "age": 44, "isNew": true,
 "reservationTime": "10:00", "flowStep": "CONSULTATION_WAITING", "location": "c03", "prevRoom": null,
 "status": {"key": "wait", "label": "상담사A 대기", "need": null}, "since": 1791875155147, "leaveTime": null,
 "outTime": "1시 전 아웃 희망!!", "counselor": "상담사A", "doctors": [],
 "memoRevealed": false, "unpaidAmount": 0, "paid": false,
 "cautions": [{"text": "**1시 전 아웃 희망!!**", "source": "예약 메모"}],
 "order": null,
 "consult": null,
 "reception": {"lines": ["**1시 전 아웃 희망!!**", "", "26.10.02/본사/…"], "source": "예약 메모"},
 "chart": [{"label": "유입", "value": "본사_대만"}, {"label": "예약 그룹", "value": "중화권"}],
 "history": [{"label": "이 병원", "value": "첫 방문", "source": ""}],
 "pastSchedules": [],
 "route": [{"stepId": "st1", "order": 1, "kind": "consult", "label": "상담", "assigneeId": "6a91…", "assigneeName": "상담사A",
            "state": "assigned", "assignedAt": 1791875155147, "startedAt": null, "endedAt": null,
            "paymentRequired": false, "ticketId": null, "kosSequence": null, "memo": ""}],
 "tickets": [],
 "myActions": [{"stepId": "st1", "kind": "consult", "action": "start", "label": "상담 시작"}]}
```

- 메모 공개(§3.4 · §0-a): `reception` · 고객 메모 · 예약 메모 앞줄 주의는 처음부터. `order`(오늘 오더 `{lines, anesthesia, source}`) · `consult`(상담 요약) ·
  거기서 온 ⚠ 주의 · 타 병원 이력은 **상담 완료 이벤트 뒤**(상담 단계 [종료] 때 들어온다) — `memoRevealed` 가 그 여부
- 차트 「오늘 결제」 · 「서비스(0원)」는 **[결제 완료] 뒤에만**
- 재내원: `history` 에 지난 방문(`{"label": "이 병원", "value": "2026-09-20 · 리쥬란 힐러 2cc", "source": "지난 방문"}`) ·
  `pastSchedules: [{"date": "2026-09-20", "consult": {lines, source} | null, "order": {lines, source} | null, "procedures": ["리쥬란 힐러 2cc"], "synthetic": true}]`(최근 순) ·
  `tickets: [{"name", "left", "total"}]`(보유 시술권 AVAILABLE)
- `source` 는 칸 이름만(「오더 메모」 · 「상담 메모」 · 「예약 메모」 · 「고객 메모」 · 「오더 메모 · 상담 메모」). `**…**` 는 원문 그대로(굵게는 front)
- 값 없는 양식 줄(「고민:」 · 「H)」 · 빈 번호 「1.」)은 빠져 있다. `route[].memo` 는 그 시술 단계가 `done` 일 때만 — 시술 완료 이벤트의 담당자 메모
- `counselor` · `doctors` 는 관제 배정(상담 단계의 상담사 · 원장 상담/시술 단계의 의사)

`GET /api/patients/{scheduleId}/procedure-candidates` — 시술 후보(§5.4): 보유 시술권(AVAILABLE 장, `source: "ticket"`) +
상담 완료 뒤 상담사가 넣은 시술 중 동선에서 빠진 것(`source: "task"`). 이미 동선에 들어간 시술권 · 순번은 빠진다

```json
[{"kind": "procedure", "label": "리쥬란 힐러 2cc", "ticketId": "t-a…", "kosSequence": null, "source": "ticket"},
 {"kind": "procedure", "label": "주름보톡스(국산)", "ticketId": "t-c…", "kosSequence": null, "source": "ticket"}]
```

상담 완료 이벤트가 들어오면 상담사가 넣은 시술은 **자동으로 동선 뒤에 붙는다**(`paymentRequired: true` · `state: planned` · `kosSequence` 유지,
ETCETERA 「방 점유/원장 상담」은 `doctor_consult` 「원장 상담」). 데스크는 확인 · 순서 · 배정만.

### 조작 — 전부 `POST`, 응답 `{"version": n}`

| 경로 | 본문 | 막는 조건(400 `code`) |
|---|---|---|
| `/api/desk/check-in` | `{"scheduleId": "4eea…", "steps": [{"kind": "consult"}, {"kind": "procedure", "label": "리쥬란 힐러 2cc", "ticketId": "98f1…", "kosSequence": 2}]}` | `already_checked_in` · `reservation_canceled` · `duplicate_ticket` · `bad_step_kind` · `label_required` |
| `/api/desk/place` | `{"scheduleId": "4eea…", "room": "c03"}` | `not_in_reception` · `not_treatment_room` · `room_full` · `room_held` |
| `/api/desk/move-sleep` | `{"scheduleId": "4eea…", "room": "s01"}` | `not_sleep_room` · `not_in_room` · `no_free_slot` |
| `/api/desk/return-room` | `{"scheduleId": "4eea…"}` | `not_in_sleep_room` |
| `/api/desk/assign` | `{"stepId": "st1", "staffId": "6a91…"}` | `role_mismatch` · `step_locked` |
| `/api/desk/unassign` | `{"stepId": "st1"}` | `not_assigned` · `step_locked` |
| `/api/desk/add-procedures` | `{"scheduleId": "4eea…", "items": [{"label": "리쥬란 아이 2cc", "ticketId": "d57d…", "kosSequence": 4}]}` | `duplicate_ticket` · `empty_items` |
| `/api/desk/reorder` | `{"scheduleId": "4eea…", "stepIds": ["st1", "st4", "st2", "st3"]}` — 단계 전부 또는 남은(planned · assigned) 단계 전부 | `step_in_progress` · `done_step_moved` · `bad_step_list` |
| `/api/desk/payment-complete` | `{"scheduleId": "4eea…"}` — 수납필요 해제 · 미결제 0 · 시술권(`ticketId`) 연결 · 차트 「오늘 결제」 공개 | `nothing_to_pay`(상담 완료 전 · 이미 완료) |
| `/api/desk/discharge` | `{"scheduleId": "4eea…"}` — 남은 단계 → `skipped`, 방 비움 | `step_in_progress` |
| `/api/desk/undo` | `{"version": 7}` — 마지막 조작만 | `undo_unavailable` |
| `/api/staff/{staffId}/start` | `{"stepId": "st1"}` | `not_my_step` · `customer_busy` |
| `/api/staff/{staffId}/finish` | `{"stepId": "st1"}` | `not_in_progress` · `not_my_step` |
| `/api/admin/reset` | 없음 | |

공통: 귀가했거나 접수 전 고객 → `customer_not_here`. 없는 id → 404(`customer_not_found` · `step_not_found` · `staff_not_found` · `reservation_not_found` · `patient_not_found`).

flowStep 전이: 접수 `RECEPTION` · 방에 넣기(상담 단계 있으면) `CONSULTATION_WAITING` · 상담/원장 상담 시작 `CONSULTATION` · 시술 시작 `PROCEDURE` ·
원장 상담 종료(남은 단계 있음) `PROCEDURE_WAITING` · 마지막 단계 종료 `PROCEDURE_DONE` · 귀가 `COMPLETED`.
상담 단계 종료 때 상담 완료 이벤트의 시술이 붙으므로, 남은 단계가 생기면 `PROCEDURE_DONE` 으로 가지 않는다.

### 통역 — `WS /api/interpret`

`cc/back/.env` 에 `SONIOX_API_KEY` 를 넣고 서버를 띄운 뒤, front 의 환자 상세에서 [통역] 을 누른다(노트북 크롬 `localhost`).
브라우저 없이 확인하려면 `ws://localhost:8600/api/interpret` 에 `{"type":"start","lang":"zh","traditional":true}` 를 보내고
PCM s16le 16kHz mono 조각을 보낸다 → `ready` · `caption`(같은 id 갱신 → `final:true`) · `audio_start`(24kHz) · PCM 바이너리 · `audio_end` 가 온다. `{"type":"stop"}` 이면 Soniox 연결을 닫고 끝낸다.
키가 없으면 `error: no_api_key`, Soniox 연결 실패는 `soniox_unavailable`, 잘못된 start 는 `bad_request`. 음색은 `Jiwoo` 하나(`app/service/interpret/soniox.py`), 자막 번체는 OpenCC `s2tw`.

## 시험

```bash
uv run pytest          # 시험 픽스처(tests/fixtures — 가짜 직원 · 가짜 고객 시나리오) + 임시 DB. 사용자 data/ 는 안 쓴다
uv run ruff check .
```
