from web import opp_suggest


def test_opportunity_suggest_rejects_mock_market_data(monkeypatch):
    def fake_search(*args, **kwargs):
        return {"source": "mock", "products": [{"base_info": {"title": "Demo"}}]}

    monkeypatch.setattr(opp_suggest.search_products, "func", fake_search)

    result = opp_suggest.suggest_opportunities("kitchen gadget", top_n=3)

    assert result["items"] == []
    assert result["data_source"] == "mock_rejected"
    assert "示例数据" in result["error"]
