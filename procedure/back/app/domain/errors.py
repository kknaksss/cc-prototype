"""도메인 예외 — 아래층은 HTTP 를 모르고 이것만 던진다. main 의 처리기가 `{error:{code,message}}` 로 바꾼다."""


class DomainError(Exception):
    status = 400

    def __init__(self, code: str, message: str, **extra):
        super().__init__(message)
        self.code = code
        self.message = message
        # 오류 본문에 더 싣는 키(SPEC-005 §7.1 — step · candidate · fields). None 은 싣지 않는다
        self.extra = {k: v for k, v in extra.items() if v is not None}


class BadRequest(DomainError):
    status = 400


class Unauthorized(DomainError):
    status = 401


class Forbidden(DomainError):
    status = 403


class NotFound(DomainError):
    status = 404

    def __init__(self, message: str = "없는 id 예요"):
        super().__init__("not_found", message)


class Conflict(DomainError):
    status = 409


class BadGateway(DomainError):
    status = 502

