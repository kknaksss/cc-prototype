# cc-prototype

고객 데모용 기능별 실험 모음. 기능 폴더 하나 = `front/`(Next.js) + `back/`(FastAPI) 한 쌍.

```text
sts/
├── front/
└── back/
cc/
├── front/
└── back/
```

- 기능끼리는 아무것도 공유하지 않는다 — 자기 compose · DB · env · 의존성을 기능 폴더 안에 둔다.
- 기능 폴더 밖의 코드를 import 하지 않는다.
- 문서는 `kknaks/kknaks_profile` 의 `para/projects/summer-star/cc-prototype/`.
