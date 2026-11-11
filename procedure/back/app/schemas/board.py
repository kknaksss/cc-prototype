"""front 계약 — 스냅샷(SPEC-003 §7.2). SSE `board` 이벤트 본문도 이 모양 + `version`(§7.5).

필드 이름은 계약 그대로(camelCase). 이 모양을 바꾸려면 SPEC-003 §7 부터 고친다.
시각은 전부 ISO 8601 · KST 오프셋(+09:00) 문자열.
"""

from typing import Literal

from pydantic import BaseModel, Field

VisitState = Literal["waiting", "doing", "home"]
ProcState = Literal["wait", "doing", "done"]
CallKind = Literal["all", "one"]
NeedWhy = Literal["home", "anes", "call"]
KosStatus = Literal["ok", "pending", "failed"]

_T = "ISO 8601 · KST(+09:00) · 초"
_CALL_KIND = "호출 종류 — `all` 전체 호출(원장 누구나) · `one` 지정 호출(그 원장만)"


class SyncInfo(BaseModel):
    """KOS 일정 조회 상태."""

    lastOkAt: str | None = Field(description=f"마지막으로 KOS 일정 조회가 성공한 시각 — {_T}. 한 번도 성공 못 했으면 null")
    lastError: str | None = Field(description="마지막 일정 조회 실패 이유(오류 이름 · 상태). 그 뒤 성공했으면 null")
    inWindow: bool = Field(description=(
        "지금이 KOS 조회 시간(env `KOS_POLL_WINDOW` · 기본 09:00-21:00 KST · 시작 포함 · 끝 제외) 안인가. "
        "밖이면 일정 조회를 쉰다"))


class Doctor(BaseModel):
    """원장 목록의 원장 한 명."""

    id: int = Field(description="ccc staff id — 호출 지정 · 수락 `doctorId` 에 쓰는 값")
    name: str = Field(description="원장 이름")
    busy: bool = Field(description="지금 집도의로 진행(`doing`) 중인 시술이 있나")
    busyRoom: str | None = Field(description="busy 일 때 그 시술 카드의 방 이름. busy 가 아니면 null")


class Counts(BaseModel):
    """상단 숫자(카드 수)."""

    all: int = Field(description="카드 전체 수(귀가 대기 포함)")
    need: int = Field(description="「확인이 필요」(`need` 가 null 아님)인 카드 수")
    waiting: int = Field(description="상태 `waiting`(시술 대기) 카드 수")
    anes: int = Field(description="귀가 대기가 아니고 마취가 진행 중인 카드 수")
    call: int = Field(description="귀가 대기가 아니고 받을 시술이 남은 호출이 있는 카드 수")
    doing: int = Field(description="상태 `doing`(시술 진행) 카드 수")


class Limits(BaseModel):
    """「확인이 필요」 기준(분) — front 는 상수를 두지 않고 이 값만 쓴다(리뷰 S5)."""

    callMin: int = Field(description="호출 미수락 기준(분) — 지금 5. 가장 오래된 열린 호출이 이만큼 지나면 need=call")
    anesMin: int = Field(description="마취 길어짐 기준(분) — 지금 20. 진행 중 마취가 이만큼 지나면 need=anes · `long`=true")


class Room(BaseModel):
    """카드의 방."""

    id: int = Field(description="ccc 방 id. 방을 못 찾으면 0")
    title: str = Field(description="방 이름. 방을 못 찾으면 빈 문자열")
    order: int = Field(description="KOS 방 순서 값 그대로(없으면 0). 방을 못 찾으면 0")


class Customer(BaseModel):
    """카드의 고객(KOS 고객 사본)."""

    name: str = Field(description="고객 이름. 고객이 없으면 빈 문자열")
    phoneticName: str | None = Field(description="발음 표기 이름. 없으면 null")
    nationality: str | None = Field(description="국적(KOS 값 그대로). 없으면 null")
    isNew: bool = Field(description="KOS `isNew`(신규 고객) 값. 고객이 없으면 false")
    chartNumber: str | None = Field(description="KOS 차트 번호. 없으면 null")


class Anesthesia(BaseModel):
    """카드의 마취(ccc 에만 있는 기록 · KOS 반영 없음)."""

    runningSince: str | None = Field(description=f"진행 중 마취의 시작 시각 — {_T}. 진행 중 마취가 없으면 null")
    lastMinutes: int | None = Field(description="마지막으로 끝난 마취의 길이(분 · 내림). 끝난 마취가 없으면 null")
    long: bool = Field(description=(  # 진행 중 마취가 anesMin 이상(need 우선순위와 상관없이 빨강 표시)
        "진행 중 마취가 `limits.anesMin` 분 이상 지났나(`need` 우선순위와 상관없이 표시용)"))
    canStart: bool = Field(description="[마취 시작] 가능 — 귀가 대기가 아니고 진행 중 마취가 없음")
    canEnd: bool = Field(description="[마취 종료] 가능 — 귀가 대기가 아니고 진행 중 마취가 있음")


class DoctorRef(BaseModel):
    """원장(id · 이름)."""

    id: int = Field(description="ccc staff id")
    name: str = Field(description="원장 이름")


class ProcCall(BaseModel):
    """시술의 유효 호출 — 그 시술이 들어간 가장 최근 호출."""

    id: int = Field(description="호출 id")
    kind: CallKind = Field(description=_CALL_KIND)
    targetDoctorId: int | None = Field(description="지정 호출의 원장 staff id. 전체 호출은 null")
    createdAt: str = Field(description=f"호출 시각 — {_T}")
    acceptedBy: int | None = Field(description="이 호출에서 이 시술을 수락한 원장 staff id. 아직이면 null")
    acceptedAt: str | None = Field(description=f"수락 시각 — {_T}. 아직이면 null")


class Procedure(BaseModel):
    """카드의 작업(시술 · 기타 작업) 하나 — KOS 작업 1개."""

    id: int = Field(description="ccc 시술 id — 호출 `procedureIds` · `/api/procedures/{procedure_id}/…` 에 쓰는 값")
    kind: Literal["procedure", "etc"] = Field(description=(  # etc = KOS ETCETERA — 규칙은 type 무관(「방 배정」은 isRoomTask)
        "KOS 작업 type — `procedure` 시술 · `etc` 기타 작업(ETCETERA). 규칙(호출 · 시작 · 종료)은 type 과 상관없다"))
    sequence: int = Field(description="KOS 작업 sequence(그 일정 안 작업 번호)")
    title: str = Field(description="작업 이름")
    state: ProcState = Field(description=(
        "ccc 상태 — `wait` 대기 · `doing` 진행(ccc [시작] 시각 있음) · `done` 완료(KOS status DONE)"))
    # KOS 작업 status 원문(NOT_STARTED · WAITING · READY · DONE · CANCELED) — 반영 대기 중이면 ccc 가 바꾼 값
    kosStatus: str | None = Field(description=(
        "KOS 작업 status 원문(예: NOT_STARTED · WAITING · READY · DONE). ccc 조작이 KOS 반영 대기 중이면 ccc 가 미리 바꾼 값 "
        "(호출 = WAITING · 수락 = READY · 종료 = DONE · 종료 되돌리기 = READY). 없으면 null"))
    startedAt: str | None = Field(description=f"ccc [시작] 시각 — {_T}. 시작 안 했으면 null")
    completedAt: str | None = Field(description=(
        f"완료 시각 — {_T}. `state` 가 done 일 때만 값이 있다(그 밖 · 완료 시각을 모르면 null)"))
    doctor: DoctorRef | None = Field(description="집도의 — 원장 목록에 있는 집도의 첫 명. 없으면 null")
    call: ProcCall | None = Field(description="유효 호출(그 시술이 들어간 가장 최근 호출). 호출된 적 없으면 null")
    pickable: bool = Field(description="[의사 호출] 에서 고를 수 있나 — 「방 배정」 아님 · 카드가 귀가 대기 아님 · state=wait")
    canStart: bool = Field(description=(
        "[시작] 가능 — 귀가 대기 아님 · state=wait · 「방 배정」 아님 · "
        "(유효 호출이 있으면 수락됨 / 없으면 원장 목록의 집도의 있음)"))
    canFinish: bool = Field(description="[종료] 가능 — 「방 배정」 아님 · state=doing")
    isRoomTask: bool = Field(description=(  # 「방 배정」(방 붙은 ETCETERA) — front 는 그리지 않는다 · 판정에서 빠짐(2026-10-25)
        "「방 배정」 작업인가(방이 붙은 기타 작업이면서 ccc 가 호출한 적 없음). front 는 그리지 않는다 · "
        "호출 · 시작 · 종료 · 전부 완료 · 수납 판정에서 빠진다"))
    # 되돌리기 아이콘(SPEC-003 §5.13) — back 이 계산 · 「방 배정」 · 귀가 대기 카드는 늘 false(기본값 false — 가짜 보드 예시용)
    canUndoStart: bool = Field(False, description="[시작] 되돌리기 가능 — 귀가 대기 아님 · 「방 배정」 아님 · state=doing")
    canUndoFinish: bool = Field(False, description=(
        "[종료] 되돌리기 가능 — 귀가 대기 아님 · 「방 배정」 아님 · state=done · ccc [시작] 시각이 있음"))


class Need(BaseModel):
    """「확인이 필요」 — 한 카드에 하나(귀가 대기 전 → 마취 → 호출 순으로 앞의 것)."""

    why: NeedWhy = Field(description=(
        "이유 — `home` 시술이 모두 끝나 [귀가 대기] 를 기다림 · `anes` 마취가 `anesMin` 분 이상 · "
        "`call` 가장 오래된 열린 호출이 `callMin` 분 이상 미수락"))
    since: str = Field(description=(
        f"기준 시각 — {_T}. home = 마지막 완료 시각(없으면 지금) · anes = 마취 시작 · call = 가장 오래된 열린 호출 시각"))
    limitMin: int = Field(description="기준(분) — home 0 · anes = anesMin · call = callMin")


class KosFailure(BaseModel):
    """KOS 반영 실패 하나."""

    op: str = Field(description="실패한 KOS 명령 이름(경로 마지막 조각, 예: `change-tasks-doctors` · `change-flow-step`)")
    error: str | None = Field(description=(
        "마지막 오류 문구(서버가 적은 글 그대로). 예: KOS 응답 오류 `HTTP <상태> <KOS 오류 이름>` · 네트워크 `network <예외>` · "
        "KOS 로그인 실패 문구(「시스템 계정 id 없음(sign-in 실패)」 등) · 보낸 뒤 확인에서 「KOS 값이 바뀌지 않음」 · "
        "앞 op 실패로 막힘 「앞 op 실패로 보내지 않음」 · 그 밖 예외는 예외 클래스 이름. 없으면 null"))


class KosState(BaseModel):
    """카드의 KOS 반영 상태."""

    status: KosStatus = Field(description=(
        "`failed` 반영 실패가 남아 있음(그 카드의 마지막 확인된 op 뒤의 실패) · "
        "`pending` 보내는 중 · 확인 대기 op 있음 · `ok` 그 밖"))
    failed: list[KosFailure] = Field(description="남아 있는 반영 실패(op 순서). 그 카드의 뒤 op 이 확인되면 사라진다")


class Card(BaseModel):
    """카드 하나 = 오늘 시술 일정(visit) 하나."""

    visitId: int = Field(description="ccc visit id — `/api/visits/{visit_id}/…` 에 쓰는 값")
    room: Room = Field(description="방")
    inAt: str | None = Field(description=f"방 배정(입실) 시각 — {_T}. 없으면 null")
    homeAt: str | None = Field(description=f"귀가 대기가 된 시각 — {_T}. 귀가 대기가 아니면 null")
    customer: Customer = Field(description="고객")
    state: VisitState = Field(description=(
        "고객 단계 — `waiting` 시술 대기(KOS PROCEDURE_WAITING) · `doing` 시술 진행(PROCEDURE) · "
        "`home` 귀가 대기(PROCEDURE_DONE)"))
    paymentRequired: bool = Field(description="시술(「방 배정」 제외) 중 KOS `paymentRequired` 인 것이 있나")
    orderMemo: str | None = Field(description="KOS 일정 오더 메모 원문. 없으면 null")
    anesthesia: Anesthesia = Field(description="마취")
    procedures: list[Procedure] = Field(description=(
        "작업(취소 아닌 KOS 작업 전부 · 「방 배정」 포함). 순서 = 완료(완료 시각 순) → 진행 → 대기(각각 sequence 순)"))
    canCall: bool = Field(description="[의사 호출] 가능 — 귀가 대기 아님 · 전부 완료 아님 · pickable 시술이 1개 이상")
    canHome: bool = Field(description="[귀가 대기] 가능 — 귀가 대기 아님 · 시술(「방 배정」 제외)이 1개 이상이고 모두 완료")
    need: Need | None = Field(description="「확인이 필요」. 해당 없으면 null(귀가 대기 카드는 늘 null)")
    kos: KosState = Field(description="KOS 반영 상태")


class CallCustomer(BaseModel):
    """호출 목록의 고객."""

    name: str = Field(description="고객 이름. 고객이 없으면 빈 문자열")
    nationality: str | None = Field(description="국적(KOS 값 그대로). 없으면 null")


class CallProcedure(BaseModel):
    """호출에서 아직 받을 시술."""

    id: int = Field(description="ccc 시술 id")
    title: str = Field(description="시술 이름")


class OpenCall(BaseModel):
    """받을 시술이 남은 호출."""

    callId: int = Field(description="호출 id — `/api/calls/{call_id}/…` 에 쓰는 값")
    visitId: int = Field(description="카드(visit) id")
    room: Room = Field(description="카드 방")
    customer: CallCustomer = Field(description="고객")
    kind: CallKind = Field(description=_CALL_KIND)
    targetDoctorId: int | None = Field(description="지정 호출의 원장 staff id. 전체 호출은 null")
    createdAt: str = Field(description=f"호출 시각 — {_T}")
    procedures: list[CallProcedure] = Field(description=(
        "아직 수락 안 된 대기 시술(이 호출이 유효 호출인 것만) — KOS sequence 순. 비지 않는다"))


class RecentAccept(BaseModel):
    """최근 수락 한 건."""

    at: str = Field(description=f"수락 시각 — {_T}")
    room: str = Field(description="카드 방 이름. 못 찾으면 빈 문자열")
    doctorName: str = Field(description="수락한 원장 이름. 못 찾으면 빈 문자열")
    count: int = Field(description="그때 수락된 시술 수")


class BoardSnapshot(BaseModel):
    """현황판 전체 스냅샷 — 화면은 이 값만으로 그린다(규칙 계산은 서버)."""

    now: str = Field(description=f"스냅샷을 만든 서버 시각 — {_T}")
    sync: SyncInfo = Field(description="KOS 일정 조회 상태")
    doctors: list[Doctor] = Field(description="원장 목록 — 비어 있는(busy=false) 원장 먼저, 같은 묶음 안은 이름 순")
    counts: Counts = Field(description="상단 숫자")
    limits: Limits = Field(description="「확인이 필요」 기준(분)")
    cards: list[Card] = Field(description=(
        "오늘 카드 — 배열 순서 = 화면 순서: ① 오늘(KST) 저장된 카드 순서(`PUT /api/board/order`)에 있는 카드(그 순서) → "
        "② 순서에 없는 카드(입실 순) → ③ 귀가 대기 카드(귀가 대기 시각 순)"))
    calls: list[OpenCall] = Field(description="받을 시술이 남은 호출 — 오래된 순(호출 시각 · id)")
    recentAccepts: list[RecentAccept] = Field(description="최근 수락 최대 3건 — 새것 먼저")


class BoardEvent(BoardSnapshot):
    """SSE `board` 이벤트 본문 = 스냅샷 + version(보낼 때마다 1 씩 증가)."""

    version: int = Field(description=(
        "발행 번호 — 서버가 board 를 발행할 때마다 1 씩 는다(서버 메모리 · 재시작하면 0 부터). "
        "SSE 프레임의 `id:` 줄과 같은 값"))
