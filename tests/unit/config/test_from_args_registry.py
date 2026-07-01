from config.dblift_config import DbliftConfig


def test_registry_scalar_arg_flows_through():
    assert DbliftConfig.from_args_dict({"max_retries": 9})["max_retries"] == 9
    assert DbliftConfig.from_args_dict({"strict_mode": True})["strict_mode"] is True


def test_arg_only_extras_preserved():
    assert DbliftConfig.from_args_dict({"undo": True})["undo"] is True
    assert DbliftConfig.from_args_dict({"journal_enabled": False})["journal_enabled"] is False
    assert DbliftConfig.from_args_dict({"retryable_error_categories": ["timeout"]})[
        "retryable_error_categories"
    ] == ["timeout"]


def test_empty_and_none_args_skipped():
    d = DbliftConfig.from_args_dict({"tags": "", "installed_by": None, "max_retries": 3})
    assert "tags" not in d
    assert "installed_by" not in d
    assert d["max_retries"] == 3
