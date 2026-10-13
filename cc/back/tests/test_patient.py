"""환자 상세 — §5.5 · §9-4. ⚠ 주의가 오더 · 상담 사본 양쪽에서 모인다."""


def _details(client):
    b = client.get("/api/board").json()
    return {r["scheduleId"]: client.get(f"/api/patients/{r['scheduleId']}").json() for r in b["resv"]}


def test_cautions_gathered_from_both_memos(client):
    ds = _details(client)
    sources = [c["source"] for d in ds.values() for c in d["cautions"]]
    assert "오더 메모 · 상담 메모 사본" in sources  # 같은 문장은 한 번, 출처 합침
    assert "상담 메모 사본" in sources  # 상담 사본에만 있는 주의도 잡힌다(오더 메모엔 없음)
    assert "고객 메모" in sources
    for d in ds.values():
        texts = [c["text"] for c in d["cautions"]]
        assert len(texts) == len(set(texts))
        if any(c["source"] == "고객 메모" for c in d["cautions"]):
            assert d["cautions"][0]["source"] == "고객 메모"  # 맨 위
        assert all(not c["text"].endswith(("— x", "— X")) for c in d["cautions"])


def test_detail_fields(client):
    ds = _details(client)
    for d in ds.values():
        assert "chartNumber" not in d and "dateOfBirth" not in d
        assert "마취용" not in d["doctors"]
        assert all(row["value"] for row in d["chart"])  # 값 없는 줄은 숨김
        labels = {row["label"] for row in d["chart"]}
        assert not labels & {"성별", "나이", "국적", "첫 방문"}  # 상단 카드와 겹치지 않음
        assert isinstance(d["tickets"], list)
    with_out = [d for d in ds.values() if d["outTime"]]
    assert with_out and all(d["outTime"].lower() not in ("x", "") for d in with_out)
    with_order = [d for d in ds.values() if d["order"]]
    assert with_order and all(d["order"]["lines"] for d in with_order)
    assert any(d["tickets"] for d in ds.values())
    assert any(any(r["status"] == "canceled" for r in d["route"]) for d in ds.values())
