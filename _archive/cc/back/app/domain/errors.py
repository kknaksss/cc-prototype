"""도메인 예외 — 아래층은 HTTP 를 모르고 이것만 던진다. 라우터가 4xx 로 바꾼다."""


class DomainError(Exception):
    status = 400

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class BadRequest(DomainError):
    status = 400


class NotFound(DomainError):
    status = 404


class Conflict(DomainError):
    status = 409
