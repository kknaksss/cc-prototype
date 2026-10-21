# cc 디자인 시안 (참고용 사본)

구현 기준 시안 두 장과, 시안이 참조하는 파일을 원본 상대 경로 그대로 받아 둔 것이다. **코드가 아니라 참고 자료다** — 앱 빌드에 넣지 않는다.

- 원본: claude.ai/design 프로젝트 `dda9a931-097f-4780-9301-972d5ac1fc23` — 받은 날 2026-10-12
- 시안: `Ceramique 현황판 v3.dc.html`(관리자 현황판 · 데스크톱) · `Ceramique 의사 모바일.dc.html`(의사 개인 화면 · 모바일/태블릿)
- 원본이 정본이다. 시안이 바뀌면 여기를 다시 받는다(손으로 고치지 않는다).

## 받지 않은 것 · 바꾼 것

| 파일 | 상태 | 이유 |
|---|---|---|
| `_ds/…/_ds_bundle.js` | **없음** | 디자인 도구 파일 읽기 한도(256KiB)를 넘어 잘려서 저장하지 않았다. 내용은 npm `@medisolve-ai/medikit@1.4.0`(MIT) 을 브라우저 전역 하나로 묶은 것 — 구현은 이 패키지를 쓴다. 그래서 이 HTML 을 로컬에서 열면 medikit 컴포넌트(Header · Menu · Tabs · Badge · Button)가 그려지지 않는다. 화면은 원본 링크에서 본다 |
| `_ds/…/fonts/PretendardVariable.woff2` | 다른 출처 | 같은 이유로 잘려서, npm `pretendard@1.3.9` 배포본으로 받았다(OFL). 원본과 버전이 같다는 보장은 없다 |
| `_ds/…/components/ui/{Badge,Button,Header,Menu,Tabs}/` | 추가 | 시안이 쓰는 medikit 컴포넌트의 props(`.d.ts`)와 사용법(`.prompt.md`). 디자인 시스템 프로젝트 `aea7ac33-…` 에서 받았다 |
| `현황판` v1 · v2 | 받지 않음 | 사용자 지시 — 시안은 v3 와 의사 모바일 |

## 구현할 때 볼 것

- 브랜드 색: 루트에 `data-product="ceramique"` + `ceramique-theme.css` (primary `#2498bd`)
- `medikit-patches.css`: medikit 1.4.0 보정 CSS — 원본 DS 반영 요청 목록이 주석으로 들어 있다
- 시안의 데이터(환자 · 방 · 직원)는 전부 샘플이다
