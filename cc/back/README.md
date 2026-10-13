# cc/back — cc PoC 백엔드

데스크 현황판 · 직원 페이지(의사 · 코디)가 함께 보는 상태를 들고, 변경을 SSE 로 알린다. 계약은 SPEC-001(§4 · §5 · §6 · §8)과 `cc/front/lib/types.ts`.
FastAPI · uv · Python 3.12 · SQLite 파일 하나(`CC_DB_PATH`). **KOS API 는 부르지 않는다** — 시드는 로컬 캡처(`CC_CAPTURE_DIR`)에서 만든다.

## 설치

```bash
cd cc/back
cp .env.example .env      # CC_CAPTURE_DIR(캡처 절대경로) 등을 채운다 — .env 는 git 에 넣지 않는다
uv sync
```

| env | 뜻 | 기본 |
|---|---|---|
| `CC_CAPTURE_DIR` | KOS 캡처 폴더(읽기만). 시드 build 에만 필요 | — |
| `CC_BACK_PORT` | 포트 | 8600 |
| `CC_DB_PATH` | SQLite 파일(상대경로면 `cc/back` 기준). 시드는 같은 폴더 `seed.json` | `data/cc.db` |
| `CC_FRONT_ORIGIN` | CORS 로 허용할 front 주소(이것 하나만) | `http://localhost:3600` |
| `SONIOX_API_KEY` | 통역(WP2) | — |

## 시드

```bash
uv run python -m app.seed build --date 2026-10-09 --at 14:45   # 캡처 → data/seed.json + DB (이전 seed.json 은 seed.<시각>.json)
uv run python -m app.seed save                                  # 「이걸 시드로」 — 지금 DB → data/seed.json (화면 버튼 아님)
```

- 화면의 [초기화] = `POST /api/admin/reset` → DB 를 `seed.json` 으로. 경과 타이머는 「지금 − 시드 때 경과」로 다시 계산한다
- `data/` 에는 실데이터(직원 실명 · 메모 원문)가 들어간다 — git 에 넣지 않는다(`.gitignore`)

## 실행

```bash
uv run uvicorn app.main:app --port 8600
```

## API (SPEC-001 §5 · §6)

| | |
|---|---|
| `GET /api/board` | customers · staff · resv · rooms(시안 LAYOUT + KOS 방 대응) · version · now |
| `GET /api/staff` · `POST /api/login {staffId}` | 계정 목록(데스크 + 의사 + 코디) · 로그인(비밀번호 미검증) |
| `GET /api/staff/{staffId}/home` | 의사 `{current, next, done[]}` / 코디 `{patients[], summary}` |
| `GET /api/patients/{scheduleId}` | 환자 상세(§5.5) |
| `GET /api/events` | SSE — 변경마다 `event: state` · `data: {"version": n}` |
| `POST /api/board/{assign,complete,remove-staff,place,check-in,undo}` | 현황판 조작 → `{version}` |
| `POST /api/staff/{staffId}/{start,finish} {scheduleId}` | 의사 진료 시작 · 완료 |
| `POST /api/admin/reset` | 초기화 |
| `WS /api/interpret` | 통역 중계(SPEC §7 · `interpret-ws-contract.md`) — Soniox STT two_way + TTS |

오류는 `{"error": {"code", "message"}}` + 4xx.

## 통역 확인

`cc/back/.env` 에 `SONIOX_API_KEY` 를 넣고 서버를 띄운 뒤, front 의 환자 상세에서 [통역] 을 누른다(노트북 크롬 `localhost`).
브라우저 없이 확인하려면 `ws://localhost:8600/api/interpret` 에 `{"type":"start","lang":"zh","traditional":true}` 를 보내고
PCM s16le 16kHz mono 조각을 보낸다 → `ready` · `caption`(같은 id 갱신 → `final:true`) · `audio_start`(24kHz) · PCM 바이너리 · `audio_end` 가 온다. `{"type":"stop"}` 이면 Soniox 연결을 닫고 끝낸다.
키가 없으면 `error: no_api_key`, Soniox 연결 실패는 `soniox_unavailable`, 잘못된 start 는 `bad_request`. 음색은 `Jiwoo` 하나(`app/service/interpret/soniox.py`), 자막 번체는 OpenCC `s2tw`.

## 시험

```bash
CC_CAPTURE_DIR=<캡처 절대경로> uv run pytest   # 캡처가 없으면 캡처 기반 시험은 건너뛴다
uv run ruff check .
```
