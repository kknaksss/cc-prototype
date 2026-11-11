"""SPEC-008 §3 · §4.1 메뉴 표 · 동기화 — T1 ~ T5(가짜 KOS · 값은 지어냄)."""

import json
import logging

from app.kos import menu_sync
from tests.ext_env import T0, fill_menu, make_ext_env, run, sample_menu, single

TABLES = ("menu_category", "menu_product", "menu_option", "menu_composition", "menu_procedure", "menu_medical_service",
          "menu_machine", "menu_medicine", "menu_target_country")


def rows(c, table, present_only=False):
    with c.repo.tx() as tx:
        return tx.menu_rows(table, present_only=present_only)


def by(c, table, key="kos_id"):
    return {r[key]: r for r in rows(c, table)}


def sync_state(c):
    with c.repo.tx() as tx:
        return tx.sync_state("menu")


# ------------------------------------------------------------------ T1 표 9 · raw 원문
def test_t1_tables_and_raw_kept(tmp_path):
    c, fake, _ = make_ext_env(tmp_path)
    m = sample_menu()
    assert {t: len(rows(c, t)) for t in TABLES} == {
        "menu_category": 3, "menu_product": 4, "menu_option": 7, "menu_composition": 2, "menu_procedure": 3,
        "menu_medical_service": 3, "menu_machine": 1, "menu_medicine": 1, "menu_target_country": 3}
    p1 = m["get-products"][0]
    prod = by(c, "menu_product")["prod-1"]
    assert json.loads(prod["raw"]) == {k: v for k, v in p1.items() if k != "options"}  # options 만 뺌 · deprecated 칸 남음
    assert "cautions" in json.loads(prod["raw"]) and list(json.loads(prod["raw"])) == [k for k in p1 if k != "options"]
    g = by(c, "menu_option")["opt-g1"]
    assert json.loads(g["raw"]) == {k: v for k, v in p1["options"][1].items() if k != "compositions"}
    s1 = by(c, "menu_option")["opt-s1"]
    assert json.loads(s1["raw"])["promotionConfigurations"] == [] and json.loads(s1["raw"])["translsMap"]["title"]
    assert (s1["type"], s1["list_price"], s1["currency"], s1["count"], s1["procedure_kos_id"], s1["seq"]) == (
        "SINGLE", 10000, "KRW", 3, "proc-1", 0)
    assert (g["count"], g["procedure_kos_id"], g["list_price"]) == (None, None, 60000)
    cons = by(c, "menu_option")["opt-c1"]
    assert (cons["list_price"], cons["currency"], cons["count"]) == (None, None, None)
    comps = sorted(rows(c, "menu_composition"), key=lambda r: r["seq"])
    assert [(x["option_kos_id"], x["seq"], x["unit_type"], x["unit_value"], x["list_price"], x["medical_service_kos_id"])
            for x in comps] == [("opt-g1", 0, "SHOT", 100.0, 40000, "ms-2"),
                                ("opt-g1", 1, "UnitType_UNKNOWN", 0.0, 20000, "ms-2")]
    assert json.loads(comps[0]["raw"]) == p1["options"][1]["compositions"][0]
    assert json.loads(by(c, "menu_product")["prod-2"]["category_kos_ids"]) == ["cat-2", "cat-1"]
    ms = by(c, "menu_medical_service")["ms-1"]
    assert (ms["code"], ms["procedure_kos_id"], ms["unit_type"], ms["unit_value"], ms["status"]) == (
        "00-X-ms-1", "proc-1", "SHOT", 300.0, "PUBLISHED")
    assert by(c, "menu_medical_service")["ms-2"]["unit_type"] is None
    countries = rows(c, "menu_target_country")
    assert sorted((r["code"], r["order"]) for r in countries) == [("ETC", 3), ("KR", 0), ("KR", 1)]  # 같은 code 두 번
    assert all(json.loads(r["raw"]) in m["get-target-countries"] for r in countries)
    assert by(c, "menu_category")["cat-h"]["opened"] == 0
    ok, err = sync_state(c)
    assert ok == T0 and err is None


# ------------------------------------------------------------------ T2 ③ 나눠 부르기 · 빠진 옵션은 이전 값
def test_t2_product_options_batched_and_missing_keep(tmp_path, monkeypatch):
    monkeypatch.setattr(menu_sync, "OPTION_BATCH", 2)
    c, fake, _ = make_ext_env(tmp_path)
    bodies = [b for p, b in fake.calls if p.endswith("get-product-options")]
    singles = ["opt-s1", "opt-del", "opt-s2", "opt-s3", "opt-s4"]  # ② 의 SINGLE(지운 옵션 포함 — KOS 가 거른다)
    assert [b["optionIds"] for b in bodies] == [singles[0:2], singles[2:4], singles[4:5]]  # N+1 … → 나눠 부름
    assert all(b["includePromotions"] is False for b in bodies)
    opts = by(c, "menu_option")
    assert {k: opts[k]["medical_service_kos_id"] for k in singles} == {
        "opt-s1": "ms-1", "opt-del": None, "opt-s2": "ms-3", "opt-s3": "ms-1", "opt-s4": "ms-1"}
    assert opts["opt-g1"]["medical_service_kos_id"] is None
    names = [p.rsplit("/", 1)[-1] for p, _ in fake.calls]
    i = names.index("get-products")
    assert names[i - 1] == "get-categories" and names[i + 1] == "get-product-options"
    # 두 번째 바퀴 — opt-s2 가 ③ 응답에서 빠짐 → 이전 값 그대로
    del fake.option_services["opt-s2"]
    assert run(c.kos.menu.run()) is True
    assert by(c, "menu_option")["opt-s2"]["medical_service_kos_id"] == "ms-3"


def test_t2_product_options_failure_keeps_values(tmp_path):
    c, fake, _ = make_ext_env(tmp_path)
    fake.option_services["opt-s1"] = {"id": "ms-2"}
    fake.fail_paths["get-product-options"] = 503
    assert run(c.kos.menu.run()) is False
    assert by(c, "menu_option")["opt-s1"]["medical_service_kos_id"] == "ms-1"
    assert "getProductOptions: HTTP 503" in sync_state(c)[1]


def test_t2_no_products_no_options_call(tmp_path):
    c, fake, _ = make_ext_env(tmp_path)
    fake.fail_paths["get-products"] = 500
    before = sum(1 for p, _ in fake.calls if p.endswith("get-product-options"))
    run(c.kos.menu.run())
    assert sum(1 for p, _ in fake.calls if p.endswith("get-product-options")) == before  # ② 실패면 ③ 안 부름


# ------------------------------------------------------------------ T3 「없음」 · 되살림
def test_t3_absent_and_revive(tmp_path):
    c, fake, _ = make_ext_env(tmp_path)
    full = sample_menu()
    menu = sample_menu()
    menu["get-products"] = [p for p in menu["get-products"] if p["id"] != "prod-2"]  # 상품 1 빠짐(옵션 opt-s2 도)
    menu["get-products"][0]["options"][1]["compositions"].pop()  # 구성 1 빠짐(seq 1)
    menu["get-target-countries"] = menu["get-target-countries"][:2]  # 타겟 국가 1 빠짐
    fill_menu(fake, menu)
    run(c.kos.menu.run())
    assert by(c, "menu_product")["prod-2"]["present"] == 0 and by(c, "menu_option")["opt-s2"]["present"] == 0
    comps = {(r["option_kos_id"], r["seq"]): r["present"] for r in rows(c, "menu_composition")}
    assert comps == {("opt-g1", 0): 1, ("opt-g1", 1): 0}
    assert sorted(r["present"] for r in rows(c, "menu_target_country")) == [0, 1, 1]
    assert len(rows(c, "menu_product")) == 4  # 행은 남는다
    fill_menu(fake, full)
    run(c.kos.menu.run())
    assert all(r["present"] == 1 for t in TABLES for r in rows(c, t))


def test_t3_kos_flags_kept_as_present(tmp_path):
    """KOS 가 행을 주며 deleted · closed · opened:false 를 단 경우 — present 1 · 표시 칸만 저장."""
    c, *_ = make_ext_env(tmp_path)
    assert by(c, "menu_product")["prod-x"]["present"] == 1 and by(c, "menu_product")["prod-x"]["closed"] == 1
    assert by(c, "menu_option")["opt-del"]["present"] == 1 and by(c, "menu_option")["opt-del"]["deleted"] == 1


# ------------------------------------------------------------------ T4 작업 실패 = 이전 값
def test_t4_failure_keeps_tables_others_applied(tmp_path, caplog):
    c, fake, _ = make_ext_env(tmp_path)
    before = {t: rows(c, t) for t in ("menu_product", "menu_option", "menu_composition")}
    menu = sample_menu()
    menu["get-procedures"].append({"id": "proc-9", "name": "새 시술"})
    menu["get-products"] = [single("opt-new", "새", 1)]  # 반영되면 안 됨
    fill_menu(fake, menu)
    fake.fail_paths["get-products"] = 503
    caplog.set_level(logging.WARNING)
    assert run(c.kos.menu.run()) is False
    assert {t: rows(c, t) for t in before} == before
    assert "proc-9" in by(c, "menu_procedure")  # 다른 작업은 반영
    ok, err = sync_state(c)
    assert err == "getProducts: HTTP 503 FakeError" and ok == T0  # 이전 성공 시각은 남는다(보정 1 N3)
    assert "fake-key" not in caplog.text and "open-" not in caplog.text and '"x"' not in caplog.text
    # 2xx 인데 data 가 배열 아님
    del fake.fail_paths["get-products"]
    fake.menu["get-products"] = {"not": "list"}
    fake.menu["get-categories"] = "x"
    run(c.kos.menu.run())
    assert {t: rows(c, t) for t in before} == before
    assert sync_state(c)[1] == "getCategories: 카테고리 응답 형식; getProducts: 상품 응답 형식"


# ------------------------------------------------------------------ T5 마스터 루프에 얹힘
def test_t5_master_once_and_startup_out_of_window(tmp_path):
    from datetime import UTC, datetime

    c, fake, _ = make_ext_env(tmp_path, startup=False)
    c.clock.set(datetime(2026, 10, 21, 13, 0, tzinfo=UTC))  # KST 22:00 — 조회 시간 밖
    run(c.kos.startup())  # 서버 시작 1회
    names = [p.rsplit("/", 1)[-1] for p, _ in fake.calls]
    assert names.count("get-categories") == 1 and names.index("get-categories") > names.index("get-etcetera-tasks")
    run(c.kos.master_once())  # 1시간 루프 — 조회 시간 밖에서도
    assert [p.rsplit("/", 1)[-1] for p, _ in fake.calls].count("get-categories") == 2
    assert len(rows(c, "menu_category")) == 3
