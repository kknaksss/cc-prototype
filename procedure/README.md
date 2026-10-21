# procedure — 시술 현황판

명동 PoC v2. 간호 스테이션 시술 현황판 + 오른쪽 「호출」 탭(의국 화면). KOS **데모 지점**에 실제로 붙는다.
계약 = SPEC-003(`kknaks/kknaks_profile` `para/projects/summer-star/cc-prototype/20-spec/spec-003-procedure-board.md`).

```text
procedure/
  docker-compose.yml   # back(8700) + front(3700)
  .env.example         # 이름만 — 복사해 procedure/.env 로 채운다(gitignore)
  back/                # FastAPI · Python 3.12 · uv · SQLite
  front/               # Next.js
```

- 기능끼리 아무것도 공유하지 않는다 — `procedure/` 밖을 import 하지 않는다.

## 실행

env 는 **`procedure/.env` 하나**(gitignore). 채우는 법은 아래 「env 채우기」.

### 한 줄 — back + front

```bash
cd procedure && cp .env.example .env   # 값 채우기
docker compose up --build              # back http://localhost:8700 · front http://localhost:3700
docker compose down                    # 내리기(DB 볼륨은 남는다 · 지우려면 down -v)
```

- back 은 `procedure/.env` 를 env_file 로 읽는다.
- front 의 `NEXT_PUBLIC_API_BASE_URL` 은 **빌드 때 번들에 박힌다** — compose 가 `procedure/.env` 의 값을 `build.args` 로 넘긴다
  (비면 `http://localhost:8700`). 값을 바꾸면 `--build` 로 다시 빌드한다.

### 따로 — back

```bash
cd procedure/back
uv sync
uv run uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8700   # 앱 팩토리 · 같은 Wi-Fi 의 앱(아이폰 · 아이패드)도 붙게
uv run pytest -q && uv run ruff check .
```

back 은 `procedure/.env` → `procedure/back/.env` 순서로 읽는다(뒤가 앞을 덮고, 실제 환경변수가 둘보다 먼저 · 빈 값은 기본값).

### 따로 — front

Next 는 `procedure/front/.env*` 만 읽는다 — 루트 `procedure/.env` 를 읽지 않는다. 개별 실행 때는 `front/.env.local`(gitignore)을 만든다.

```bash
cd procedure/front
echo "NEXT_PUBLIC_API_BASE_URL=http://localhost:8700" > .env.local   # back 주소
npm install
npm run dev                                                         # http://localhost:3700
```

back(8700)이 먼저 떠 있어야 한다. `.env.local` 이 없으면 요청이 `localhost:3700/api/…` 로 가서 404 가 난다.

## env 채우기

값은 이 레포에 쓰지 않는다(public). **값을 이 README · 커밋 · 이슈에 붙이지 말 것.**

| 이름 | 어디서 |
|---|---|
| `KOS_OPEN_API_BASE` | 공개 API 운영 호스트(데모 테넌트가 그 안에 있다) — `kos-demo-api.md` §1.2 |
| `KOS_OPEN_API_KEY` | ax-clinic-project `scripts/.env` 의 **`KOS_API_tenent_dev`** 값. **`KOS_API_tenent`(운영 명동점) 금지** |
| `KOS_INTERNAL_API_BASE` | 내부 API 호스트 — `_RESUME.md` §2 「(사실) KOS 내부 로그인」 줄 |
| `KOS_SYSTEM_EMAIL` · `KOS_SYSTEM_PASSWORD` | ax-clinic-project `scripts/.env` 의 같은 이름 |
| `KOS_TENANT_ID` | 시스템 계정 `sign-in` 응답의 `data.tenantIds[]`(데모 지점 1곳) |
| `KOS_ZONE_ID` | 공개 `getZones` 의 「4층」 id — `kos-demo-api.md` §1.2 |
| `KOS_EXCLUDE_ACCOUNT_IDS` | 원장 목록에서 뺄 계정 id(「마취용」 등, 쉼표). 공개 `getAccounts` 에서 찾는다 |
| `KOS_POLL_SCHEDULE_SEC` · `KOS_POLL_MASTER_SEC` · `KOS_POLL_WINDOW` | 비우면 10 · 3600 · `09:00-21:00`(KST) |
| `CCC_ADMIN_ID` · `CCC_ADMIN_PASSWORD` | 어드민 로그인 아이디 · 비밀번호(간호 스테이션 · 의국). **로그인 = 아이디 + 비밀번호**(OQ-601) — 서버 시작 때 bcrypt 해시로 DB 에. 비면 그 계정은 못 들어온다 |
| `CCC_DOCTOR_ID` · `CCC_DOCTOR_PASSWORD` · `CCC_DOCTOR_KOS_ACCOUNT_ID` | PoC 의사 아이디 · 비밀번호 + 연결할 **KOS 데모 지점 실제 원장**의 계정 id(공개 `getAccounts` id · 원장 목록에 있는 사람 · 시스템 계정 X). 원장 목록 밖이면 의사 계정을 만들지 않는다(로그에 사유) |
| `CCC_NURSE_ID` · `CCC_NURSE_PASSWORD` · `CCC_NURSE_NAME` | PoC 간호사 아이디 · 비밀번호 · 표시 이름 |
| `APNS_KEY_PATH` · `APNS_KEY_ID` · `APNS_TEAM_ID` · `APNS_BUNDLE_ID` · `APNS_ENV` | 원장 호출 푸시(APNs 직접). `.p8` 키 파일은 **레포 밖**(경로만 env) · `APNS_ENV` = `sandbox` \| `production`(TestFlight = production). 하나라도 비면 발송을 끄고 시작 로그 1줄 — 호출 · 조작은 그대로. compose 로 띄울 때는 `APNS_KEY_HOST_PATH`(호스트 `.p8` 경로)를 넣고 `APNS_KEY_PATH=/run/secrets/apns.p8` — compose 가 그 파일 하나만 읽기 전용 마운트한다(레포 · 이미지에 키 0). 시작 로그 「APNs JWT 서명 OK」로 확인 |
| `SONIOX_API_KEY` | 통역(Soniox STT · TTS) 키 — ax-clinic-project `scripts/.env` 의 같은 이름. 비면 통역이 `no_api_key` |
| `PROC_INTERPRET_ORIGIN` | (선택) 브라우저에서 통역 WS 를 여는 허용 출처 — 비면 `PROC_FRONT_ORIGIN` |
| `PROC_SESSION_SECRET` | 아무 긴 난수(`python3 -c 'import secrets;print(secrets.token_urlsafe(32))'`) |
| `PROC_DB_PATH` · `PROC_BACK_PORT` · `PROC_FRONT_ORIGIN` | 비우면 `back/data/procedure.db` · 8700 · `http://localhost:3700`(compose 는 DB 를 볼륨 `/data` 에 둔다) |
| `PROC_FAKE_BOARD` | **개발 전용 · 배포 env 에 넣지 않는다.** `1` 이면 `/api/board` · `/stream` 이 가짜 스냅샷(front 단독 작업)이고 조작 API 는 403 `fake_board`. 평소엔 비운다 |
| `NEXT_PUBLIC_API_BASE_URL` | front → back 주소(`http://localhost:8700`). compose 는 빌드 인자로 넘기고, front 개별 실행은 `front/.env.local` 에 쓴다 |

KOS 값이 하나라도 비면 back 은 KOS 조회 · 반영 없이 뜬다(`/api/health` 의 `kos` 가 false).

## API (SPEC-003 §7)

- 계정 · 권한(SPEC-004 §3 · OQ-601): `POST /api/auth/login {id, password}` → `{token, expiresAt, id, role, name, staffId}`(role = admin | doctor | nurse) ·
  실패는 이유와 상관없이 401 `invalid_credentials`「아이디 또는 비밀번호가 맞지 않아요」 · 같은 아이디 5회 실패면 1분 429 `too_many_attempts` ·
  `GET /api/auth/me` → `{id, role, name, staffId}`. 공개 계정 목록(`/api/auth/accounts`)은 없다. 비밀번호가 있는 계정 = 어드민 · PoC 의사 · 간호사.
  토큰 claims `{sub, role, staffId, exp}` · 검증은 DB 의 지금 값(비활성 · 역할 바뀜 → 401). 계정 = admin · nurse 는 env 1행, doctor 는 원장 목록 한 명당 1행(카드는 1명)
- 수락 `POST /api/calls/{id}/accept {doctorId?}` — doctor = 자기 원장으로만(생략 가능 · 다르면 403 `doctor_forbidden` · 남의 지정 호출 403 `not_your_call`) ·
  admin = 원장을 골라 `doctorId` 필수 · nurse = 403 `role_forbidden`. 나머지 조작은 세 역할 모두. `event_log.actor` = 로그인 아이디
- `GET /api/board` — 스냅샷(`limits:{callMin, anesMin}` · 카드 `anesthesia.long` 포함) · `GET /api/board/stream?token=` — SSE
  `board` 이벤트(첫 접속 전체 1개 · 바뀔 때마다 · 조회와 상관없이 10초마다 · 15초 `: ping`). 접근 로그에는 쿼리 문자열(`token`)을 남기지 않는다
- 조작: `POST /api/visits/{id}/anesthesia/{start|end}` · `POST /api/visits/{id}/calls` · `POST /api/calls/{id}/accept` ·
  `POST /api/calls/{id}/reassign-all` · `POST /api/procedures/{id}/{start|finish}` · `POST /api/visits/{id}/home`
- 원장 호출 푸시(SPEC-004 §5-1): `POST /api/devices {token}`(세 역할 · 같은 토큰은 마지막 로그인 계정으로 옮김) · `DELETE /api/devices/{token}`(자기 것만).
  호출 · [다른 원장에게] 뒤 비동기 발송 — 전체 호출 = 의사 전원 + 관리자 · 지정 호출 = 그 원장 + 관리자 · 간호사 없음 · 누른 의사 자신 제외.
  본문 「<방> · 시술 N건 · 전체/지정 호출」(고객 이름 없음) · payload `visitId` · `callId`. 5xx · 429 · 네트워크 1회 재시도 · 410 이면 기기 삭제 · 로그엔 토큰 끝 6자리만
- 통역 `WS /api/interpret`(SPEC-004 §4 · 이전 PoC 계약) — 토큰 = 헤더 `Authorization: Bearer <토큰>`(앱) 또는 `?token=`(브라우저).
  accept 전에 검증(틀리면 핸드셰이크 403) · Origin 이 있으면 허용 출처만 · 세 역할 모두. 접근 로그에는 쿼리 문자열을 남기지 않는다
- `GET /api/health`
