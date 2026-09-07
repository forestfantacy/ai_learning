from __future__ import annotations

from chat.escalation import detect_high_risk, is_transfer_request, reply_claims_escalation


def test_self_harm_phrase_detected():
    assert detect_high_risk("我想跳楼了") == "self_harm"


def test_regulatory_phrase_detected():
    assert detect_high_risk("我要打12315投诉你们") == "regulatory"


def test_no_high_risk_phrase_returns_none():
    assert detect_high_risk("请问怎么注销账号") is None


def test_self_harm_and_regulatory_lists_dont_cross_match():
    for phrase in ("自杀", "跳楼", "自残", "割腕", "轻生", "寻短见", "喝药", "上吊", "死在门店", "出人命", "猝死"):
        assert detect_high_risk(phrase) == "self_harm"
    for phrase in ("12315", "市场监管", "消协", "12345", "信访", "工商局", "市监局", "税务稽查", "12305", "12366", "找媒体", "投诉315"):
        assert detect_high_risk(phrase) == "regulatory"


def test_quality_complaint_phrase_detected():
    assert detect_high_risk("这个店卫生条件差，喝出了虫子") == "quality_complaint"


def test_quality_complaint_list_doesnt_cross_match_others():
    phrases = (
        "卫生条件差", "卫生太脏", "卫生不敢恭维", "食品安全问题",
        "质量有问题", "质量堪忧", "产品质量差", "产品质量太差", "产品质量非常差",
        "店员不洗手", "店员美甲", "指甲油", "偷工减料",
        "喝出了虫子", "眼睫毛", "头发", "毛发", "玻璃片", "锡纸", "螺丝",
        "小生物", "蚊子", "小飞虫", "苍蝇", "脏东西",
        "肚子", "使用过期物料", "超保质期",
    )
    for phrase in phrases:
        assert detect_high_risk(phrase) == "quality_complaint"


def test_attitude_complaint_phrase_detected():
    assert detect_high_risk("店员态度恶劣，还对我阴阳怪气") == "attitude_complaint"


def test_attitude_complaint_list_doesnt_cross_match_others():
    phrases = (
        "态度恶劣", "背后议论人", "在那摔东西", "拿东西噼里啪啦的", "脸色特难看",
        "口吐芬芳脏话", "激烈争执", "情绪激动", "恶意骚扰", "侵犯隐私",
        "阴阳怪气", "指桑骂槐", "电话骚扰", "短信骚扰", "辱骂",
    )
    for phrase in phrases:
        assert detect_high_risk(phrase) == "attitude_complaint"


def test_transfer_exact_word_alone_matches():
    assert is_transfer_request("客服") is True
    assert is_transfer_request("人工") is True


def test_transfer_exact_word_embedded_in_unrelated_sentence_does_not_match():
    assert is_transfer_request("之前客服跟我说过这个问题") is False


def test_transfer_pinyin_matches_case_insensitively():
    assert is_transfer_request("rengong") is True
    assert is_transfer_request("ZhuanRenGong") is True


def test_transfer_contains_phrase_matches_anywhere_in_sentence():
    assert is_transfer_request("喂，帮我转人工谢谢") is True


def test_unrelated_sentence_does_not_match_transfer_request():
    assert is_transfer_request("请问怎么注销账号") is False


def test_reply_claiming_escalation_is_detected():
    assert reply_claims_escalation("好的，已经为您转接人工客服，请您耐心等候。") is True


def test_normal_reply_does_not_claim_escalation():
    assert reply_claims_escalation("如需删除历史订单，您可通过APP找到对应订单。") is False
