"""시술 후보 = 묶음 단위 n/m(SPEC-001 0.3.0 §0-b 3 · 2).

- 보유 시술권: 시술권 묶음(세트) 하나 = 한 줄 `{name, left, total}`.
  고르면 그 묶음의 다음 AVAILABLE 1장을 단계에 연결(1회 차감)
- 오늘 결제분(상담 종료 이벤트의 시술): **동선에 붙이지 않고 후보로.** 같은 이름의 작업을 한 줄로 묶는다.
  [결제 완료] 전엔 수납필요, 뒤엔 결제 완료 이벤트의 시술권을 연결
- 원장 상담(ETCETERA): 동선에 원장 상담이 이미 있으면 후보에서 뺀다
- SPEC-002 §4(D-22): 보유 시술권 후보는 접수 전(접수 모달) · 상담 종료 뒤에만. 접수 뒤 상담 종료 전엔 없다.
  묶음의 회차가 하나라도 동선에 있으면 그 묶음 통째로 뺀다
- 보유 `n/m` 의 n 은 **완료된** 시술 단계가 쓴 회차만 빠진다(D-32 — 차감 = 시술 완료)
"""

from app.domain import board as B
from app.domain.errors import BadRequest

DOCTOR_CONSULT = "doctor_consult"


def _bundle(bundle_id: str, kind: str, name: str, members: list[dict], total: int, source: str, **extra) -> dict:
    return {"bundleId": bundle_id, "kind": kind, "name": name, "left": len(members), "total": total,
            "source": source, "members": members, **extra}


def build(derived: dict, events: dict, cust: dict | None, steps: list[dict]) -> list[dict]:
    """후보 묶음(내부용 `members` 포함 — 남은 것을 앞에서부터 쓴다)."""
    used_tickets = {s["ticketId"] for s in steps if s.get("ticketId")}
    used_seq = {s["kosSequence"] for s in steps if s.get("kosSequence") is not None}
    out: list[dict] = []
    if cust and cust.get("consultApplied"):
        done = (events or {}).get("consultationDone") or {}
        paid = bool(cust.get("paid"))
        by_seq = {str(k): v for k, v in (((events or {}).get("paymentDone") or {}).get("ticketIdsBySequence") or {}).items()}
        tasks = sorted(done.get("tasks") or [], key=lambda t: t.get("sequence") or 0)
        etc = [t for t in tasks if t.get("type") == "ETCETERA"]
        if etc and not any(s["kind"] == DOCTOR_CONSULT for s in steps):
            members = [{"kind": DOCTOR_CONSULT, "label": "원장 상담", "kosSequence": t.get("sequence"),
                        "ticketId": None, "paymentRequired": False} for t in etc if t.get("sequence") not in used_seq]
            if members:
                out.append(_bundle("today:doctor_consult", DOCTOR_CONSULT, "원장 상담", members[:1], 1, "today"))
        groups: dict[str, list[dict]] = {}
        for t in tasks:
            if t.get("type") != "ETCETERA":
                groups.setdefault(t.get("title") or "", []).append(t)
        for title, ts in groups.items():
            members = []
            for t in ts:
                seq = t.get("sequence")
                ticket = by_seq.get(str(seq)) if paid else None
                if seq in used_seq or (ticket and ticket in used_tickets):
                    continue
                members.append({"kind": "procedure", "label": title, "kosSequence": seq, "ticketId": ticket,
                                "paymentRequired": bool(t.get("paymentRequired")) and not paid})
            out.append(_bundle(f"today:{title}", "procedure", title, members, len(ts), "today",
                               paymentRequired=bool(members) and any(m["paymentRequired"] for m in members)))
    if cust and not cust.get("consultApplied"):
        return out  # 접수 뒤 상담 종료 전 — 보유 시술권은 접수 모달에서 이미 골랐다
    for ts in derived.get("tickets") or []:
        if used_tickets & set(ts["available"]):
            continue  # 같은 묶음 회차가 동선에 있다 — 하루에 같은 시술권 두 번 안 씀
        members = [{"kind": "procedure", "label": ts["name"], "kosSequence": None, "ticketId": t, "paymentRequired": False}
                   for t in ts["available"]]
        out.append(_bundle(f"ticket:{ts['bundleId']}", "procedure", ts["name"], members, ts["total"], "ticket"))
    return out


def holdings(derived: dict, steps: list[dict]) -> list[dict]:
    """보유 시술권 `n/m` — 동선에 넣은 것과 상관없이 묶음 전부. n = AVAILABLE − 완료된 단계가 쓴 회차."""
    done = B.ticket_used(steps)
    return [{"bundleId": f"ticket:{ts['bundleId']}", "name": ts["name"],
             "left": len([t for t in ts["available"] if t not in done]), "total": ts["total"]}
            for ts in derived.get("tickets") or []]


def public(bundles: list[dict]) -> list[dict]:
    return [{k: v for k, v in b.items() if k != "members"} for b in bundles]


def resolve(requests: list[dict], bundles: list[dict]) -> list[dict]:
    """요청 단계들 → 구체 단계 항목. `bundleId` 가 있으면 그 묶음의 다음 1장, 없으면 그대로(상담 · 원장 상담 직접)."""
    pool = {b["bundleId"]: list(b["members"]) for b in bundles}
    out = []
    for r in requests:
        bid = r.get("bundleId")
        if not bid:
            out.append(r)
            continue
        if bid not in pool:
            raise BadRequest("unknown_bundle", f"후보 묶음 {bid} 이 없어요")
        if not pool[bid]:
            raise BadRequest("bundle_empty", "그 묶음에 남은 회차가 없어요")
        out.append(pool[bid].pop(0))
    return out
