from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import ingest.build_kb as build_kb_module
from ingest.build_kb import CATEGORY_CANONICAL, apply_ambiguity, apply_previews, build_entries
from ingest.dedupe import build_ambiguous_clusters, find_candidate_pairs, jaccard
from ingest.html_to_text import Link, parse_answer_html
from ingest.preview import text_preview

REAL_XLSX = Path("/Users/forest/Downloads/【内】C端FAQ.xlsx")


def test_simple_paragraph():
    parsed = parse_answer_html("<p>不客气呀～能帮到您也是我最大的快乐~</p>")
    assert parsed.text == "不客气呀～能帮到您也是我最大的快乐~"
    assert parsed.image_urls == []
    assert parsed.links == []


def test_in_app_deep_link_preserved():
    html = '如开票的订单无法自助操作，可点击【<a href="cotti://invoice-request">开发票</a>】提交申请哦~'
    parsed = parse_answer_html(html)
    assert parsed.links == [Link(text="开发票", url="cotti://invoice-request")]
    assert "cotti://invoice-request" in parsed.text
    assert "开发票" in parsed.text


def test_multiple_images_order_and_no_leakage_into_text():
    html = (
        "<p>APP查询路径：</p>"
        '<img src="https://a.example/1.png">'
        "<p>小程序查询路径：</p>"
        '<img src="https://a.example/2.png">'
    )
    parsed = parse_answer_html(html)
    assert parsed.image_urls == ["https://a.example/1.png", "https://a.example/2.png"]
    assert "https://a.example" not in parsed.text
    assert "[图片]" in parsed.text


def test_category_normalization_map_covers_known_variants():
    assert CATEGORY_CANONICAL["库迪咖啡TOC/APP账户1"] == "库迪咖啡TOC/APP账户"
    assert CATEGORY_CANONICAL["库迪咖啡TOC/订单类"] == "库迪咖啡TOC/订单相关"
    assert CATEGORY_CANONICAL["库迪咖啡TOC/合作相关"] == "库迪咖啡TOC/合作类"


class _FakeEntry:
    def __init__(self, id, question, answer_text):
        self.id = id
        self.question = question
        self.answer_text = answer_text


def test_dedupe_flags_answer_differing_lookalikes_as_high_risk():
    entries = [
        _FakeEntry("A", "联名周边套餐售罄", "去别的门店买"),
        _FakeEntry("B", "联名周边商品售罄", "正在补货"),
        _FakeEntry("C", "今天天气怎么样", "不清楚哦"),
    ]
    pairs = find_candidate_pairs(entries)
    ab = [p for p in pairs if {p.id_a, p.id_b} == {"A", "B"}]
    assert ab and ab[0].answers_differ is True
    clusters = build_ambiguous_clusters(pairs)
    assert clusters["A"] == {"B"}
    assert clusters["B"] == {"A"}
    assert "C" not in clusters


def test_dedupe_does_not_flag_similar_questions_with_same_answer():
    entries = [
        _FakeEntry("A", "优惠券能否延期", "不可以延期哦"),
        _FakeEntry("B", "代金券能否延期", "不可以延期哦"),
    ]
    pairs = find_candidate_pairs(entries)
    assert pairs and pairs[0].answers_differ is False
    clusters = build_ambiguous_clusters(pairs)
    assert clusters == {}


def test_jaccard_similarity_symmetric_and_bounded():
    a, b = "联名周边套餐售罄", "联名周边商品售罄"
    assert jaccard(a, b) == jaccard(b, a)
    assert 0.0 <= jaccard(a, b) <= 1.0
    assert jaccard(a, a) == 1.0


@pytest.mark.skipif(not REAL_XLSX.exists(), reason="real source xlsx not present on this machine")
def test_real_data_flags_the_known_risk_cluster_and_applies_category_fix():
    from ingest.build_kb import load_overrides, read_rows

    overrides = load_overrides()
    rows = read_rows(str(REAL_XLSX))
    entries = build_entries(rows, overrides)
    apply_ambiguity(entries, overrides)
    by_id = {e.id: e for e in entries}

    risk_ids = {"2081585274477150208", "11067290495", "2081586938646953984", "63730228540"}
    for rid in risk_ids:
        others = set(by_id[rid].ambiguous_with)
        assert others == (risk_ids - {rid})
        assert by_id[rid].disambiguation_hint

    assert by_id["1988496532821483520"].category == "库迪咖啡TOC/订单相关"
    assert by_id["95027638717"].ambiguous_with == []


def test_text_preview_skips_short_greeting_before_splitting():
    # "您好！" alone is 2 chars before the "！" - splitting on the very first
    # sentence-ender would make the preview just the greeting.
    text = "您好！因活动火爆，周边库存紧张，您可在【潮玩】页面选购哦。后续还会补货。"
    preview = text_preview(text)
    assert preview != "您好"
    assert "潮玩" in preview or len(preview) > 6


def test_text_preview_truncates_long_first_sentence_with_ellipsis():
    text = "如需联系下单门店可通过库迪咖啡APP/小程序找到对应【订单】-点击【耳机】图标即可~"
    preview = text_preview(text, limit=20)
    assert preview.endswith("…")
    assert len(preview) == 21  # 20 chars + ellipsis


def test_text_preview_returns_whole_short_answer_unchanged():
    assert text_preview("库迪咖啡门店支持现金支付~") == "库迪咖啡门店支持现金支付~"


def test_text_preview_empty_input():
    assert text_preview("") == ""


def test_apply_previews_text_only_entries_need_no_network(monkeypatch, tmp_path):
    monkeypatch.setattr(build_kb_module, "PREVIEW_CACHE_PATH", tmp_path / "cache.json")
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    monkeypatch.delenv("ARK_VISION_MODEL", raising=False)

    entries = [
        build_kb_module.KBEntry(id="A", category="cat", question="q", answer_text="库迪咖啡门店支持现金支付~")
    ]
    asyncio.run(apply_previews(entries))
    assert entries[0].preview == "库迪咖啡门店支持现金支付~"


def test_apply_previews_uses_cache_hit_without_calling_ark(monkeypatch, tmp_path):
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(
        json.dumps({"A": {"image_urls": ["https://x/1.png"], "preview": "缓存的摘要"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(build_kb_module, "PREVIEW_CACHE_PATH", cache_path)
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    monkeypatch.delenv("ARK_VISION_MODEL", raising=False)

    entries = [
        build_kb_module.KBEntry(
            id="A", category="cat", question="q", answer_text="a", image_urls=["https://x/1.png"]
        )
    ]
    # No ARK_API_KEY set - if this tried to call the vision model it would
    # raise RuntimeError instead of returning.
    asyncio.run(apply_previews(entries))
    assert entries[0].preview == "缓存的摘要"


def test_apply_previews_raises_without_ark_credentials_for_uncached_image(monkeypatch, tmp_path):
    monkeypatch.setattr(build_kb_module, "PREVIEW_CACHE_PATH", tmp_path / "cache.json")
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    monkeypatch.delenv("ARK_VISION_MODEL", raising=False)

    entries = [
        build_kb_module.KBEntry(
            id="A", category="cat", question="q", answer_text="a", image_urls=["https://x/1.png"]
        )
    ]
    with pytest.raises(RuntimeError):
        asyncio.run(apply_previews(entries))
