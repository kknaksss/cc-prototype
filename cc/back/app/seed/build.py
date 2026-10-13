"""시드 만들기 — SPEC-001 §4.1. 캡처의 하루치를 읽어 참조 데이터 · 현황판 상태(--at 시각 T)를 만든다.

재구성은 근사다(KOS 에는 최종 시각만 있다). 규칙은 research-cc-data-fit-report §B-4 · §C-8:
- 오더 = 상담(있으면) → 원장 진료(ETCETERA 원장 상담) → 시술(PROCEDURE, sequence 순) → 진정(「진정」 작업)
- 단계 끝 시각(근사): 상담 = 첫 시술 작업 ready(시술 작업은 상담 뒤 한꺼번에 생긴다) · 원장 진료 = 첫 의사 호출
  · 시술 = 그 작업들의 completed
- 위치 = T 에 열린 작업의 방(시술 중인 작업 → 원장 상담 작업 → 그 밖의 작업 순), 없으면 라운지
"""

import copy
import re
from datetime import UTC, date, datetime

from app.domain.rooms import cap_of, map_kos_room
from app.seed.capture import KST, Capture, hhmm, kst_date, parse_ts
from app.seed.names import NAME_LINE, FakeNames, MemoScrubber, Person
from app.service.snapshot import state_to_snapshot

ANESTHESIA_ONLY = "마취용"  # D-22: 의사 칸의 계정 이름 — 직원 · 원장 표시에서 뺀다
ROLE_RANK = {"의사": 0, "상담사": 1, "코디": 2}


def _doctors(task: dict) -> list[dict]:
    return [d for d in task.get("doctors") or [] if d.get("name") and d["name"] != ANESTHESIA_ONLY]


def _alive(task: dict) -> bool:
    return task.get("status") != "CANCELED"


def _is_calm(task: dict) -> bool:
    return "진정" in (task.get("title") or "")


def _is_sleep(task: dict) -> bool:
    a = (task.get("anesthesiaType") or "").upper()
    return "SLEEP" in a or "SEDAT" in a


def _label(titles: list[str]) -> str:
    uniq = list(dict.fromkeys(t for t in titles if t))
    if not uniq:
        return "시술"
    return uniq[0] + (f" 외 {len(uniq) - 1}" if len(uniq) > 1 else "")


def build_steps(doc: dict, out_ms: int | None) -> list[dict]:
    """일정 하나의 오더 단계 + 각 단계의 근사 시각 · 담당."""
    tasks = sorted(doc.get("tasks") or [], key=lambda t: t.get("sequence") or 0)
    etc = next((t for t in tasks if t.get("type") == "ETCETERA" and _alive(t)), None)
    procs = [t for t in tasks if t.get("type") == "PROCEDURE" and _alive(t)]
    treats = [t for t in procs if not _is_calm(t)]
    calms = [t for t in procs if _is_calm(t)]
    first_ready = min((parse_ts(t.get("readyDateTimeUtc")) for t in procs if t.get("readyDateTimeUtc")), default=None)
    first_call = min((parse_ts(t.get("doctorCallDateTime")) for t in procs if t.get("doctorCallDateTime")), default=None)
    reception = parse_ts(doc.get("receptionDateTimeUtc"))
    steps: list[dict] = []
    prev_end = reception

    cons = (doc.get("consultations") or [None])[0]
    if cons:
        start = parse_ts(cons.get("consultationStartedDateTimeUtc")) or reception
        end = first_ready or (parse_ts(etc.get("completedDateTimeUtc")) if etc else None) or out_ms
        counselor = (cons.get("counselors") or [{}])[0]
        steps.append({
            "kind": "consult", "label": "상담", "role": "상담사", "start": start, "end": max(end, start) if end else None,
            "call": start, "staffId": counselor.get("id"), "room": map_kos_room((etc or {}).get("room", {}).get("title")),
            "seqs": [], "people": [counselor.get("id")] if counselor.get("id") else [],
        })
        prev_end = steps[-1]["end"]

    if etc:
        start = prev_end if cons else parse_ts(etc.get("readyDateTimeUtc"))
        end = first_call or parse_ts(etc.get("doctorCallDateTime")) or first_ready or parse_ts(etc.get("completedDateTimeUtc"))
        if end and start and end < start:
            end = start
        drs = _doctors(etc) or next((_doctors(t) for t in procs if _doctors(t)), [])
        steps.append({
            "kind": "doctor", "label": "원장 진료", "role": "의사", "start": start, "end": end, "call": None,
            "staffId": drs[0]["id"] if drs else None, "room": map_kos_room(etc.get("room", {}).get("title")),
            "seqs": [etc.get("sequence")], "people": [],
        })
        prev_end = end or prev_end

    def group_key(t: dict) -> tuple:
        drs = tuple(sorted(d["id"] for d in _doctors(t)))
        asg = tuple(sorted(a["id"] for a in t.get("assignees") or []))
        return ("의사" if drs else "코디", map_kos_room(t.get("room", {}).get("title")), drs, asg, _is_sleep(t))

    groups: list[list[dict]] = []
    for t in treats:
        if groups and group_key(groups[-1][0]) == group_key(t):
            groups[-1].append(t)
        else:
            groups.append([t])
    for g in groups + ([calms] if calms else []):
        role, room, drs, asg, sleep = group_key(g[0])
        is_calm = g is calms
        readies = [parse_ts(t.get("readyDateTimeUtc")) for t in g if t.get("readyDateTimeUtc")]
        calls = [parse_ts(t.get("doctorCallDateTime")) for t in g if t.get("doctorCallDateTime")]
        dones = [parse_ts(t.get("completedDateTimeUtc")) for t in g]
        start = max(x for x in [prev_end, min(readies, default=None)] if x is not None) if (prev_end or readies) else None
        end = None if any(x is None for x in dones) else max(dones)
        steps.append({
            "kind": "calm" if is_calm else ("sleep" if sleep else "treat"),
            "label": "진정 관리" if is_calm else _label([t.get("title", "") for t in g]),
            "role": "코디" if is_calm else role, "start": start, "end": end, "call": min(calls, default=None),
            "staffId": (drs[0] if drs else (asg[0] if asg else None)), "room": room,
            "seqs": [t.get("sequence") for t in g], "people": [],
        })
        prev_end = end or prev_end
    return steps


def _open(task: dict, t: int) -> bool:
    ready = parse_ts(task.get("readyDateTimeUtc"))
    done = parse_ts(task.get("completedDateTimeUtc"))
    return _alive(task) and ready is not None and ready <= t and (done is None or t < done)


def locate(doc: dict, t: int) -> str:
    """T 시각 고객 위치(현황판 칸 id)."""
    tasks = [x for x in doc.get("tasks") or [] if _open(x, t) and map_kos_room(x.get("room", {}).get("title"))]

    def called(x: dict) -> bool:
        c = parse_ts(x.get("doctorCallDateTime"))
        return c is not None and c <= t

    for pick in (
        lambda x: x.get("type") == "PROCEDURE" and called(x),
        lambda x: x.get("type") == "ETCETERA",
        lambda x: True,
    ):
        hit = [x for x in tasks if pick(x)]
        if hit:
            hit.sort(key=lambda x: parse_ts(x.get("readyDateTimeUtc")) or 0, reverse=True)
            return map_kos_room(hit[0]["room"]["title"])
    # 열린 작업이 없으면 라운지 — 단, 작업을 이미 마친 고객(마무리 대기)은 마지막 방에 둔다(근사, 리포트 참조)
    finished = [x for x in doc.get("tasks") or [] if _alive(x) and map_kos_room(x.get("room", {}).get("title"))
                and (parse_ts(x.get("completedDateTimeUtc")) or t + 1) <= t]
    if finished:
        finished.sort(key=lambda x: parse_ts(x.get("completedDateTimeUtc")) or 0, reverse=True)
        return map_kos_room(finished[0]["room"]["title"])
    return "lounge"


# ── 환자 상세 · 차트 재료(참조 데이터 곁) ───────────────────────────────


def _age(dob: str | None, day: date) -> int | None:
    if not dob:
        return None
    try:
        b = datetime.fromisoformat(dob.replace("Z", "+00:00").replace(" ", "T")).date()
    except ValueError:
        return None
    if b >= day:
        return None  # 이상값(생년이 그해 · 미래) — research-cc-data-fit Q10
    return day.year - b.year - ((day.month, day.day) < (b.month, b.day))


def _tickets(bundles) -> list[dict]:
    out = []
    for b in bundles or []:
        for ts in b.get("ticketSets") or []:
            tks = ts.get("tickets") or []
            left = sum(1 for x in tks if x.get("status") == "AVAILABLE")
            if not left:
                continue
            name = ts.get("title") or (ts.get("procedure") or {}).get("name") or ""
            # 만료일 · 담당 직군 · 수면 여부는 KOS 에 없다(data-fit D51) — 빈 값 · 기본값
            out.append({"name": name, "left": left, "total": len(tks), "expires": "", "role": "의사", "sleep": False})
    return out


def _prepaid(balance) -> int:
    try:
        return int(((balance or {}).get("remainingBalance") or {}).get("balance", {}).get("value") or 0)
    except (TypeError, ValueError):
        return 0


def _purchases(items: list[dict], visitor_id: str, day: date) -> list[dict]:
    out = []
    for it in items:
        if it.get("visitorId") != visitor_id or it.get("purchaseStatus") != "ACCEPTED":
            continue
        ts = parse_ts(it.get("createdDateTimeUtc"))
        if ts is None or kst_date(ts) != day:
            continue
        amount = ((it.get("cost") or {}).get("totalAmount") or {}).get("value") or 0
        out.append({"title": it.get("productOptionTitle") or it.get("productTitle") or "", "amount": int(amount)})
    return out


# ── 본체 ──────────────────────────────────────────────────────────────


def build_seed(capture: Capture, day: date, at: str) -> tuple[dict, list[str]]:
    hh, mm = (int(x) for x in at.split(":"))
    t_ms = int(datetime(day.year, day.month, day.day, hh, mm, tzinfo=KST).timestamp() * 1000)
    notes: list[str] = []

    every = capture.schedules()
    todays = [d for d in every if kst_date(parse_ts(d["reservation"]["startDateTime"])) == day]
    todays.sort(key=lambda d: (d["reservation"]["startDateTime"], d["id"]))
    if not todays:
        raise ValueError(f"{day} 일정이 캡처에 없어요")
    stats = capture.schedule_statistics()
    groups = capture.reservation_groups()
    purchase_items = capture.purchase_items()

    # 1) 이름 — 실제 이름 전부(캡처 전체) · 가짜 이름(고객 id 로 결정적)
    real: set[str] = set()
    names_by_visitor: dict[str, set[str]] = {}
    nat_by_visitor: dict[str, str] = {}
    for d in every:
        v = d["visitor"]
        ns = names_by_visitor.setdefault(v["id"], set())
        ns.update(x for x in (v.get("name"), v.get("phoneticName")) if x)
        ns.update(c["visitor"]["name"] for c in d.get("consultations") or [] if c.get("visitor", {}).get("name"))
        nat_by_visitor[v["id"]] = v.get("nationality") or ""
        real.update(ns)
        for memo in _memos(d):
            real.update(m.group(2).strip() for m in NAME_LINE.finditer(memo or "") if m.group(2).strip())
    fakes = FakeNames(real)
    for vid in sorted(names_by_visitor):
        fakes.get(vid, nat_by_visitor[vid])
    today_visitors = {d["visitor"]["id"] for d in todays}
    people = {vid: Person(vid, fakes.get(vid, nat_by_visitor[vid]), ns, vid in today_visitors)
              for vid, ns in names_by_visitor.items()}
    scrubber = MemoScrubber(list(people.values()), fakes)

    # 2) 참조 데이터(이름 치환본) · 곁 데이터
    ref_schedule: dict[str, dict] = {}
    derived: dict[str, dict] = {}
    for d in todays:
        doc = copy.deepcopy(d)
        v = doc["visitor"]
        own = people[v["id"]]
        age = _age(v.get("dateOfBirth"), day)
        v["name"] = own.fake
        v["phoneticName"] = own.fake if v.get("phoneticName") else ""
        v["phone"] = {"countryCode": "", "phoneNumber": ""}
        v["chartNumber"] = ""
        v["dateOfBirth"] = ""
        if isinstance(v.get("snsInfo"), dict):
            v["snsInfo"]["accountId"] = ""
        v["memo"] = scrubber.scrub(v.get("memo"), own)
        doc["orderMemo"] = scrubber.scrub(doc.get("orderMemo"), own)
        r = doc["reservation"]
        r["reservationMemo"] = scrubber.scrub(r.get("reservationMemo"), own)
        if isinstance(r.get("funnel"), dict):
            r["funnel"]["funnelDetail"] = scrubber.scrub(r["funnel"].get("funnelDetail"), own)
        if isinstance(doc.get("consultation"), dict):
            doc["consultation"]["consultationMemo"] = scrubber.scrub(doc["consultation"].get("consultationMemo"), own)
        for c in doc.get("consultations") or []:
            c.setdefault("visitor", {})["name"] = own.fake
            if isinstance(c.get("content"), dict):
                c["content"]["text"] = scrubber.scrub(c["content"].get("text"), own)
        for task in doc.get("tasks") or []:
            task["assigneeMemo"] = scrubber.scrub(task.get("assigneeMemo"), own)
            task["memo"] = scrubber.scrub(task.get("memo"), own)
        for ew in doc.get("etceteraWorks") or []:
            ew["memo"] = scrubber.scrub(ew.get("memo"), own)
        ref_schedule[doc["id"]] = doc

        st = stats.get(d["id"], {})
        derived[doc["id"]] = {
            "age": age,
            "firstVisit": bool(st.get("isFirstProcedureSchedule", v.get("isNew"))),
            "groupTitle": groups.get(r.get("reservationGroupId"), "") or st.get("reservationGroupTitle", ""),
            "tickets": _tickets(capture.per_visitor("getTicketBundlesQuery", d["visitor"]["id"])),
            "prepaid": _prepaid(capture.per_visitor("getVisitorPrepaidCardBalance", d["visitor"]["id"])),
            "purchases": _purchases(purchase_items, d["visitor"]["id"], day),
        }

    # 3) 직원
    staff_map: dict[str, dict] = {}

    def add_staff(p: dict, role: str) -> None:
        if not p.get("id") or not p.get("name") or p["name"] == ANESTHESIA_ONLY:
            return
        cur = staff_map.get(p["id"])
        if cur is None or ROLE_RANK[role] < ROLE_RANK[cur["role"]]:
            staff_map[p["id"]] = {"staffId": p["id"], "name": p["name"], "role": role}

    for d in todays:
        for task in d.get("tasks") or []:
            for p in _doctors(task):
                add_staff(p, "의사")
        for c in d.get("consultations") or []:
            for p in c.get("counselors") or []:
                add_staff(p, "상담사")
        for task in d.get("tasks") or []:
            for p in task.get("assignees") or []:
                add_staff(p, "코디")
        for ew in d.get("etceteraWorks") or []:
            for p in ew.get("assignees") or []:
                add_staff(p, "코디")
    staff = sorted(staff_map.values(), key=lambda s: (ROLE_RANK[s["role"]], s["name"]))
    for s in staff:
        s["queue"] = []
        s["home"] = "office" if s["role"] == "의사" else "desk"

    # 4) 현황판 상태 @ T
    customers: list[dict] = []
    resv: list[dict] = []
    history: list[dict] = []
    present_slots: dict[str, dict[str, int]] = {}
    for d in todays:
        sid = d["id"]
        doc = ref_schedule[sid]
        status = d["reservation"].get("status")
        reception = parse_ts(d.get("receptionDateTimeUtc"))
        out = parse_ts(d.get("flowStepUpdatedDateTimeUtc")) if d.get("flowStep") == "COMPLETED" else None
        steps = build_steps(d, out)
        order = [{"kind": s["kind"], "label": s["label"], "role": s["role"]} for s in steps]
        derived[sid]["plannedOrder"] = order
        derived[sid]["taskStep"] = {str(q): i for i, s in enumerate(steps) for q in s["seqs"] if q is not None}

        first_proc = next((t for t in sorted(d.get("tasks") or [], key=lambda t: t.get("sequence") or 0)
                           if t.get("type") == "PROCEDURE" and _alive(t)), None)
        n_proc = sum(1 for t in d.get("tasks") or [] if t.get("type") == "PROCEDURE" and _alive(t))
        procedure = ((first_proc or {}).get("title") or "") + (f" 외 {n_proc - 1}" if n_proc > 1 else "")
        if not procedure:
            procedure = "상담" if d.get("consultations") else "-"
        doctor = next((p["name"] for t in d.get("tasks") or [] if _alive(t) for p in _doctors(t)), "미정")
        arrived = reception is not None and reception <= t_ms
        if status == "CANCELED":
            st = "canceled"
        elif status == "NO_SHOW":
            st = "noshow"
        else:
            st = "checked" if arrived else "booked"
        resv.append({"scheduleId": sid, "time": hhmm(parse_ts(d["reservation"]["startDateTime"])),
                     "name": doc["visitor"]["name"], "procedure": procedure, "doctor": doctor, "st": st})
        if st != "checked":
            continue

        gone = out is not None and out <= t_ms
        idx = next((i for i, s in enumerate(steps) if s["end"] is None or s["end"] > t_ms), len(steps))
        for s in (steps[:idx] if not gone else steps):
            if s["end"] is None or s["end"] > t_ms:
                continue
            started = s["call"] if s["kind"] != "doctor" and s["call"] and s["call"] <= s["end"] else s["start"]
            history.append({"scheduleId": sid, "kind": s["kind"], "label": s["label"], "staffId": s["staffId"],
                            "room": s["room"], "startedAt": started or s["end"], "completedAt": s["end"]})
        cust = {"scheduleId": sid, "name": doc["visitor"]["name"], "nationality": doc["visitor"].get("nationality", ""),
                "order": order, "prev": None}
        if gone:
            customers.append({**cust, "room": None, "step": len(order), "since": out, "done": True, "doneAt": out})
            continue
        room = locate(d, t_ms)
        if idx < len(steps):
            s = steps[idx]
            since = s["call"] if s["call"] and s["call"] <= t_ms else s["start"]
        else:
            since = max((s["end"] for s in steps if s["end"]), default=reception)
        since = min(max(since or reception, reception), t_ms)
        customers.append({**cust, "room": room, "step": idx, "since": since, "done": False, "doneAt": None})

        # 직원 — 그 방에 열린 작업의 담당자 · 호출된 의사 · 진행 중 상담의 상담사
        if room == "lounge":
            continue
        slots = present_slots

        def put(staff_id: str | None, at_ms: int | None, room: str = room, slots: dict = slots) -> None:
            if staff_id and staff_id in staff_map and at_ms is not None:
                cur = slots.setdefault(staff_id, {})
                cur[room] = max(cur.get(room, 0), at_ms)

        if idx < len(steps) and steps[idx]["kind"] == "consult" and steps[idx]["start"] <= t_ms:
            for p in steps[idx]["people"]:
                put(p, steps[idx]["start"])
        for task in d.get("tasks") or []:
            if not _open(task, t_ms) or map_kos_room(task.get("room", {}).get("title")) != room:
                continue
            for a in task.get("assignees") or []:
                put(a.get("id"), parse_ts(task.get("readyDateTimeUtc")))
            call = parse_ts(task.get("doctorCallDateTime"))
            if call is not None and call <= t_ms:
                for p in _doctors(task):
                    put(p["id"], call)

    for s in staff:
        rooms = present_slots.get(s["staffId"], {})
        s["queue"] = [r for r, _ in sorted(rooms.items(), key=lambda kv: -kv[1])]

    # 시안 commit 의 큐 정리(고객 없는 방은 큐에서 뺀다)
    occ = {c["room"] for c in customers if not c["done"] and c["room"] and c["room"] != "lounge"}
    for s in staff:
        s["queue"] = [r for r in s["queue"] if r in occ]
    state = {"customers": customers, "staff": staff, "resv": resv, "history": history}

    load: dict[str, int] = {}
    for c in customers:
        if not c["done"] and c["room"] != "lounge":
            load[c["room"]] = load.get(c["room"], 0) + 1
    for rid, n in sorted(load.items()):
        if n > cap_of(rid):
            notes.append(f"{rid} 에 고객 {n}명(정원 {cap_of(rid)}) — KOS 방 겹침")

    snapshot = {
        "meta": {"date": day.isoformat(), "at": at, "atMs": t_ms, "kind": "build",
                 "builtAt": datetime.now(UTC).isoformat()},
        "reference": {"schedule": ref_schedule, "derived": derived},
        "state": state_to_snapshot(state, t_ms),
        "walkN": 0,
    }
    return snapshot, notes


def _memos(d: dict) -> list[str]:
    out = [d.get("orderMemo"), (d.get("reservation") or {}).get("reservationMemo"), (d.get("visitor") or {}).get("memo"),
           (d.get("consultation") or {}).get("consultationMemo")]
    out += [(c.get("content") or {}).get("text") for c in d.get("consultations") or []]
    out += [t.get("assigneeMemo") for t in d.get("tasks") or []]
    return [m for m in out if m]


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
AT_RE = re.compile(r"^\d{1,2}:\d{2}$")
