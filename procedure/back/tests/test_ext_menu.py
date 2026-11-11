"""SPEC-008 §6.3 `GET /api/ext/menu` — T6 ~ T8(+ 보정 1 N3 syncedAt)."""

import json

from tests.ext_env import H_LINKY, make_ext_env, run, sample_menu

HIDDEN = ("medicalService", "medicineAndMachines", "suppliedAmount", "vatAmount", "additional", "displayChannels", "badges",
          "caution", "cautions", "promotionConfigurations", "frequentlyUsedOption", "taxation", "taxFreeAmount")


def keys(node, out=None):
    out = set() if out is None else out
    if isinstance(node, dict):
        for k, v in node.items():
            if k != "translsMap":
                out.add(k)
                keys(v, out)
    elif isinstance(node, list):
        for v in node:
            keys(v, out)
    return out


def get(cl):
    r = cl.get("/api/ext/menu", headers=H_LINKY)
    assert r.status_code == 200
    return r.json()


def opts(menu):
    return {o["id"]: o for c in menu["categories"] for p in c["products"] for o in p["options"]}


# ------------------------------------------------------------------ T6 깊이 · 칸
def test_t6_fields_and_hidden(tmp_path):
    c, fake, cl = make_ext_env(tmp_path)
    m = get(cl)
    assert set(m) == {"syncedAt", "categories"} and m["syncedAt"] == "2026-10-21T11:00:00+09:00"
    cat = m["categories"][0]
    assert set(cat) == {"id", "name", "order", "translsMap", "products"}
    prod = cat["products"][0]
    assert set(prod) == {"id", "title", "description", "isEvent", "translsMap", "options"}
    o = opts(m)
    assert set(o["opt-s1"]) == {"id", "type", "title", "description", "translsMap", "listPriceExVat", "count", "unit",
                                "procedure", "compositions"}
    assert o["opt-s1"] | {"translsMap": None} == {
        "id": "opt-s1", "type": "SINGLE", "title": "단일1", "description": "단일1 설명", "translsMap": None,
        "listPriceExVat": {"value": 10000, "currency": "KRW"}, "count": 3, "unit": {"type": "SHOT", "value": 300.0},
        "procedure": {"id": "proc-1", "name": "시술-proc-1"}, "compositions": []}
    assert o["opt-s1"]["translsMap"] == sample_menu()["get-products"][0]["options"][0]["translsMap"]
    g = o["opt-g1"]
    assert (g["count"], g["unit"], g["procedure"]) == (None, None, None)
    assert g["compositions"] == [
        {"title": "구성A", "count": 1, "unit": {"type": "SHOT", "value": 100.0},
         "listPriceExVat": {"value": 40000, "currency": "KRW"},
         "procedure": {"id": "proc-2", "name": "시술-proc-2"}},
        {"title": "구성B", "count": 5, "unit": {"type": "UnitType_UNKNOWN", "value": 0.0},
         "listPriceExVat": {"value": 20000, "currency": "KRW"}, "procedure": {"id": "proc-3", "name": "시술-proc-3"}}]
    cons = o["opt-c1"]
    assert (cons["type"], cons["listPriceExVat"], cons["count"], cons["unit"], cons["procedure"], cons["compositions"]) == (
        "CONSULTATION", None, None, None, None, [])
    assert cons["translsMap"] == {} and cons["description"] == ""
    assert o["opt-s2"]["unit"] is None  # 진료항목 ms-3 에 단위 없음
    assert not keys(m) & set(HIDDEN)
    assert m["categories"][1]["products"][0]["isEvent"] is True and prod["isEvent"] is False


def test_t6_empty_before_sync_and_synced_at_kept(tmp_path):
    c, fake, cl = make_ext_env(tmp_path, startup=False)
    assert get(cl) == {"syncedAt": None, "categories": []}
    run(c.kos.menu.run())
    first = get(cl)["syncedAt"]
    assert first == "2026-10-21T11:00:00+09:00"
    from datetime import timedelta

    c.clock.set(c.clock.now() + timedelta(hours=1))
    fake.fail_paths["get-machines"] = 503  # 작업 하나 실패 → syncedAt 그대로(보정 1 N3)
    assert run(c.kos.menu.run()) is False
    assert get(cl)["syncedAt"] == first
    del fake.fail_paths["get-machines"]
    run(c.kos.menu.run())
    assert get(cl)["syncedAt"] == "2026-10-21T12:00:00+09:00"


# ------------------------------------------------------------------ T7 지금 있는 것만
def test_t7_only_live(tmp_path):
    c, fake, cl = make_ext_env(tmp_path)
    m = get(cl)
    assert [x["id"] for x in m["categories"]] == ["cat-1", "cat-2"]  # order 순 · 닫힌(opened false) 카테고리 없음
    assert [p["id"] for p in m["categories"][0]["products"]] == ["prod-1", "prod-2"]  # 닫힌 상품 없음 · seq 순
    assert [p["id"] for p in m["categories"][1]["products"]] == ["prod-2"]  # 카테고리 둘에 걸린 상품
    assert [o["id"] for o in m["categories"][0]["products"][0]["options"]] == ["opt-s1", "opt-g1", "opt-c1"]  # 지운 옵션 없음
    assert "opt-s4" not in opts(m) and "prod-h" not in json.dumps(m)  # 숨은 카테고리에만 걸린 상품
    # present 0(동기화에서 빠짐) · 위 층이 빠지면 아래 층도
    menu = sample_menu()
    menu["get-products"] = [p for p in menu["get-products"] if p["id"] != "prod-2"]
    menu["get-products"][0]["options"][1]["compositions"].pop()
    menu["get-categories"] = [x for x in menu["get-categories"] if x["id"] != "cat-2"]
    fake.menu.update(menu)
    run(c.kos.menu.run())
    m = get(cl)
    assert [x["id"] for x in m["categories"]] == ["cat-1"]
    assert [p["id"] for p in m["categories"][0]["products"]] == ["prod-1"]
    assert [x["title"] for x in opts(m)["opt-g1"]["compositions"]] == ["구성A"]
    with c.repo.tx() as tx:
        tx.con.execute("UPDATE menu_category SET deleted = 1 WHERE kos_id = 'cat-1'")
    assert get(cl)["categories"] == []


# ------------------------------------------------------------------ T8 정가 = 부가세 별도
def test_t8_list_price(tmp_path):
    c, fake, cl = make_ext_env(tmp_path)
    o = opts(get(cl))
    src = {x["id"]: x for p in sample_menu()["get-products"] for x in p["options"]}
    for oid in ("opt-s1", "opt-g1", "opt-s2"):
        assert o[oid]["listPriceExVat"]["value"] == src[oid]["price"]["amount"]["value"]
    assert sum(x["listPriceExVat"]["value"] for x in o["opt-g1"]["compositions"]) == o["opt-g1"]["listPriceExVat"]["value"]
    assert "listPrice" not in keys(get(cl)) and "price" not in keys(get(cl))
