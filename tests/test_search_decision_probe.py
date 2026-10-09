from scripts.run_search_decision_probe import token_summary


def test_missing_usage_is_unknown_and_partial_usage_is_identified():
    missing = token_summary([None, {}])
    assert missing["calls"] == 2
    assert missing["calls_with_usage"] == 0
    assert missing["input_tokens"] is None
    assert missing["monetary_cost"] is None
    partial = token_summary(
        [
            {"input_tokens": 30, "output_tokens": 4},
            None,
            {"prompt_tokens": 20, "completion_tokens": 6},
        ]
    )
    assert partial["calls"] == 3
    assert partial["calls_with_usage"] == 2
    assert partial["input_tokens"] == 50
    assert partial["output_tokens"] == 10
