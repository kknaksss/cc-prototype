from fastapi import APIRouter

from app.api.deps import Actor, Ctr
from app.api.docs import INVALID, T_AUTH, UNAUTHORIZED, errors
from app.schemas.actions import LoginRequest, LoginResponse, MeResponse

router = APIRouter(prefix="/api/auth", tags=[T_AUTH])


@router.post(
    "/login", response_model=LoginResponse,
    summary="로그인 — 아이디 · 비밀번호로 토큰 받기",
    description="""
아이디 · 비밀번호를 확인하고 세션 토큰을 준다. **로그인 없이** 부른다.

- 토큰 = 서버가 서명한 문자열. 이후 요청은 헤더 `Authorization: Bearer <token>`(SSE 는 `?token=`).
- 수명 = env `PROC_SESSION_HOURS`(기본 12시간) — 만료 시각은 응답 `expiresAt`. 갱신 · 로그아웃 API 는 없다.
- 실패 이유(없는 아이디 · 틀린 비밀번호 · 비활성 계정 · 비밀번호가 설정 안 된 계정 · 서버에 서명 키가 없음)는 구분하지 않고
  모두 같은 `401 invalid_credentials` 다.
- **같은 아이디**로 5번 잇달아 실패하면 60초 동안 그 아이디는 `429 too_many_attempts`(맞는 비밀번호여도). 60초가 지나면
  실패 수를 0 부터 다시 센다 · 성공하면 실패 수를 지운다. 카운터는 서버 메모리(재시작하면 지워짐 · 파드마다 따로).
- 다섯 역할(admin · doctor · nurse · coordinator · counselor) 모두 같은 길. 부작용 = 없음(DB 쓰기 없음).
""",
    responses=errors(
        INVALID,
        (401, "invalid_credentials", "아이디 · 비밀번호가 맞지 않을 때(없는 아이디 · 비활성 · 비밀번호 미설정 계정 포함)"),
        (429, "too_many_attempts", "같은 아이디로 5번 잇달아 실패한 뒤 60초 동안"),
    ),
)
def login(body: LoginRequest, c: Ctr) -> LoginResponse:
    token, expires_at, a = c.auth.login(body.id, body.password)
    return LoginResponse(token=token, expiresAt=expires_at, id=a.login_id, role=a.role, name=a.name, staffId=a.staff_id)


@router.get(
    "/me", response_model=MeResponse,
    summary="내 계정 — 토큰의 계정 정보",
    description="""
`Authorization: Bearer` 토큰의 계정을 돌려준다(DB 의 지금 값). 다섯 역할 모두 부를 수 있다. 부작용 없음.

토큰이 살아 있는지 확인하는 데 쓸 수 있다 — 만료 · 비활성 · 역할이나 staffId 가 발급 뒤 바뀌었으면 `401 unauthorized`.
""",
    responses=errors(UNAUTHORIZED),
)
def me(actor: Actor) -> MeResponse:
    return MeResponse(id=actor.login_id, role=actor.role, name=actor.name, staffId=actor.staff_id)
