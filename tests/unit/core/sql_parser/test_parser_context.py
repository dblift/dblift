from dblift.core.sql_parser.parser_context import ParserContext


def test_block_initiators_are_a_stack() -> None:
    ctx = ParserContext()
    ctx.increase_block_depth("ATOMIC")
    ctx.increase_block_depth("CASE")
    ctx.decrease_block_depth()
    assert ctx.get_block_initiator() == "ATOMIC"
    assert ctx.get_last_closed_block_initiator() == "CASE"
    ctx.decrease_block_depth()
    assert ctx.get_block_initiator() is None and ctx.block_depth == 0


def test_reset_for_new_statement_clears_the_stack() -> None:
    ctx = ParserContext()
    ctx.increase_block_depth("BEGIN")
    ctx.reset_for_new_statement()
    assert ctx.block_depth == 0 and ctx.get_block_initiator() is None
