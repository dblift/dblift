from dblift.core.sql_model.sequence import Sequence
from dblift.core.sql_model.view import View


def test_view_comment_survives_model_round_trip():
    view = View(name="v", query="SELECT 1", comment="Owner's view")

    assert View.from_dict(view.to_dict()).comment == "Owner's view"
    assert View(name="v", query="SELECT 1") != view


def test_view_typed_constructor_accepts_comment():
    view = View.from_options(name="v", query="SELECT 1", comment="Owner's view")

    assert view.comment == "Owner's view"


def test_sequence_comment_survives_model_round_trip():
    sequence = Sequence(name="s", comment="Owner's sequence")

    assert Sequence.from_dict(sequence.to_dict()).comment == "Owner's sequence"
    assert Sequence(name="s") != sequence
