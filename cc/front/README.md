# cc/front — 데스크 현황판 · 직원 페이지 (Next.js)

계약: SPEC-001(§2 화면 · §5 API · §6 로그인) + `lib/types.ts`(응답 모양 — WP1↔WP3 계약 보충).
화면 정본: claude.ai/design 프로젝트 `dda9a931-…` 의 `Ceramique 현황판 v3` · `Ceramique 직원 - 로그인/의사/코디`.

## 설치 · 실행

```bash
cd cc/front
cp .env.example .env.local   # NEXT_PUBLIC_API_BASE_URL=http://localhost:8600 (cc/back)
npm install
npm run dev                  # http://localhost:3600
```

- back(`cc/back`, 포트 8600)이 먼저 떠 있어야 한다. back 주소는 `NEXT_PUBLIC_API_BASE_URL` 로만 바꾼다(빌드 때 박힌다)
- 배포용 빌드: `npm run build && npm run start` (포트 3600)
- 검증: `npx tsc --noEmit` · `npm run lint` · `npm run build`

## 화면

| 경로 | 화면 |
|---|---|
| `/login` | 직원 로그인 — 계정 목록 `GET /api/staff`, 시연 카드 3장. 비밀번호는 받기만 한다 |
| `/desk` | 데스크 현황판 — 도면 · 진행 목록(예약/현황/직원/고객) · 방 패널 · 접수 모달 · 되돌리기 · [초기화] |
| `/staff` | 직원 첫 화면 — 의사: 지금 진행 중 + 오늘 내 일정 / 코디: 지금 내원 환자 |
| `/staff/patient/[scheduleId]` | 환자 상세. 폭 760px 이상이면 목록과 나란히 |

## 구조

- `lib/api.ts` — back 호출 전부(fetch · SSE). 컴포넌트는 이 모듈만 부른다
- `lib/hooks.ts` — `useLive`(GET + SSE `state` 이벤트마다 다시 읽기) · `useSession`(localStorage, 없으면 `/login`)
- `lib/board.ts` — 현황판 시안의 화면 계산(도면 · 상태 · 대기 라벨). 상태 변경 계산은 back 몫
- 스타일: `@medisolve-ai/medikit@1.4.0`(Tailwind preset) · `pretendard` · `app/styles/ceramique-theme.css` · `medikit-patches.css`(`cc/design` 사본) · 루트 `data-product="ceramique"`
- `lib/interpret.ts` — 통역 세션(SPEC §7 · WS 계약): 마이크 → AudioWorklet 16kHz mono s16le → `WS /api/interpret`, 자막 `caption` 갱신, 번역 음성 PCM 이어 재생. 화면은 `components/staff/InterpretModal.tsx`
- 통역은 마이크가 필요해서 `http://localhost:3600` 처럼 **localhost** 로 열어야 한다(다른 주소의 http 는 브라우저가 마이크를 막는다)
