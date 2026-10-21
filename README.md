# cc-prototype

고객 데모용 기능별 실험 모음. 기능 폴더 하나 = `front/`(Next.js) + `back/`(FastAPI) 한 쌍(+ 필요하면 앱).

| 기능 | 폴더 | 무엇 | 배포 |
|---|---|---|---|
| **procedure** | `procedure/` | 명동 PoC v2 — 시술 현황판(간호 스테이션 · 의국) · KOS 데모 지점 실연동 · 계정 3역할 · 통역 · 원장 호출 푸시 · iOS 앱(`procedure/app`) | **배포 중** — `https://ccc.medisolveai.xyz`(이미지 `procedure-back` · `procedure-front` · Actions `procedure-*-image.yml`) |
| cc | `_archive/cc/` | 1 · 2차 PoC — 데스크 현황판 · 직원 페이지 · 통역 · 예약관리 데모 | **아카이브 — 배포 안 함**(코드 그대로 보관 · Actions 없음) |

```text
procedure/
├── front/   # Next.js
├── back/    # FastAPI
├── app/     # Flutter(iOS)
└── docker-compose.yml
_archive/
└── cc/      # 아카이브(배포 안 함)
```

- 기능끼리는 아무것도 공유하지 않는다 — 자기 compose · DB · env · 의존성을 기능 폴더 안에 둔다.
- 기능 폴더 밖의 코드를 import 하지 않는다.
- 실행 · env 는 각 기능의 README(`procedure/README.md`).
- 문서는 `kknaks/kknaks_profile` 의 `para/projects/summer-star/cc-prototype/`.
