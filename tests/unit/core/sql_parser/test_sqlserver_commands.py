"""SQL Server client commands, scripting variables and lone carriage returns in batch scripts.

Expected values were recorded from the splitter this engine replaces (records as
text, line, terminator, repeat, source_start and source_end, execution strings run length
encoded, refusals as class and message); the unterminated-lexeme wording is the shared engine's.
"""

import itertools
import json
from dataclasses import replace
from pathlib import Path

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.db.plugins.sqlserver.parser.lexical_spec import SQLSERVER_SPEC

# Recorded: (name, script, outcome). Outcome: ("ok", records, strings) or ("error", class, message).
CASES = [
    (
        "row 5c",
        "SELECT 'a'\rGO",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 1: a lone carriage return is not a line break sqlcmd was measured on; end the line "
            "with a newline",
        ),
    ),
    (
        "row 5d",
        "SELECT [x]\rGO",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 1: a lone carriage return is not a line break sqlcmd was measured on; end the line "
            "with a newline",
        ),
    ),
    (
        "row 11",
        ":setvar schema dbo\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':setvar' on line 1: dblift does not run client commands",
        ),
    ),
    (
        "row 17",
        "EXIT\nSELECT 1\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 1: dblift does not run client commands",
        ),
    ),
    (
        "row 18",
        ":r include.sql\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':r' on line 1: dblift does not run client commands",
        ),
    ),
    (
        "row 19",
        "SELECT * FROM $(table)\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(table) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the "
            "text as it is",
        ),
    ),
    (
        "row 19a",
        "SELECT 1 -- $(x)\nGO",
        ("ok", [("SELECT 1 -- $(x)", 1, "GO", 1, 0, 19)], [["SELECT 1 -- $(x)", 1]]),
    ),
    (
        "row 19b",
        "SELECT '$(x)' AS s\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(x) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "row 20",
        "SELECT 'a\n:setvar x y\nb' AS s\nGO",
        (
            "ok",
            [("SELECT 'a\n:setvar x y\nb' AS s", 1, "GO", 1, 0, 32)],
            [["SELECT 'a\n:setvar x y\nb' AS s", 1]],
        ),
    ),
    (
        "row 20a",
        "SELECT 1 /*\n:setvar x y\n*/\nGO",
        (
            "ok",
            [("SELECT 1 /*\n:setvar x y\n*/", 1, "GO", 1, 0, 29)],
            [["SELECT 1 /*\n:setvar x y\n*/", 1]],
        ),
    ),
    ("row 21", ":foo\nGO", ("ok", [(":foo", 1, "GO", 1, 0, 7)], [[":foo", 1]])),
    (
        "row 22",
        "CREATE TABLE t (id INT,\n:setvar x y\n x INT)\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':setvar' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "row 24",
        "CREATE TABLE t (\n  exit INT\n)\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "row 24a",
        "CREATE TABLE t (\n  quit INT\n)\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'QUIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "row 24b",
        "CREATE TABLE t (\n  reset INT\n)\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'RESET' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "row 24c",
        "CREATE TABLE t (\n  ed INT\n)\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'ED' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "row 24d",
        "SELECT 1\nquit;\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nquit;\nSELECT 2", 1, None, 1, 0, 23)],
            [["SELECT 1\nquit;\nSELECT 2", 1]],
        ),
    ),
    (
        "colon lower setvar",
        "SELECT 1\n:setvar x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':setvar' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon upper setvar",
        "SELECT 1\n:SETVAR x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':SETVAR' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon mixed setvar",
        "SELECT 1\n:Setvar x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':Setvar' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon lower r",
        "SELECT 1\n:r x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':r' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon upper r",
        "SELECT 1\n:R x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':R' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon mixed r",
        "SELECT 1\n:R x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':R' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon lower connect",
        "SELECT 1\n:connect x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':connect' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon upper connect",
        "SELECT 1\n:CONNECT x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':CONNECT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon mixed connect",
        "SELECT 1\n:Connect x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':Connect' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon lower on",
        "SELECT 1\n:on x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':on' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon upper on",
        "SELECT 1\n:ON x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':ON' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon mixed on",
        "SELECT 1\n:On x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':On' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon lower exit",
        "SELECT 1\n:exit x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':exit' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon upper exit",
        "SELECT 1\n:EXIT x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon mixed exit",
        "SELECT 1\n:Exit x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':Exit' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon lower quit",
        "SELECT 1\n:quit x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':quit' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon upper quit",
        "SELECT 1\n:QUIT x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':QUIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon mixed quit",
        "SELECT 1\n:Quit x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':Quit' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon lower list",
        "SELECT 1\n:list x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':list' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon upper list",
        "SELECT 1\n:LIST x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':LIST' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon mixed list",
        "SELECT 1\n:List x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':List' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon lower listvar",
        "SELECT 1\n:listvar x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':listvar' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon upper listvar",
        "SELECT 1\n:LISTVAR x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':LISTVAR' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon mixed listvar",
        "SELECT 1\n:Listvar x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':Listvar' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon lower error",
        "SELECT 1\n:error x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':error' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon upper error",
        "SELECT 1\n:ERROR x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':ERROR' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon mixed error",
        "SELECT 1\n:Error x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':Error' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon lower out",
        "SELECT 1\n:out x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':out' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon upper out",
        "SELECT 1\n:OUT x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':OUT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon mixed out",
        "SELECT 1\n:Out x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':Out' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon lower perftrace",
        "SELECT 1\n:perftrace x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':perftrace' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon upper perftrace",
        "SELECT 1\n:PERFTRACE x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':PERFTRACE' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon mixed perftrace",
        "SELECT 1\n:Perftrace x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':Perftrace' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon lower help",
        "SELECT 1\n:help x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':help' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon upper help",
        "SELECT 1\n:HELP x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':HELP' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon mixed help",
        "SELECT 1\n:Help x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':Help' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon lower serverlist",
        "SELECT 1\n:serverlist x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':serverlist' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon upper serverlist",
        "SELECT 1\n:SERVERLIST x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':SERVERLIST' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon mixed serverlist",
        "SELECT 1\n:Serverlist x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':Serverlist' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon lower xml",
        "SELECT 1\n:xml x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':xml' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon upper xml",
        "SELECT 1\n:XML x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':XML' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon mixed xml",
        "SELECT 1\n:Xml x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':Xml' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon lower reset",
        "SELECT 1\n:reset x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':reset' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon upper reset",
        "SELECT 1\n:RESET x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':RESET' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon mixed reset",
        "SELECT 1\n:Reset x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':Reset' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon lower ed",
        "SELECT 1\n:ed x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':ed' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon upper ed",
        "SELECT 1\n:ED x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':ED' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "colon mixed ed",
        "SELECT 1\n:Ed x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':Ed' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "line ':setvarx'",
        "SELECT 1\n:setvarx\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n:setvarx\nSELECT 2", 1, None, 1, 0, 26)],
            [["SELECT 1\n:setvarx\nSELECT 2", 1]],
        ),
    ),
    (
        "line ':foo'",
        "SELECT 1\n:foo\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n:foo\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\n:foo\nSELECT 2", 1]],
        ),
    ),
    (
        "line ':setvar_x'",
        "SELECT 1\n:setvar_x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n:setvar_x\nSELECT 2", 1, None, 1, 0, 27)],
            [["SELECT 1\n:setvar_x\nSELECT 2", 1]],
        ),
    ),
    (
        "line ':setvar1'",
        "SELECT 1\n:setvar1\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n:setvar1\nSELECT 2", 1, None, 1, 0, 26)],
            [["SELECT 1\n:setvar1\nSELECT 2", 1]],
        ),
    ),
    (
        "line ':r2'",
        "SELECT 1\n:r2\nSELECT 2",
        ("ok", [("SELECT 1\n:r2\nSELECT 2", 1, None, 1, 0, 21)], [["SELECT 1\n:r2\nSELECT 2", 1]]),
    ),
    (
        "line ':ed$'",
        "SELECT 1\n:ed$\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n:ed$\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\n:ed$\nSELECT 2", 1]],
        ),
    ),
    (
        "line ':SetVar a b'",
        "SELECT 1\n:SetVar a b\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':SetVar' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "line ':Exit'",
        "SELECT 1\n:Exit\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':Exit' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "line ':ConNect s'",
        "SELECT 1\n:ConNect s\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':ConNect' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "line ':LISTvar'",
        "SELECT 1\n:LISTvar\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':LISTvar' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "line ':'",
        "SELECT 1\n:\nSELECT 2",
        ("ok", [("SELECT 1\n:\nSELECT 2", 1, None, 1, 0, 19)], [["SELECT 1\n:\nSELECT 2", 1]]),
    ),
    (
        "line ': setvar'",
        "SELECT 1\n: setvar\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n: setvar\nSELECT 2", 1, None, 1, 0, 26)],
            [["SELECT 1\n: setvar\nSELECT 2", 1]],
        ),
    ),
    (
        "line 'x :setvar'",
        "SELECT 1\nx :setvar\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nx :setvar\nSELECT 2", 1, None, 1, 0, 27)],
            [["SELECT 1\nx :setvar\nSELECT 2", 1]],
        ),
    ),
    (
        "line ':setvar'",
        "SELECT 1\n:setvar\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':setvar' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "line ':setvar\\tx'",
        "SELECT 1\n:setvar\tx\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':setvar' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "line ':r\\ninclude'",
        "SELECT 1\n:r\ninclude\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':r' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "line ':!!x'",
        "SELECT 1\n:!!x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':!!x' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "line ':!'",
        "SELECT 1\n:!\nSELECT 2",
        ("ok", [("SELECT 1\n:!\nSELECT 2", 1, None, 1, 0, 20)], [["SELECT 1\n:!\nSELECT 2", 1]]),
    ),
    (
        "line '!!echo hi'",
        "SELECT 1\n!!echo hi\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command '!!echo' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "line '!!'",
        "SELECT 1\n!!\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command '!!' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "line '!x'",
        "SELECT 1\n!x\nSELECT 2",
        ("ok", [("SELECT 1\n!x\nSELECT 2", 1, None, 1, 0, 20)], [["SELECT 1\n!x\nSELECT 2", 1]]),
    ),
    (
        "line '!'",
        "SELECT 1\n!\nSELECT 2",
        ("ok", [("SELECT 1\n!\nSELECT 2", 1, None, 1, 0, 19)], [["SELECT 1\n!\nSELECT 2", 1]]),
    ),
    (
        "line '!!\\nGO'",
        "SELECT 1\n!!\nGO\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command '!!' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "line 'SELECT 1\\n!!dir\\nGO'",
        "SELECT 1\nSELECT 1\n!!dir\nGO\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command '!!dir' on line 3: dblift does not run client commands",
        ),
    ),
    (
        "bare EXIT' '",
        "SELECT 1\nEXIT x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare EXIT'\\t'",
        "SELECT 1\nEXIT\tx\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare EXIT'\\r'",
        "SELECT 1\nEXIT\rx\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare EXIT'-'",
        "SELECT 1\nEXIT-x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare EXIT'='",
        "SELECT 1\nEXIT=x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare EXIT'('",
        "SELECT 1\nEXIT(x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare EXIT'['",
        "SELECT 1\nEXIT[x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        'bare EXIT"\'"',
        "SELECT 1\nEXIT'x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare EXIT'/'",
        "SELECT 1\nEXIT/x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare EXIT'.'",
        "SELECT 1\nEXIT.x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nEXIT.x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nEXIT.x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare EXIT','",
        "SELECT 1\nEXIT,x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nEXIT,x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nEXIT,x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare EXIT';'",
        "SELECT 1\nEXIT;x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nEXIT;x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nEXIT;x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare EXIT'+'",
        "SELECT 1\nEXIT+x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nEXIT+x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nEXIT+x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare EXIT')'",
        "SELECT 1\nEXIT)x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nEXIT)x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nEXIT)x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare EXIT'*'",
        "SELECT 1\nEXIT*x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nEXIT*x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nEXIT*x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare EXIT':'",
        "SELECT 1\nEXIT:x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nEXIT:x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nEXIT:x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare EXIT'|'",
        "SELECT 1\nEXIT|x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nEXIT|x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nEXIT|x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare EXIT'<'",
        "SELECT 1\nEXIT<x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nEXIT<x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nEXIT<x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare EXIT'@'",
        "SELECT 1\nEXIT@x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nEXIT@x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nEXIT@x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare EXIT'a'",
        "SELECT 1\nEXITax\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nEXITax\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nEXITax\nSELECT 2", 1]],
        ),
    ),
    (
        "bare EXIT'Z'",
        "SELECT 1\nEXITZx\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nEXITZx\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nEXITZx\nSELECT 2", 1]],
        ),
    ),
    (
        "bare EXIT'_'",
        "SELECT 1\nEXIT_x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nEXIT_x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nEXIT_x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare EXIT'9'",
        "SELECT 1\nEXIT9x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nEXIT9x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nEXIT9x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare EXIT'#'",
        "SELECT 1\nEXIT#x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nEXIT#x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nEXIT#x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare EXIT'$'",
        "SELECT 1\nEXIT$x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nEXIT$x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nEXIT$x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare EXIT''",
        "SELECT 1\nEXITx\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nEXITx\nSELECT 2", 1, None, 1, 0, 23)],
            [["SELECT 1\nEXITx\nSELECT 2", 1]],
        ),
    ),
    (
        "bare EXIT alone",
        "SELECT 1\nEXIT\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare EXIT at eof",
        "SELECT 1\nEXIT",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare exit' '",
        "SELECT 1\nexit x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare exit'\\t'",
        "SELECT 1\nexit\tx\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare exit'\\r'",
        "SELECT 1\nexit\rx\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare exit'-'",
        "SELECT 1\nexit-x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare exit'='",
        "SELECT 1\nexit=x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare exit'('",
        "SELECT 1\nexit(x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare exit'['",
        "SELECT 1\nexit[x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        'bare exit"\'"',
        "SELECT 1\nexit'x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare exit'/'",
        "SELECT 1\nexit/x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare exit'.'",
        "SELECT 1\nexit.x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nexit.x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nexit.x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare exit','",
        "SELECT 1\nexit,x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nexit,x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nexit,x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare exit';'",
        "SELECT 1\nexit;x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nexit;x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nexit;x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare exit'+'",
        "SELECT 1\nexit+x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nexit+x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nexit+x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare exit')'",
        "SELECT 1\nexit)x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nexit)x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nexit)x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare exit'*'",
        "SELECT 1\nexit*x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nexit*x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nexit*x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare exit':'",
        "SELECT 1\nexit:x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nexit:x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nexit:x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare exit'|'",
        "SELECT 1\nexit|x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nexit|x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nexit|x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare exit'<'",
        "SELECT 1\nexit<x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nexit<x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nexit<x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare exit'@'",
        "SELECT 1\nexit@x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nexit@x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nexit@x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare exit'a'",
        "SELECT 1\nexitax\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nexitax\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nexitax\nSELECT 2", 1]],
        ),
    ),
    (
        "bare exit'Z'",
        "SELECT 1\nexitZx\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nexitZx\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nexitZx\nSELECT 2", 1]],
        ),
    ),
    (
        "bare exit'_'",
        "SELECT 1\nexit_x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nexit_x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nexit_x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare exit'9'",
        "SELECT 1\nexit9x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nexit9x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nexit9x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare exit'#'",
        "SELECT 1\nexit#x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nexit#x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nexit#x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare exit'$'",
        "SELECT 1\nexit$x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nexit$x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nexit$x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare exit''",
        "SELECT 1\nexitx\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nexitx\nSELECT 2", 1, None, 1, 0, 23)],
            [["SELECT 1\nexitx\nSELECT 2", 1]],
        ),
    ),
    (
        "bare exit alone",
        "SELECT 1\nexit\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare exit at eof",
        "SELECT 1\nexit",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare Exit' '",
        "SELECT 1\nExit x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare Exit'\\t'",
        "SELECT 1\nExit\tx\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare Exit'\\r'",
        "SELECT 1\nExit\rx\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare Exit'-'",
        "SELECT 1\nExit-x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare Exit'='",
        "SELECT 1\nExit=x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare Exit'('",
        "SELECT 1\nExit(x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare Exit'['",
        "SELECT 1\nExit[x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        'bare Exit"\'"',
        "SELECT 1\nExit'x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare Exit'/'",
        "SELECT 1\nExit/x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare Exit'.'",
        "SELECT 1\nExit.x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nExit.x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nExit.x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Exit','",
        "SELECT 1\nExit,x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nExit,x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nExit,x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Exit';'",
        "SELECT 1\nExit;x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nExit;x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nExit;x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Exit'+'",
        "SELECT 1\nExit+x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nExit+x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nExit+x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Exit')'",
        "SELECT 1\nExit)x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nExit)x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nExit)x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Exit'*'",
        "SELECT 1\nExit*x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nExit*x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nExit*x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Exit':'",
        "SELECT 1\nExit:x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nExit:x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nExit:x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Exit'|'",
        "SELECT 1\nExit|x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nExit|x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nExit|x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Exit'<'",
        "SELECT 1\nExit<x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nExit<x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nExit<x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Exit'@'",
        "SELECT 1\nExit@x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nExit@x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nExit@x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Exit'a'",
        "SELECT 1\nExitax\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nExitax\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nExitax\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Exit'Z'",
        "SELECT 1\nExitZx\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nExitZx\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nExitZx\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Exit'_'",
        "SELECT 1\nExit_x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nExit_x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nExit_x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Exit'9'",
        "SELECT 1\nExit9x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nExit9x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nExit9x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Exit'#'",
        "SELECT 1\nExit#x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nExit#x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nExit#x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Exit'$'",
        "SELECT 1\nExit$x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nExit$x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nExit$x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Exit''",
        "SELECT 1\nExitx\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nExitx\nSELECT 2", 1, None, 1, 0, 23)],
            [["SELECT 1\nExitx\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Exit alone",
        "SELECT 1\nExit\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare Exit at eof",
        "SELECT 1\nExit",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare QUIT' '",
        "SELECT 1\nQUIT x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'QUIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare QUIT'\\t'",
        "SELECT 1\nQUIT\tx\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'QUIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare QUIT'\\r'",
        "SELECT 1\nQUIT\rx\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'QUIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare QUIT'-'",
        "SELECT 1\nQUIT-x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'QUIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare QUIT'='",
        "SELECT 1\nQUIT=x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'QUIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare QUIT'('",
        "SELECT 1\nQUIT(x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'QUIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare QUIT'['",
        "SELECT 1\nQUIT[x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'QUIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        'bare QUIT"\'"',
        "SELECT 1\nQUIT'x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'QUIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare QUIT'/'",
        "SELECT 1\nQUIT/x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'QUIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare QUIT'.'",
        "SELECT 1\nQUIT.x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nQUIT.x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nQUIT.x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare QUIT','",
        "SELECT 1\nQUIT,x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nQUIT,x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nQUIT,x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare QUIT';'",
        "SELECT 1\nQUIT;x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nQUIT;x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nQUIT;x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare QUIT'+'",
        "SELECT 1\nQUIT+x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nQUIT+x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nQUIT+x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare QUIT')'",
        "SELECT 1\nQUIT)x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nQUIT)x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nQUIT)x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare QUIT'*'",
        "SELECT 1\nQUIT*x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nQUIT*x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nQUIT*x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare QUIT':'",
        "SELECT 1\nQUIT:x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nQUIT:x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nQUIT:x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare QUIT'|'",
        "SELECT 1\nQUIT|x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nQUIT|x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nQUIT|x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare QUIT'<'",
        "SELECT 1\nQUIT<x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nQUIT<x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nQUIT<x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare QUIT'@'",
        "SELECT 1\nQUIT@x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nQUIT@x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nQUIT@x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare QUIT'a'",
        "SELECT 1\nQUITax\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nQUITax\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nQUITax\nSELECT 2", 1]],
        ),
    ),
    (
        "bare QUIT'Z'",
        "SELECT 1\nQUITZx\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nQUITZx\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nQUITZx\nSELECT 2", 1]],
        ),
    ),
    (
        "bare QUIT'_'",
        "SELECT 1\nQUIT_x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nQUIT_x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nQUIT_x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare QUIT'9'",
        "SELECT 1\nQUIT9x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nQUIT9x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nQUIT9x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare QUIT'#'",
        "SELECT 1\nQUIT#x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nQUIT#x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nQUIT#x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare QUIT'$'",
        "SELECT 1\nQUIT$x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nQUIT$x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nQUIT$x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare QUIT''",
        "SELECT 1\nQUITx\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nQUITx\nSELECT 2", 1, None, 1, 0, 23)],
            [["SELECT 1\nQUITx\nSELECT 2", 1]],
        ),
    ),
    (
        "bare QUIT alone",
        "SELECT 1\nQUIT\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'QUIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare QUIT at eof",
        "SELECT 1\nQUIT",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'QUIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare quit' '",
        "SELECT 1\nquit x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'QUIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare quit'\\t'",
        "SELECT 1\nquit\tx\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'QUIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare quit'\\r'",
        "SELECT 1\nquit\rx\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'QUIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare quit'-'",
        "SELECT 1\nquit-x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'QUIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare quit'='",
        "SELECT 1\nquit=x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'QUIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare quit'('",
        "SELECT 1\nquit(x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'QUIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare quit'['",
        "SELECT 1\nquit[x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'QUIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        'bare quit"\'"',
        "SELECT 1\nquit'x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'QUIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare quit'/'",
        "SELECT 1\nquit/x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'QUIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare quit'.'",
        "SELECT 1\nquit.x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nquit.x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nquit.x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare quit','",
        "SELECT 1\nquit,x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nquit,x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nquit,x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare quit';'",
        "SELECT 1\nquit;x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nquit;x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nquit;x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare quit'+'",
        "SELECT 1\nquit+x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nquit+x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nquit+x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare quit')'",
        "SELECT 1\nquit)x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nquit)x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nquit)x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare quit'*'",
        "SELECT 1\nquit*x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nquit*x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nquit*x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare quit':'",
        "SELECT 1\nquit:x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nquit:x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nquit:x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare quit'|'",
        "SELECT 1\nquit|x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nquit|x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nquit|x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare quit'<'",
        "SELECT 1\nquit<x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nquit<x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nquit<x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare quit'@'",
        "SELECT 1\nquit@x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nquit@x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nquit@x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare quit'a'",
        "SELECT 1\nquitax\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nquitax\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nquitax\nSELECT 2", 1]],
        ),
    ),
    (
        "bare quit'Z'",
        "SELECT 1\nquitZx\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nquitZx\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nquitZx\nSELECT 2", 1]],
        ),
    ),
    (
        "bare quit'_'",
        "SELECT 1\nquit_x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nquit_x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nquit_x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare quit'9'",
        "SELECT 1\nquit9x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nquit9x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nquit9x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare quit'#'",
        "SELECT 1\nquit#x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nquit#x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nquit#x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare quit'$'",
        "SELECT 1\nquit$x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nquit$x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nquit$x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare quit''",
        "SELECT 1\nquitx\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nquitx\nSELECT 2", 1, None, 1, 0, 23)],
            [["SELECT 1\nquitx\nSELECT 2", 1]],
        ),
    ),
    (
        "bare quit alone",
        "SELECT 1\nquit\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'QUIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare quit at eof",
        "SELECT 1\nquit",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'QUIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare Quit' '",
        "SELECT 1\nQuit x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'QUIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare Quit'\\t'",
        "SELECT 1\nQuit\tx\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'QUIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare Quit'\\r'",
        "SELECT 1\nQuit\rx\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'QUIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare Quit'-'",
        "SELECT 1\nQuit-x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'QUIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare Quit'='",
        "SELECT 1\nQuit=x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'QUIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare Quit'('",
        "SELECT 1\nQuit(x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'QUIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare Quit'['",
        "SELECT 1\nQuit[x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'QUIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        'bare Quit"\'"',
        "SELECT 1\nQuit'x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'QUIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare Quit'/'",
        "SELECT 1\nQuit/x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'QUIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare Quit'.'",
        "SELECT 1\nQuit.x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nQuit.x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nQuit.x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Quit','",
        "SELECT 1\nQuit,x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nQuit,x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nQuit,x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Quit';'",
        "SELECT 1\nQuit;x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nQuit;x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nQuit;x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Quit'+'",
        "SELECT 1\nQuit+x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nQuit+x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nQuit+x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Quit')'",
        "SELECT 1\nQuit)x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nQuit)x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nQuit)x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Quit'*'",
        "SELECT 1\nQuit*x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nQuit*x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nQuit*x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Quit':'",
        "SELECT 1\nQuit:x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nQuit:x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nQuit:x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Quit'|'",
        "SELECT 1\nQuit|x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nQuit|x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nQuit|x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Quit'<'",
        "SELECT 1\nQuit<x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nQuit<x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nQuit<x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Quit'@'",
        "SELECT 1\nQuit@x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nQuit@x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nQuit@x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Quit'a'",
        "SELECT 1\nQuitax\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nQuitax\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nQuitax\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Quit'Z'",
        "SELECT 1\nQuitZx\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nQuitZx\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nQuitZx\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Quit'_'",
        "SELECT 1\nQuit_x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nQuit_x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nQuit_x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Quit'9'",
        "SELECT 1\nQuit9x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nQuit9x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nQuit9x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Quit'#'",
        "SELECT 1\nQuit#x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nQuit#x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nQuit#x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Quit'$'",
        "SELECT 1\nQuit$x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nQuit$x\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nQuit$x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Quit''",
        "SELECT 1\nQuitx\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nQuitx\nSELECT 2", 1, None, 1, 0, 23)],
            [["SELECT 1\nQuitx\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Quit alone",
        "SELECT 1\nQuit\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'QUIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare Quit at eof",
        "SELECT 1\nQuit",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'QUIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare RESET' '",
        "SELECT 1\nRESET x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'RESET' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare RESET'\\t'",
        "SELECT 1\nRESET\tx\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'RESET' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare RESET'\\r'",
        "SELECT 1\nRESET\rx\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'RESET' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare RESET'-'",
        "SELECT 1\nRESET-x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'RESET' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare RESET'='",
        "SELECT 1\nRESET=x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'RESET' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare RESET'('",
        "SELECT 1\nRESET(x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'RESET' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare RESET'['",
        "SELECT 1\nRESET[x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'RESET' on line 2: dblift does not run client commands",
        ),
    ),
    (
        'bare RESET"\'"',
        "SELECT 1\nRESET'x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'RESET' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare RESET'/'",
        "SELECT 1\nRESET/x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'RESET' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare RESET'.'",
        "SELECT 1\nRESET.x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nRESET.x\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nRESET.x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare RESET','",
        "SELECT 1\nRESET,x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nRESET,x\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nRESET,x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare RESET';'",
        "SELECT 1\nRESET;x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nRESET;x\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nRESET;x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare RESET'+'",
        "SELECT 1\nRESET+x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nRESET+x\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nRESET+x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare RESET')'",
        "SELECT 1\nRESET)x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nRESET)x\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nRESET)x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare RESET'*'",
        "SELECT 1\nRESET*x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nRESET*x\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nRESET*x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare RESET':'",
        "SELECT 1\nRESET:x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nRESET:x\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nRESET:x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare RESET'|'",
        "SELECT 1\nRESET|x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nRESET|x\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nRESET|x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare RESET'<'",
        "SELECT 1\nRESET<x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nRESET<x\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nRESET<x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare RESET'@'",
        "SELECT 1\nRESET@x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nRESET@x\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nRESET@x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare RESET'a'",
        "SELECT 1\nRESETax\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nRESETax\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nRESETax\nSELECT 2", 1]],
        ),
    ),
    (
        "bare RESET'Z'",
        "SELECT 1\nRESETZx\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nRESETZx\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nRESETZx\nSELECT 2", 1]],
        ),
    ),
    (
        "bare RESET'_'",
        "SELECT 1\nRESET_x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nRESET_x\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nRESET_x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare RESET'9'",
        "SELECT 1\nRESET9x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nRESET9x\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nRESET9x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare RESET'#'",
        "SELECT 1\nRESET#x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nRESET#x\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nRESET#x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare RESET'$'",
        "SELECT 1\nRESET$x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nRESET$x\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nRESET$x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare RESET''",
        "SELECT 1\nRESETx\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nRESETx\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nRESETx\nSELECT 2", 1]],
        ),
    ),
    (
        "bare RESET alone",
        "SELECT 1\nRESET\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'RESET' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare RESET at eof",
        "SELECT 1\nRESET",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'RESET' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare reset' '",
        "SELECT 1\nreset x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'RESET' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare reset'\\t'",
        "SELECT 1\nreset\tx\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'RESET' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare reset'\\r'",
        "SELECT 1\nreset\rx\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'RESET' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare reset'-'",
        "SELECT 1\nreset-x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'RESET' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare reset'='",
        "SELECT 1\nreset=x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'RESET' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare reset'('",
        "SELECT 1\nreset(x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'RESET' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare reset'['",
        "SELECT 1\nreset[x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'RESET' on line 2: dblift does not run client commands",
        ),
    ),
    (
        'bare reset"\'"',
        "SELECT 1\nreset'x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'RESET' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare reset'/'",
        "SELECT 1\nreset/x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'RESET' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare reset'.'",
        "SELECT 1\nreset.x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nreset.x\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nreset.x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare reset','",
        "SELECT 1\nreset,x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nreset,x\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nreset,x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare reset';'",
        "SELECT 1\nreset;x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nreset;x\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nreset;x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare reset'+'",
        "SELECT 1\nreset+x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nreset+x\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nreset+x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare reset')'",
        "SELECT 1\nreset)x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nreset)x\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nreset)x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare reset'*'",
        "SELECT 1\nreset*x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nreset*x\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nreset*x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare reset':'",
        "SELECT 1\nreset:x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nreset:x\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nreset:x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare reset'|'",
        "SELECT 1\nreset|x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nreset|x\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nreset|x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare reset'<'",
        "SELECT 1\nreset<x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nreset<x\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nreset<x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare reset'@'",
        "SELECT 1\nreset@x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nreset@x\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nreset@x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare reset'a'",
        "SELECT 1\nresetax\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nresetax\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nresetax\nSELECT 2", 1]],
        ),
    ),
    (
        "bare reset'Z'",
        "SELECT 1\nresetZx\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nresetZx\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nresetZx\nSELECT 2", 1]],
        ),
    ),
    (
        "bare reset'_'",
        "SELECT 1\nreset_x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nreset_x\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nreset_x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare reset'9'",
        "SELECT 1\nreset9x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nreset9x\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nreset9x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare reset'#'",
        "SELECT 1\nreset#x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nreset#x\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nreset#x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare reset'$'",
        "SELECT 1\nreset$x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nreset$x\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nreset$x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare reset''",
        "SELECT 1\nresetx\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nresetx\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nresetx\nSELECT 2", 1]],
        ),
    ),
    (
        "bare reset alone",
        "SELECT 1\nreset\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'RESET' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare reset at eof",
        "SELECT 1\nreset",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'RESET' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare Reset' '",
        "SELECT 1\nReset x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'RESET' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare Reset'\\t'",
        "SELECT 1\nReset\tx\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'RESET' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare Reset'\\r'",
        "SELECT 1\nReset\rx\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'RESET' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare Reset'-'",
        "SELECT 1\nReset-x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'RESET' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare Reset'='",
        "SELECT 1\nReset=x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'RESET' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare Reset'('",
        "SELECT 1\nReset(x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'RESET' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare Reset'['",
        "SELECT 1\nReset[x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'RESET' on line 2: dblift does not run client commands",
        ),
    ),
    (
        'bare Reset"\'"',
        "SELECT 1\nReset'x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'RESET' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare Reset'/'",
        "SELECT 1\nReset/x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'RESET' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare Reset'.'",
        "SELECT 1\nReset.x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nReset.x\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nReset.x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Reset','",
        "SELECT 1\nReset,x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nReset,x\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nReset,x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Reset';'",
        "SELECT 1\nReset;x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nReset;x\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nReset;x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Reset'+'",
        "SELECT 1\nReset+x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nReset+x\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nReset+x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Reset')'",
        "SELECT 1\nReset)x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nReset)x\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nReset)x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Reset'*'",
        "SELECT 1\nReset*x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nReset*x\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nReset*x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Reset':'",
        "SELECT 1\nReset:x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nReset:x\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nReset:x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Reset'|'",
        "SELECT 1\nReset|x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nReset|x\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nReset|x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Reset'<'",
        "SELECT 1\nReset<x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nReset<x\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nReset<x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Reset'@'",
        "SELECT 1\nReset@x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nReset@x\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nReset@x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Reset'a'",
        "SELECT 1\nResetax\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nResetax\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nResetax\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Reset'Z'",
        "SELECT 1\nResetZx\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nResetZx\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nResetZx\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Reset'_'",
        "SELECT 1\nReset_x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nReset_x\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nReset_x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Reset'9'",
        "SELECT 1\nReset9x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nReset9x\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nReset9x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Reset'#'",
        "SELECT 1\nReset#x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nReset#x\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nReset#x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Reset'$'",
        "SELECT 1\nReset$x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nReset$x\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nReset$x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Reset''",
        "SELECT 1\nResetx\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nResetx\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nResetx\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Reset alone",
        "SELECT 1\nReset\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'RESET' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare Reset at eof",
        "SELECT 1\nReset",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'RESET' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare ED' '",
        "SELECT 1\nED x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'ED' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare ED'\\t'",
        "SELECT 1\nED\tx\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'ED' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare ED'\\r'",
        "SELECT 1\nED\rx\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'ED' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare ED'-'",
        "SELECT 1\nED-x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'ED' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare ED'='",
        "SELECT 1\nED=x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'ED' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare ED'('",
        "SELECT 1\nED(x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'ED' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare ED'['",
        "SELECT 1\nED[x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'ED' on line 2: dblift does not run client commands",
        ),
    ),
    (
        'bare ED"\'"',
        "SELECT 1\nED'x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'ED' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare ED'/'",
        "SELECT 1\nED/x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'ED' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare ED'.'",
        "SELECT 1\nED.x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nED.x\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\nED.x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare ED','",
        "SELECT 1\nED,x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nED,x\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\nED,x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare ED';'",
        "SELECT 1\nED;x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nED;x\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\nED;x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare ED'+'",
        "SELECT 1\nED+x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nED+x\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\nED+x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare ED')'",
        "SELECT 1\nED)x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nED)x\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\nED)x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare ED'*'",
        "SELECT 1\nED*x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nED*x\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\nED*x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare ED':'",
        "SELECT 1\nED:x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nED:x\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\nED:x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare ED'|'",
        "SELECT 1\nED|x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nED|x\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\nED|x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare ED'<'",
        "SELECT 1\nED<x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nED<x\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\nED<x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare ED'@'",
        "SELECT 1\nED@x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nED@x\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\nED@x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare ED'a'",
        "SELECT 1\nEDax\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nEDax\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\nEDax\nSELECT 2", 1]],
        ),
    ),
    (
        "bare ED'Z'",
        "SELECT 1\nEDZx\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nEDZx\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\nEDZx\nSELECT 2", 1]],
        ),
    ),
    (
        "bare ED'_'",
        "SELECT 1\nED_x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nED_x\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\nED_x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare ED'9'",
        "SELECT 1\nED9x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nED9x\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\nED9x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare ED'#'",
        "SELECT 1\nED#x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nED#x\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\nED#x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare ED'$'",
        "SELECT 1\nED$x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nED$x\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\nED$x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare ED''",
        "SELECT 1\nEDx\nSELECT 2",
        ("ok", [("SELECT 1\nEDx\nSELECT 2", 1, None, 1, 0, 21)], [["SELECT 1\nEDx\nSELECT 2", 1]]),
    ),
    (
        "bare ED alone",
        "SELECT 1\nED\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'ED' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare ED at eof",
        "SELECT 1\nED",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'ED' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare ed' '",
        "SELECT 1\ned x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'ED' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare ed'\\t'",
        "SELECT 1\ned\tx\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'ED' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare ed'\\r'",
        "SELECT 1\ned\rx\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'ED' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare ed'-'",
        "SELECT 1\ned-x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'ED' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare ed'='",
        "SELECT 1\ned=x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'ED' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare ed'('",
        "SELECT 1\ned(x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'ED' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare ed'['",
        "SELECT 1\ned[x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'ED' on line 2: dblift does not run client commands",
        ),
    ),
    (
        'bare ed"\'"',
        "SELECT 1\ned'x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'ED' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare ed'/'",
        "SELECT 1\ned/x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'ED' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare ed'.'",
        "SELECT 1\ned.x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\ned.x\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\ned.x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare ed','",
        "SELECT 1\ned,x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\ned,x\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\ned,x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare ed';'",
        "SELECT 1\ned;x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\ned;x\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\ned;x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare ed'+'",
        "SELECT 1\ned+x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\ned+x\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\ned+x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare ed')'",
        "SELECT 1\ned)x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\ned)x\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\ned)x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare ed'*'",
        "SELECT 1\ned*x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\ned*x\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\ned*x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare ed':'",
        "SELECT 1\ned:x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\ned:x\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\ned:x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare ed'|'",
        "SELECT 1\ned|x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\ned|x\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\ned|x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare ed'<'",
        "SELECT 1\ned<x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\ned<x\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\ned<x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare ed'@'",
        "SELECT 1\ned@x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\ned@x\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\ned@x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare ed'a'",
        "SELECT 1\nedax\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nedax\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\nedax\nSELECT 2", 1]],
        ),
    ),
    (
        "bare ed'Z'",
        "SELECT 1\nedZx\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nedZx\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\nedZx\nSELECT 2", 1]],
        ),
    ),
    (
        "bare ed'_'",
        "SELECT 1\ned_x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\ned_x\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\ned_x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare ed'9'",
        "SELECT 1\ned9x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\ned9x\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\ned9x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare ed'#'",
        "SELECT 1\ned#x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\ned#x\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\ned#x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare ed'$'",
        "SELECT 1\ned$x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\ned$x\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\ned$x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare ed''",
        "SELECT 1\nedx\nSELECT 2",
        ("ok", [("SELECT 1\nedx\nSELECT 2", 1, None, 1, 0, 21)], [["SELECT 1\nedx\nSELECT 2", 1]]),
    ),
    (
        "bare ed alone",
        "SELECT 1\ned\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'ED' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare ed at eof",
        "SELECT 1\ned",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'ED' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare Ed' '",
        "SELECT 1\nEd x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'ED' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare Ed'\\t'",
        "SELECT 1\nEd\tx\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'ED' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare Ed'\\r'",
        "SELECT 1\nEd\rx\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'ED' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare Ed'-'",
        "SELECT 1\nEd-x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'ED' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare Ed'='",
        "SELECT 1\nEd=x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'ED' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare Ed'('",
        "SELECT 1\nEd(x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'ED' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare Ed'['",
        "SELECT 1\nEd[x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'ED' on line 2: dblift does not run client commands",
        ),
    ),
    (
        'bare Ed"\'"',
        "SELECT 1\nEd'x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'ED' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare Ed'/'",
        "SELECT 1\nEd/x\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'ED' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare Ed'.'",
        "SELECT 1\nEd.x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nEd.x\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\nEd.x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Ed','",
        "SELECT 1\nEd,x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nEd,x\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\nEd,x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Ed';'",
        "SELECT 1\nEd;x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nEd;x\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\nEd;x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Ed'+'",
        "SELECT 1\nEd+x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nEd+x\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\nEd+x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Ed')'",
        "SELECT 1\nEd)x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nEd)x\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\nEd)x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Ed'*'",
        "SELECT 1\nEd*x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nEd*x\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\nEd*x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Ed':'",
        "SELECT 1\nEd:x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nEd:x\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\nEd:x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Ed'|'",
        "SELECT 1\nEd|x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nEd|x\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\nEd|x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Ed'<'",
        "SELECT 1\nEd<x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nEd<x\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\nEd<x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Ed'@'",
        "SELECT 1\nEd@x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nEd@x\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\nEd@x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Ed'a'",
        "SELECT 1\nEdax\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nEdax\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\nEdax\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Ed'Z'",
        "SELECT 1\nEdZx\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nEdZx\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\nEdZx\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Ed'_'",
        "SELECT 1\nEd_x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nEd_x\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\nEd_x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Ed'9'",
        "SELECT 1\nEd9x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nEd9x\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\nEd9x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Ed'#'",
        "SELECT 1\nEd#x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nEd#x\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\nEd#x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Ed'$'",
        "SELECT 1\nEd$x\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nEd$x\nSELECT 2", 1, None, 1, 0, 22)],
            [["SELECT 1\nEd$x\nSELECT 2", 1]],
        ),
    ),
    (
        "bare Ed''",
        "SELECT 1\nEdx\nSELECT 2",
        ("ok", [("SELECT 1\nEdx\nSELECT 2", 1, None, 1, 0, 21)], [["SELECT 1\nEdx\nSELECT 2", 1]]),
    ),
    (
        "bare Ed alone",
        "SELECT 1\nEd\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'ED' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare Ed at eof",
        "SELECT 1\nEd",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'ED' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare line 'exit foo'",
        "SELECT 1\nexit foo\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare line 'exit(1)'",
        "SELECT 1\nexit(1)\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare line 'ed = 1'",
        "SELECT 1\ned = 1\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'ED' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare line 'exit+1'",
        "SELECT 1\nexit+1\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nexit+1\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\nexit+1\nSELECT 2", 1]],
        ),
    ),
    (
        "bare line 'quit;'",
        "SELECT 1\nquit;\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nquit;\nSELECT 2", 1, None, 1, 0, 23)],
            [["SELECT 1\nquit;\nSELECT 2", 1]],
        ),
    ),
    (
        "bare line 'ed.id'",
        "SELECT 1\ned.id\nSELECT 2",
        (
            "ok",
            [("SELECT 1\ned.id\nSELECT 2", 1, None, 1, 0, 23)],
            [["SELECT 1\ned.id\nSELECT 2", 1]],
        ),
    ),
    (
        "bare line 'reset<1'",
        "SELECT 1\nreset<1\nSELECT 2",
        (
            "ok",
            [("SELECT 1\nreset<1\nSELECT 2", 1, None, 1, 0, 25)],
            [["SELECT 1\nreset<1\nSELECT 2", 1]],
        ),
    ),
    (
        "bare line 'exit-1'",
        "SELECT 1\nexit-1\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare line 'EXIT -- c'",
        "SELECT 1\nEXIT -- c\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare line 'ed;'",
        "SELECT 1\ned;\nSELECT 2",
        ("ok", [("SELECT 1\ned;\nSELECT 2", 1, None, 1, 0, 21)], [["SELECT 1\ned;\nSELECT 2", 1]]),
    ),
    (
        "bare line 'reset\\r'",
        "SELECT 1\nreset\r\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'RESET' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "bare line 'quit\\r\\n'",
        "SELECT 1\nquit\r\n\nSELECT 2",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'QUIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "after comment '/* c */ :setvar a b'",
        "SELECT 1\n/* c */ :setvar a b\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':setvar' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "after comment '/* c */ EXIT'",
        "SELECT 1\n/* c */ EXIT\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "after comment '/* a\\nb */ :r x'",
        "SELECT 1\n/* a\nb */ :r x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':r' on line 3: dblift does not run client commands",
        ),
    ),
    (
        "after comment '/* a */ /* b */ !!x'",
        "SELECT 1\n/* a */ /* b */ !!x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command '!!x' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "after comment '-- c\\n:setvar a b'",
        "SELECT 1\n-- c\n:setvar a b\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':setvar' on line 3: dblift does not run client commands",
        ),
    ),
    (
        "after comment '/* c */ ED'",
        "SELECT 1\n/* c */ ED\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'ED' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "after comment 'x /* c */ :setvar a b'",
        "SELECT 1\nx /* c */ :setvar a b\nGO",
        (
            "ok",
            [("SELECT 1\nx /* c */ :setvar a b", 1, "GO", 1, 0, 33)],
            [["SELECT 1\nx /* c */ :setvar a b", 1]],
        ),
    ),
    (
        "nonblank '\\xa0' :setvar x y",
        "SELECT 1\n\xa0:setvar x y\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\xa0:setvar x y\nSELECT 2", 1, None, 1, 0, 30)],
            [["SELECT 1\n\xa0:setvar x y\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\xa0' :setvar x y",
        "SELECT 1\n\xa0/* c */ :setvar x y\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\xa0/* c */ :setvar x y\nSELECT 2", 1, None, 1, 0, 38)],
            [["SELECT 1\n\xa0/* c */ :setvar x y\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\xa0' EXIT",
        "SELECT 1\n\xa0EXIT\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\xa0EXIT\nSELECT 2", 1, None, 1, 0, 23)],
            [["SELECT 1\n\xa0EXIT\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\xa0' EXIT",
        "SELECT 1\n\xa0/* c */ EXIT\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\xa0/* c */ EXIT\nSELECT 2", 1, None, 1, 0, 31)],
            [["SELECT 1\n\xa0/* c */ EXIT\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\xa0' !!dir",
        "SELECT 1\n\xa0!!dir\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\xa0!!dir\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\n\xa0!!dir\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\xa0' !!dir",
        "SELECT 1\n\xa0/* c */ !!dir\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\xa0/* c */ !!dir\nSELECT 2", 1, None, 1, 0, 32)],
            [["SELECT 1\n\xa0/* c */ !!dir\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\xa0' QUIT",
        "SELECT 1\n\xa0QUIT\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\xa0QUIT\nSELECT 2", 1, None, 1, 0, 23)],
            [["SELECT 1\n\xa0QUIT\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\xa0' QUIT",
        "SELECT 1\n\xa0/* c */ QUIT\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\xa0/* c */ QUIT\nSELECT 2", 1, None, 1, 0, 31)],
            [["SELECT 1\n\xa0/* c */ QUIT\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\xa0' :r f",
        "SELECT 1\n\xa0:r f\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\xa0:r f\nSELECT 2", 1, None, 1, 0, 23)],
            [["SELECT 1\n\xa0:r f\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\xa0' :r f",
        "SELECT 1\n\xa0/* c */ :r f\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\xa0/* c */ :r f\nSELECT 2", 1, None, 1, 0, 31)],
            [["SELECT 1\n\xa0/* c */ :r f\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\x0c' :setvar x y",
        "SELECT 1\n\x0c:setvar x y\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x0c:setvar x y\nSELECT 2", 1, None, 1, 0, 30)],
            [["SELECT 1\n\x0c:setvar x y\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\x0c' :setvar x y",
        "SELECT 1\n\x0c/* c */ :setvar x y\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x0c/* c */ :setvar x y\nSELECT 2", 1, None, 1, 0, 38)],
            [["SELECT 1\n\x0c/* c */ :setvar x y\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\x0c' EXIT",
        "SELECT 1\n\x0cEXIT\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x0cEXIT\nSELECT 2", 1, None, 1, 0, 23)],
            [["SELECT 1\n\x0cEXIT\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\x0c' EXIT",
        "SELECT 1\n\x0c/* c */ EXIT\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x0c/* c */ EXIT\nSELECT 2", 1, None, 1, 0, 31)],
            [["SELECT 1\n\x0c/* c */ EXIT\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\x0c' !!dir",
        "SELECT 1\n\x0c!!dir\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x0c!!dir\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\n\x0c!!dir\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\x0c' !!dir",
        "SELECT 1\n\x0c/* c */ !!dir\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x0c/* c */ !!dir\nSELECT 2", 1, None, 1, 0, 32)],
            [["SELECT 1\n\x0c/* c */ !!dir\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\x0c' QUIT",
        "SELECT 1\n\x0cQUIT\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x0cQUIT\nSELECT 2", 1, None, 1, 0, 23)],
            [["SELECT 1\n\x0cQUIT\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\x0c' QUIT",
        "SELECT 1\n\x0c/* c */ QUIT\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x0c/* c */ QUIT\nSELECT 2", 1, None, 1, 0, 31)],
            [["SELECT 1\n\x0c/* c */ QUIT\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\x0c' :r f",
        "SELECT 1\n\x0c:r f\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x0c:r f\nSELECT 2", 1, None, 1, 0, 23)],
            [["SELECT 1\n\x0c:r f\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\x0c' :r f",
        "SELECT 1\n\x0c/* c */ :r f\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x0c/* c */ :r f\nSELECT 2", 1, None, 1, 0, 31)],
            [["SELECT 1\n\x0c/* c */ :r f\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\x1c' :setvar x y",
        "SELECT 1\n\x1c:setvar x y\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x1c:setvar x y\nSELECT 2", 1, None, 1, 0, 30)],
            [["SELECT 1\n\x1c:setvar x y\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\x1c' :setvar x y",
        "SELECT 1\n\x1c/* c */ :setvar x y\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x1c/* c */ :setvar x y\nSELECT 2", 1, None, 1, 0, 38)],
            [["SELECT 1\n\x1c/* c */ :setvar x y\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\x1c' EXIT",
        "SELECT 1\n\x1cEXIT\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x1cEXIT\nSELECT 2", 1, None, 1, 0, 23)],
            [["SELECT 1\n\x1cEXIT\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\x1c' EXIT",
        "SELECT 1\n\x1c/* c */ EXIT\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x1c/* c */ EXIT\nSELECT 2", 1, None, 1, 0, 31)],
            [["SELECT 1\n\x1c/* c */ EXIT\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\x1c' !!dir",
        "SELECT 1\n\x1c!!dir\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x1c!!dir\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\n\x1c!!dir\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\x1c' !!dir",
        "SELECT 1\n\x1c/* c */ !!dir\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x1c/* c */ !!dir\nSELECT 2", 1, None, 1, 0, 32)],
            [["SELECT 1\n\x1c/* c */ !!dir\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\x1c' QUIT",
        "SELECT 1\n\x1cQUIT\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x1cQUIT\nSELECT 2", 1, None, 1, 0, 23)],
            [["SELECT 1\n\x1cQUIT\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\x1c' QUIT",
        "SELECT 1\n\x1c/* c */ QUIT\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x1c/* c */ QUIT\nSELECT 2", 1, None, 1, 0, 31)],
            [["SELECT 1\n\x1c/* c */ QUIT\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\x1c' :r f",
        "SELECT 1\n\x1c:r f\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x1c:r f\nSELECT 2", 1, None, 1, 0, 23)],
            [["SELECT 1\n\x1c:r f\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\x1c' :r f",
        "SELECT 1\n\x1c/* c */ :r f\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x1c/* c */ :r f\nSELECT 2", 1, None, 1, 0, 31)],
            [["SELECT 1\n\x1c/* c */ :r f\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\x1d' :setvar x y",
        "SELECT 1\n\x1d:setvar x y\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x1d:setvar x y\nSELECT 2", 1, None, 1, 0, 30)],
            [["SELECT 1\n\x1d:setvar x y\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\x1d' :setvar x y",
        "SELECT 1\n\x1d/* c */ :setvar x y\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x1d/* c */ :setvar x y\nSELECT 2", 1, None, 1, 0, 38)],
            [["SELECT 1\n\x1d/* c */ :setvar x y\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\x1d' EXIT",
        "SELECT 1\n\x1dEXIT\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x1dEXIT\nSELECT 2", 1, None, 1, 0, 23)],
            [["SELECT 1\n\x1dEXIT\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\x1d' EXIT",
        "SELECT 1\n\x1d/* c */ EXIT\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x1d/* c */ EXIT\nSELECT 2", 1, None, 1, 0, 31)],
            [["SELECT 1\n\x1d/* c */ EXIT\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\x1d' !!dir",
        "SELECT 1\n\x1d!!dir\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x1d!!dir\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\n\x1d!!dir\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\x1d' !!dir",
        "SELECT 1\n\x1d/* c */ !!dir\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x1d/* c */ !!dir\nSELECT 2", 1, None, 1, 0, 32)],
            [["SELECT 1\n\x1d/* c */ !!dir\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\x1d' QUIT",
        "SELECT 1\n\x1dQUIT\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x1dQUIT\nSELECT 2", 1, None, 1, 0, 23)],
            [["SELECT 1\n\x1dQUIT\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\x1d' QUIT",
        "SELECT 1\n\x1d/* c */ QUIT\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x1d/* c */ QUIT\nSELECT 2", 1, None, 1, 0, 31)],
            [["SELECT 1\n\x1d/* c */ QUIT\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\x1d' :r f",
        "SELECT 1\n\x1d:r f\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x1d:r f\nSELECT 2", 1, None, 1, 0, 23)],
            [["SELECT 1\n\x1d:r f\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\x1d' :r f",
        "SELECT 1\n\x1d/* c */ :r f\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x1d/* c */ :r f\nSELECT 2", 1, None, 1, 0, 31)],
            [["SELECT 1\n\x1d/* c */ :r f\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\x1e' :setvar x y",
        "SELECT 1\n\x1e:setvar x y\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x1e:setvar x y\nSELECT 2", 1, None, 1, 0, 30)],
            [["SELECT 1\n\x1e:setvar x y\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\x1e' :setvar x y",
        "SELECT 1\n\x1e/* c */ :setvar x y\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x1e/* c */ :setvar x y\nSELECT 2", 1, None, 1, 0, 38)],
            [["SELECT 1\n\x1e/* c */ :setvar x y\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\x1e' EXIT",
        "SELECT 1\n\x1eEXIT\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x1eEXIT\nSELECT 2", 1, None, 1, 0, 23)],
            [["SELECT 1\n\x1eEXIT\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\x1e' EXIT",
        "SELECT 1\n\x1e/* c */ EXIT\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x1e/* c */ EXIT\nSELECT 2", 1, None, 1, 0, 31)],
            [["SELECT 1\n\x1e/* c */ EXIT\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\x1e' !!dir",
        "SELECT 1\n\x1e!!dir\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x1e!!dir\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\n\x1e!!dir\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\x1e' !!dir",
        "SELECT 1\n\x1e/* c */ !!dir\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x1e/* c */ !!dir\nSELECT 2", 1, None, 1, 0, 32)],
            [["SELECT 1\n\x1e/* c */ !!dir\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\x1e' QUIT",
        "SELECT 1\n\x1eQUIT\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x1eQUIT\nSELECT 2", 1, None, 1, 0, 23)],
            [["SELECT 1\n\x1eQUIT\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\x1e' QUIT",
        "SELECT 1\n\x1e/* c */ QUIT\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x1e/* c */ QUIT\nSELECT 2", 1, None, 1, 0, 31)],
            [["SELECT 1\n\x1e/* c */ QUIT\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\x1e' :r f",
        "SELECT 1\n\x1e:r f\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x1e:r f\nSELECT 2", 1, None, 1, 0, 23)],
            [["SELECT 1\n\x1e:r f\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\x1e' :r f",
        "SELECT 1\n\x1e/* c */ :r f\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x1e/* c */ :r f\nSELECT 2", 1, None, 1, 0, 31)],
            [["SELECT 1\n\x1e/* c */ :r f\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\x1f' :setvar x y",
        "SELECT 1\n\x1f:setvar x y\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x1f:setvar x y\nSELECT 2", 1, None, 1, 0, 30)],
            [["SELECT 1\n\x1f:setvar x y\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\x1f' :setvar x y",
        "SELECT 1\n\x1f/* c */ :setvar x y\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x1f/* c */ :setvar x y\nSELECT 2", 1, None, 1, 0, 38)],
            [["SELECT 1\n\x1f/* c */ :setvar x y\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\x1f' EXIT",
        "SELECT 1\n\x1fEXIT\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x1fEXIT\nSELECT 2", 1, None, 1, 0, 23)],
            [["SELECT 1\n\x1fEXIT\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\x1f' EXIT",
        "SELECT 1\n\x1f/* c */ EXIT\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x1f/* c */ EXIT\nSELECT 2", 1, None, 1, 0, 31)],
            [["SELECT 1\n\x1f/* c */ EXIT\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\x1f' !!dir",
        "SELECT 1\n\x1f!!dir\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x1f!!dir\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\n\x1f!!dir\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\x1f' !!dir",
        "SELECT 1\n\x1f/* c */ !!dir\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x1f/* c */ !!dir\nSELECT 2", 1, None, 1, 0, 32)],
            [["SELECT 1\n\x1f/* c */ !!dir\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\x1f' QUIT",
        "SELECT 1\n\x1fQUIT\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x1fQUIT\nSELECT 2", 1, None, 1, 0, 23)],
            [["SELECT 1\n\x1fQUIT\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\x1f' QUIT",
        "SELECT 1\n\x1f/* c */ QUIT\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x1f/* c */ QUIT\nSELECT 2", 1, None, 1, 0, 31)],
            [["SELECT 1\n\x1f/* c */ QUIT\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\x1f' :r f",
        "SELECT 1\n\x1f:r f\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x1f:r f\nSELECT 2", 1, None, 1, 0, 23)],
            [["SELECT 1\n\x1f:r f\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\x1f' :r f",
        "SELECT 1\n\x1f/* c */ :r f\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x1f/* c */ :r f\nSELECT 2", 1, None, 1, 0, 31)],
            [["SELECT 1\n\x1f/* c */ :r f\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\x85' :setvar x y",
        "SELECT 1\n\x85:setvar x y\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x85:setvar x y\nSELECT 2", 1, None, 1, 0, 30)],
            [["SELECT 1\n\x85:setvar x y\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\x85' :setvar x y",
        "SELECT 1\n\x85/* c */ :setvar x y\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x85/* c */ :setvar x y\nSELECT 2", 1, None, 1, 0, 38)],
            [["SELECT 1\n\x85/* c */ :setvar x y\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\x85' EXIT",
        "SELECT 1\n\x85EXIT\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x85EXIT\nSELECT 2", 1, None, 1, 0, 23)],
            [["SELECT 1\n\x85EXIT\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\x85' EXIT",
        "SELECT 1\n\x85/* c */ EXIT\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x85/* c */ EXIT\nSELECT 2", 1, None, 1, 0, 31)],
            [["SELECT 1\n\x85/* c */ EXIT\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\x85' !!dir",
        "SELECT 1\n\x85!!dir\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x85!!dir\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\n\x85!!dir\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\x85' !!dir",
        "SELECT 1\n\x85/* c */ !!dir\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x85/* c */ !!dir\nSELECT 2", 1, None, 1, 0, 32)],
            [["SELECT 1\n\x85/* c */ !!dir\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\x85' QUIT",
        "SELECT 1\n\x85QUIT\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x85QUIT\nSELECT 2", 1, None, 1, 0, 23)],
            [["SELECT 1\n\x85QUIT\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\x85' QUIT",
        "SELECT 1\n\x85/* c */ QUIT\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x85/* c */ QUIT\nSELECT 2", 1, None, 1, 0, 31)],
            [["SELECT 1\n\x85/* c */ QUIT\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\x85' :r f",
        "SELECT 1\n\x85:r f\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x85:r f\nSELECT 2", 1, None, 1, 0, 23)],
            [["SELECT 1\n\x85:r f\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\x85' :r f",
        "SELECT 1\n\x85/* c */ :r f\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x85/* c */ :r f\nSELECT 2", 1, None, 1, 0, 31)],
            [["SELECT 1\n\x85/* c */ :r f\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\u2028' :setvar x y",
        "SELECT 1\n\u2028:setvar x y\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\u2028:setvar x y\nSELECT 2", 1, None, 1, 0, 30)],
            [["SELECT 1\n\u2028:setvar x y\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\u2028' :setvar x y",
        "SELECT 1\n\u2028/* c */ :setvar x y\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\u2028/* c */ :setvar x y\nSELECT 2", 1, None, 1, 0, 38)],
            [["SELECT 1\n\u2028/* c */ :setvar x y\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\u2028' EXIT",
        "SELECT 1\n\u2028EXIT\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\u2028EXIT\nSELECT 2", 1, None, 1, 0, 23)],
            [["SELECT 1\n\u2028EXIT\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\u2028' EXIT",
        "SELECT 1\n\u2028/* c */ EXIT\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\u2028/* c */ EXIT\nSELECT 2", 1, None, 1, 0, 31)],
            [["SELECT 1\n\u2028/* c */ EXIT\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\u2028' !!dir",
        "SELECT 1\n\u2028!!dir\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\u2028!!dir\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\n\u2028!!dir\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\u2028' !!dir",
        "SELECT 1\n\u2028/* c */ !!dir\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\u2028/* c */ !!dir\nSELECT 2", 1, None, 1, 0, 32)],
            [["SELECT 1\n\u2028/* c */ !!dir\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\u2028' QUIT",
        "SELECT 1\n\u2028QUIT\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\u2028QUIT\nSELECT 2", 1, None, 1, 0, 23)],
            [["SELECT 1\n\u2028QUIT\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\u2028' QUIT",
        "SELECT 1\n\u2028/* c */ QUIT\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\u2028/* c */ QUIT\nSELECT 2", 1, None, 1, 0, 31)],
            [["SELECT 1\n\u2028/* c */ QUIT\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\u2028' :r f",
        "SELECT 1\n\u2028:r f\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\u2028:r f\nSELECT 2", 1, None, 1, 0, 23)],
            [["SELECT 1\n\u2028:r f\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\u2028' :r f",
        "SELECT 1\n\u2028/* c */ :r f\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\u2028/* c */ :r f\nSELECT 2", 1, None, 1, 0, 31)],
            [["SELECT 1\n\u2028/* c */ :r f\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\u2029' :setvar x y",
        "SELECT 1\n\u2029:setvar x y\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\u2029:setvar x y\nSELECT 2", 1, None, 1, 0, 30)],
            [["SELECT 1\n\u2029:setvar x y\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\u2029' :setvar x y",
        "SELECT 1\n\u2029/* c */ :setvar x y\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\u2029/* c */ :setvar x y\nSELECT 2", 1, None, 1, 0, 38)],
            [["SELECT 1\n\u2029/* c */ :setvar x y\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\u2029' EXIT",
        "SELECT 1\n\u2029EXIT\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\u2029EXIT\nSELECT 2", 1, None, 1, 0, 23)],
            [["SELECT 1\n\u2029EXIT\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\u2029' EXIT",
        "SELECT 1\n\u2029/* c */ EXIT\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\u2029/* c */ EXIT\nSELECT 2", 1, None, 1, 0, 31)],
            [["SELECT 1\n\u2029/* c */ EXIT\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\u2029' !!dir",
        "SELECT 1\n\u2029!!dir\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\u2029!!dir\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\n\u2029!!dir\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\u2029' !!dir",
        "SELECT 1\n\u2029/* c */ !!dir\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\u2029/* c */ !!dir\nSELECT 2", 1, None, 1, 0, 32)],
            [["SELECT 1\n\u2029/* c */ !!dir\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\u2029' QUIT",
        "SELECT 1\n\u2029QUIT\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\u2029QUIT\nSELECT 2", 1, None, 1, 0, 23)],
            [["SELECT 1\n\u2029QUIT\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\u2029' QUIT",
        "SELECT 1\n\u2029/* c */ QUIT\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\u2029/* c */ QUIT\nSELECT 2", 1, None, 1, 0, 31)],
            [["SELECT 1\n\u2029/* c */ QUIT\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\u2029' :r f",
        "SELECT 1\n\u2029:r f\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\u2029:r f\nSELECT 2", 1, None, 1, 0, 23)],
            [["SELECT 1\n\u2029:r f\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\u2029' :r f",
        "SELECT 1\n\u2029/* c */ :r f\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\u2029/* c */ :r f\nSELECT 2", 1, None, 1, 0, 31)],
            [["SELECT 1\n\u2029/* c */ :r f\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\x0b' :setvar x y",
        "SELECT 1\n\x0b:setvar x y\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x0b:setvar x y\nSELECT 2", 1, None, 1, 0, 30)],
            [["SELECT 1\n\x0b:setvar x y\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\x0b' :setvar x y",
        "SELECT 1\n\x0b/* c */ :setvar x y\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x0b/* c */ :setvar x y\nSELECT 2", 1, None, 1, 0, 38)],
            [["SELECT 1\n\x0b/* c */ :setvar x y\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\x0b' EXIT",
        "SELECT 1\n\x0bEXIT\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x0bEXIT\nSELECT 2", 1, None, 1, 0, 23)],
            [["SELECT 1\n\x0bEXIT\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\x0b' EXIT",
        "SELECT 1\n\x0b/* c */ EXIT\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x0b/* c */ EXIT\nSELECT 2", 1, None, 1, 0, 31)],
            [["SELECT 1\n\x0b/* c */ EXIT\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\x0b' !!dir",
        "SELECT 1\n\x0b!!dir\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x0b!!dir\nSELECT 2", 1, None, 1, 0, 24)],
            [["SELECT 1\n\x0b!!dir\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\x0b' !!dir",
        "SELECT 1\n\x0b/* c */ !!dir\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x0b/* c */ !!dir\nSELECT 2", 1, None, 1, 0, 32)],
            [["SELECT 1\n\x0b/* c */ !!dir\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\x0b' QUIT",
        "SELECT 1\n\x0bQUIT\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x0bQUIT\nSELECT 2", 1, None, 1, 0, 23)],
            [["SELECT 1\n\x0bQUIT\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\x0b' QUIT",
        "SELECT 1\n\x0b/* c */ QUIT\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x0b/* c */ QUIT\nSELECT 2", 1, None, 1, 0, 31)],
            [["SELECT 1\n\x0b/* c */ QUIT\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank '\\x0b' :r f",
        "SELECT 1\n\x0b:r f\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x0b:r f\nSELECT 2", 1, None, 1, 0, 23)],
            [["SELECT 1\n\x0b:r f\nSELECT 2", 1]],
        ),
    ),
    (
        "nonblank comment '\\x0b' :r f",
        "SELECT 1\n\x0b/* c */ :r f\nSELECT 2",
        (
            "ok",
            [("SELECT 1\n\x0b/* c */ :r f\nSELECT 2", 1, None, 1, 0, 31)],
            [["SELECT 1\n\x0b/* c */ :r f\nSELECT 2", 1]],
        ),
    ),
    (
        "context \"SELECT '\\n:setvar x y\\n'\"",
        "SELECT '\n:setvar x y\n'",
        (
            "ok",
            [("SELECT '\n:setvar x y\n'", 1, None, 1, 0, 22)],
            [["SELECT '\n:setvar x y\n'", 1]],
        ),
    ),
    (
        "context 'SELECT [\\nEXIT\\n]'",
        "SELECT [\nEXIT\n]",
        ("ok", [("SELECT [\nEXIT\n]", 1, None, 1, 0, 15)], [["SELECT [\nEXIT\n]", 1]]),
    ),
    (
        "context 'SELECT \"\\n!!dir\\n\"'",
        'SELECT "\n!!dir\n"',
        ("ok", [('SELECT "\n!!dir\n"', 1, None, 1, 0, 16)], [['SELECT "\n!!dir\n"', 1]]),
    ),
    (
        "context 'SELECT 1 -- :setvar x\\nGO'",
        "SELECT 1 -- :setvar x\nGO",
        ("ok", [("SELECT 1 -- :setvar x", 1, "GO", 1, 0, 24)], [["SELECT 1 -- :setvar x", 1]]),
    ),
    (
        "context 'SELECT 1 /*\\nEXIT\\n*/\\nGO'",
        "SELECT 1 /*\nEXIT\n*/\nGO",
        ("ok", [("SELECT 1 /*\nEXIT\n*/", 1, "GO", 1, 0, 22)], [["SELECT 1 /*\nEXIT\n*/", 1]]),
    ),
    (
        "context \"SELECT 'a'\\n:r x\\n\"",
        "SELECT 'a'\n:r x\n",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':r' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "context 'SELECT [a]\\nEXIT\\n'",
        "SELECT [a]\nEXIT\n",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "context 'SELECT 1 /* x */\\nEXIT'",
        "SELECT 1 /* x */\nEXIT",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "context 'SELECT 1\\n  :setvar x y'",
        "SELECT 1\n  :setvar x y",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':setvar' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "context 'CREATE TABLE t (\\n  exit INT\\n)\\nGO'",
        "CREATE TABLE t (\n  exit INT\n)\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "context 'CREATE TABLE t (id INT,\\n:setvar x y\\n x INT)\\nGO'",
        "CREATE TABLE t (id INT,\n:setvar x y\n x INT)\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':setvar' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "context 'SELECT 1;\\nEXIT'",
        "SELECT 1;\nEXIT",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "context 'SELECT 1\\n\\tEXIT\\n'",
        "SELECT 1\n\tEXIT\n",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "context 'SELECT 1\\r\\n:setvar a b\\r\\nGO'",
        "SELECT 1\r\n:setvar a b\r\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command ':setvar' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "context 'SELECT 1\\r\\nEXIT\\r\\n'",
        "SELECT 1\r\nEXIT\r\n",
        (
            "error",
            "UnsupportedMetaCommandError",
            "sqlcmd command 'EXIT' on line 2: dblift does not run client commands",
        ),
    ),
    (
        "var code '$(x)'",
        "SELECT $(x)\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(x) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var string '$(x)'",
        "SELECT '$(x)' AS s\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(x) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var bracket '$(x)'",
        "SELECT [$(x)] FROM t\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(x) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var quoted '$(x)'",
        'SELECT "$(x)" FROM t\nGO',
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(x) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var line comment '$(x)'",
        "SELECT 1 -- $(x)\nGO",
        ("ok", [("SELECT 1 -- $(x)", 1, "GO", 1, 0, 19)], [["SELECT 1 -- $(x)", 1]]),
    ),
    (
        "var block comment '$(x)'",
        "SELECT 1 /* $(x) */\nGO",
        ("ok", [("SELECT 1 /* $(x) */", 1, "GO", 1, 0, 22)], [["SELECT 1 /* $(x) */", 1]]),
    ),
    (
        "var go tail '$(x)'",
        "SELECT 1\nGO $(x)\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it; $(x) is not substituted",
        ),
    ),
    (
        "var code '$()'",
        "SELECT $()\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $() on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var string '$()'",
        "SELECT '$()' AS s\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $() on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var bracket '$()'",
        "SELECT [$()] FROM t\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $() on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var quoted '$()'",
        'SELECT "$()" FROM t\nGO',
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $() on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var line comment '$()'",
        "SELECT 1 -- $()\nGO",
        ("ok", [("SELECT 1 -- $()", 1, "GO", 1, 0, 18)], [["SELECT 1 -- $()", 1]]),
    ),
    (
        "var block comment '$()'",
        "SELECT 1 /* $() */\nGO",
        ("ok", [("SELECT 1 /* $() */", 1, "GO", 1, 0, 21)], [["SELECT 1 /* $() */", 1]]),
    ),
    (
        "var go tail '$()'",
        "SELECT 1\nGO $()\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it; $() is not substituted",
        ),
    ),
    (
        "var code '$(1x)'",
        "SELECT $(1x)\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(1x) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the "
            "text as it is",
        ),
    ),
    (
        "var string '$(1x)'",
        "SELECT '$(1x)' AS s\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(1x) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the "
            "text as it is",
        ),
    ),
    (
        "var bracket '$(1x)'",
        "SELECT [$(1x)] FROM t\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(1x) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the "
            "text as it is",
        ),
    ),
    (
        "var quoted '$(1x)'",
        'SELECT "$(1x)" FROM t\nGO',
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(1x) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the "
            "text as it is",
        ),
    ),
    (
        "var line comment '$(1x)'",
        "SELECT 1 -- $(1x)\nGO",
        ("ok", [("SELECT 1 -- $(1x)", 1, "GO", 1, 0, 20)], [["SELECT 1 -- $(1x)", 1]]),
    ),
    (
        "var block comment '$(1x)'",
        "SELECT 1 /* $(1x) */\nGO",
        ("ok", [("SELECT 1 /* $(1x) */", 1, "GO", 1, 0, 23)], [["SELECT 1 /* $(1x) */", 1]]),
    ),
    (
        "var go tail '$(1x)'",
        "SELECT 1\nGO $(1x)\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it; $(1x) is not substituted",
        ),
    ),
    (
        "var code '$(a.b)'",
        "SELECT $(a.b)\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(a.b) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the "
            "text as it is",
        ),
    ),
    (
        "var string '$(a.b)'",
        "SELECT '$(a.b)' AS s\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(a.b) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the "
            "text as it is",
        ),
    ),
    (
        "var bracket '$(a.b)'",
        "SELECT [$(a.b)] FROM t\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(a.b) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the "
            "text as it is",
        ),
    ),
    (
        "var quoted '$(a.b)'",
        'SELECT "$(a.b)" FROM t\nGO',
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(a.b) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the "
            "text as it is",
        ),
    ),
    (
        "var line comment '$(a.b)'",
        "SELECT 1 -- $(a.b)\nGO",
        ("ok", [("SELECT 1 -- $(a.b)", 1, "GO", 1, 0, 21)], [["SELECT 1 -- $(a.b)", 1]]),
    ),
    (
        "var block comment '$(a.b)'",
        "SELECT 1 /* $(a.b) */\nGO",
        ("ok", [("SELECT 1 /* $(a.b) */", 1, "GO", 1, 0, 24)], [["SELECT 1 /* $(a.b) */", 1]]),
    ),
    (
        "var go tail '$(a.b)'",
        "SELECT 1\nGO $(a.b)\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it; $(a.b) is not substituted",
        ),
    ),
    (
        "var code '$(x y)'",
        "SELECT $(x y)\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(x y) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the "
            "text as it is",
        ),
    ),
    (
        "var string '$(x y)'",
        "SELECT '$(x y)' AS s\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(x y) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the "
            "text as it is",
        ),
    ),
    (
        "var bracket '$(x y)'",
        "SELECT [$(x y)] FROM t\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(x y) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the "
            "text as it is",
        ),
    ),
    (
        "var quoted '$(x y)'",
        'SELECT "$(x y)" FROM t\nGO',
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(x y) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the "
            "text as it is",
        ),
    ),
    (
        "var line comment '$(x y)'",
        "SELECT 1 -- $(x y)\nGO",
        ("ok", [("SELECT 1 -- $(x y)", 1, "GO", 1, 0, 21)], [["SELECT 1 -- $(x y)", 1]]),
    ),
    (
        "var block comment '$(x y)'",
        "SELECT 1 /* $(x y) */\nGO",
        ("ok", [("SELECT 1 /* $(x y) */", 1, "GO", 1, 0, 24)], [["SELECT 1 /* $(x y) */", 1]]),
    ),
    (
        "var go tail '$(x y)'",
        "SELECT 1\nGO $(x y)\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it; $(x y) is not substituted",
        ),
    ),
    (
        "var code '$('",
        "SELECT $(\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $( on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var string '$('",
        "SELECT '$(' AS s\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $( on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var bracket '$('",
        "SELECT [$(] FROM t\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $( on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var quoted '$('",
        'SELECT "$(" FROM t\nGO',
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $( on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var line comment '$('",
        "SELECT 1 -- $(\nGO",
        ("ok", [("SELECT 1 -- $(", 1, "GO", 1, 0, 17)], [["SELECT 1 -- $(", 1]]),
    ),
    (
        "var block comment '$('",
        "SELECT 1 /* $( */\nGO",
        ("ok", [("SELECT 1 /* $( */", 1, "GO", 1, 0, 20)], [["SELECT 1 /* $( */", 1]]),
    ),
    (
        "var go tail '$('",
        "SELECT 1\nGO $(\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it; $( is not substituted",
        ),
    ),
    (
        "var code '$(x'",
        "SELECT $(x\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(x on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var string '$(x'",
        "SELECT '$(x' AS s\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(x on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var bracket '$(x'",
        "SELECT [$(x] FROM t\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(x on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var quoted '$(x'",
        'SELECT "$(x" FROM t\nGO',
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(x on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var line comment '$(x'",
        "SELECT 1 -- $(x\nGO",
        ("ok", [("SELECT 1 -- $(x", 1, "GO", 1, 0, 18)], [["SELECT 1 -- $(x", 1]]),
    ),
    (
        "var block comment '$(x'",
        "SELECT 1 /* $(x */\nGO",
        ("ok", [("SELECT 1 /* $(x */", 1, "GO", 1, 0, 21)], [["SELECT 1 /* $(x */", 1]]),
    ),
    (
        "var go tail '$(x'",
        "SELECT 1\nGO $(x\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it; $(x is not substituted",
        ),
    ),
    (
        "var code '$ (x)'",
        "SELECT $ (x)\nGO",
        ("ok", [("SELECT $ (x)", 1, "GO", 1, 0, 15)], [["SELECT $ (x)", 1]]),
    ),
    (
        "var string '$ (x)'",
        "SELECT '$ (x)' AS s\nGO",
        ("ok", [("SELECT '$ (x)' AS s", 1, "GO", 1, 0, 22)], [["SELECT '$ (x)' AS s", 1]]),
    ),
    (
        "var bracket '$ (x)'",
        "SELECT [$ (x)] FROM t\nGO",
        ("ok", [("SELECT [$ (x)] FROM t", 1, "GO", 1, 0, 24)], [["SELECT [$ (x)] FROM t", 1]]),
    ),
    (
        "var quoted '$ (x)'",
        'SELECT "$ (x)" FROM t\nGO',
        ("ok", [('SELECT "$ (x)" FROM t', 1, "GO", 1, 0, 24)], [['SELECT "$ (x)" FROM t', 1]]),
    ),
    (
        "var line comment '$ (x)'",
        "SELECT 1 -- $ (x)\nGO",
        ("ok", [("SELECT 1 -- $ (x)", 1, "GO", 1, 0, 20)], [["SELECT 1 -- $ (x)", 1]]),
    ),
    (
        "var block comment '$ (x)'",
        "SELECT 1 /* $ (x) */\nGO",
        ("ok", [("SELECT 1 /* $ (x) */", 1, "GO", 1, 0, 23)], [["SELECT 1 /* $ (x) */", 1]]),
    ),
    (
        "var go tail '$ (x)'",
        "SELECT 1\nGO $ (x)\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it",
        ),
    ),
    (
        "var code '$(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)'",
        "SELECT $(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa on line 1: sqlcmd substitutes it before "
            "the batch is sent, dblift sends the text as it is",
        ),
    ),
    (
        "var string '$(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)'",
        "SELECT '$(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)' AS s\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa on line 1: sqlcmd substitutes it before "
            "the batch is sent, dblift sends the text as it is",
        ),
    ),
    (
        "var bracket '$(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)'",
        "SELECT [$(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)] FROM t\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa on line 1: sqlcmd substitutes it before "
            "the batch is sent, dblift sends the text as it is",
        ),
    ),
    (
        "var quoted '$(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)'",
        'SELECT "$(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)" FROM t\nGO',
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa on line 1: sqlcmd substitutes it before "
            "the batch is sent, dblift sends the text as it is",
        ),
    ),
    (
        "var line comment '$(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)'",
        "SELECT 1 -- $(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)\nGO",
        (
            "ok",
            [("SELECT 1 -- $(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)", 1, "GO", 1, 0, 63)],
            [["SELECT 1 -- $(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)", 1]],
        ),
    ),
    (
        "var block comment '$(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)'",
        "SELECT 1 /* $(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa) */\nGO",
        (
            "ok",
            [
                (
                    "SELECT 1 /* $(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa) */",
                    1,
                    "GO",
                    1,
                    0,
                    66,
                )
            ],
            [["SELECT 1 /* $(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa) */", 1]],
        ),
    ),
    (
        "var go tail '$(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)'",
        "SELECT 1\nGO $(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it; "
            "$(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa is not substituted",
        ),
    ),
    (
        'var code "$(a\'b)"',
        "SELECT $(a'b)\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(a on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        'var string "$(a\'b)"',
        "SELECT '$(a'b)' AS s\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(a on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        'var bracket "$(a\'b)"',
        "SELECT [$(a'b)] FROM t\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(a'b) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the "
            "text as it is",
        ),
    ),
    (
        'var quoted "$(a\'b)"',
        'SELECT "$(a\'b)" FROM t\nGO',
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(a'b) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the "
            "text as it is",
        ),
    ),
    (
        'var line comment "$(a\'b)"',
        "SELECT 1 -- $(a'b)\nGO",
        ("ok", [("SELECT 1 -- $(a'b)", 1, "GO", 1, 0, 21)], [["SELECT 1 -- $(a'b)", 1]]),
    ),
    (
        'var block comment "$(a\'b)"',
        "SELECT 1 /* $(a'b) */\nGO",
        ("ok", [("SELECT 1 /* $(a'b) */", 1, "GO", 1, 0, 24)], [["SELECT 1 /* $(a'b) */", 1]]),
    ),
    (
        'var go tail "$(a\'b)"',
        "SELECT 1\nGO $(a'b)\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it; $(a'b) is not substituted",
        ),
    ),
    (
        "var code \"$(a'b)'\"",
        "SELECT $(a'b)'\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(a on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var string \"$(a'b)'\"",
        "SELECT '$(a'b)'' AS s\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(a on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var bracket \"$(a'b)'\"",
        "SELECT [$(a'b)'] FROM t\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(a'b) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the "
            "text as it is",
        ),
    ),
    (
        "var quoted \"$(a'b)'\"",
        "SELECT \"$(a'b)'\" FROM t\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(a'b) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the "
            "text as it is",
        ),
    ),
    (
        "var line comment \"$(a'b)'\"",
        "SELECT 1 -- $(a'b)'\nGO",
        ("ok", [("SELECT 1 -- $(a'b)'", 1, "GO", 1, 0, 22)], [["SELECT 1 -- $(a'b)'", 1]]),
    ),
    (
        "var block comment \"$(a'b)'\"",
        "SELECT 1 /* $(a'b)' */\nGO",
        ("ok", [("SELECT 1 /* $(a'b)' */", 1, "GO", 1, 0, 25)], [["SELECT 1 /* $(a'b)' */", 1]]),
    ),
    (
        "var go tail \"$(a'b)'\"",
        "SELECT 1\nGO $(a'b)'\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it; $(a'b) is not substituted",
        ),
    ),
    (
        "var code '$(a--b)'",
        "SELECT $(a--b)\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(a on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var string '$(a--b)'",
        "SELECT '$(a--b)' AS s\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(a--b) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the "
            "text as it is",
        ),
    ),
    (
        "var bracket '$(a--b)'",
        "SELECT [$(a--b)] FROM t\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(a--b) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the "
            "text as it is",
        ),
    ),
    (
        "var quoted '$(a--b)'",
        'SELECT "$(a--b)" FROM t\nGO',
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(a--b) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the "
            "text as it is",
        ),
    ),
    (
        "var line comment '$(a--b)'",
        "SELECT 1 -- $(a--b)\nGO",
        ("ok", [("SELECT 1 -- $(a--b)", 1, "GO", 1, 0, 22)], [["SELECT 1 -- $(a--b)", 1]]),
    ),
    (
        "var block comment '$(a--b)'",
        "SELECT 1 /* $(a--b) */\nGO",
        ("ok", [("SELECT 1 /* $(a--b) */", 1, "GO", 1, 0, 25)], [["SELECT 1 /* $(a--b) */", 1]]),
    ),
    (
        "var go tail '$(a--b)'",
        "SELECT 1\nGO $(a--b)\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it; $(a--b) is not substituted",
        ),
    ),
    (
        "var code '$(a/*b)'",
        "SELECT $(a/*b)\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(a on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var string '$(a/*b)'",
        "SELECT '$(a/*b)' AS s\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(a/*b) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the "
            "text as it is",
        ),
    ),
    (
        "var bracket '$(a/*b)'",
        "SELECT [$(a/*b)] FROM t\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(a/*b) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the "
            "text as it is",
        ),
    ),
    (
        "var quoted '$(a/*b)'",
        'SELECT "$(a/*b)" FROM t\nGO',
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(a/*b) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the "
            "text as it is",
        ),
    ),
    (
        "var line comment '$(a/*b)'",
        "SELECT 1 -- $(a/*b)\nGO",
        ("ok", [("SELECT 1 -- $(a/*b)", 1, "GO", 1, 0, 22)], [["SELECT 1 -- $(a/*b)", 1]]),
    ),
    (
        "var block comment '$(a/*b)'",
        "SELECT 1 /* $(a/*b) */\nGO",
        ("ok", [("SELECT 1 /* $(a/*b) */", 1, "GO", 1, 0, 25)], [["SELECT 1 /* $(a/*b) */", 1]]),
    ),
    (
        "var go tail '$(a/*b)'",
        "SELECT 1\nGO $(a/*b)\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it; $(a/*b) is not substituted",
        ),
    ),
    (
        "var code '$($(x))'",
        "SELECT $($(x))\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $($(x) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the "
            "text as it is",
        ),
    ),
    (
        "var string '$($(x))'",
        "SELECT '$($(x))' AS s\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $($(x) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the "
            "text as it is",
        ),
    ),
    (
        "var bracket '$($(x))'",
        "SELECT [$($(x))] FROM t\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $($(x) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the "
            "text as it is",
        ),
    ),
    (
        "var quoted '$($(x))'",
        'SELECT "$($(x))" FROM t\nGO',
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $($(x) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the "
            "text as it is",
        ),
    ),
    (
        "var line comment '$($(x))'",
        "SELECT 1 -- $($(x))\nGO",
        ("ok", [("SELECT 1 -- $($(x))", 1, "GO", 1, 0, 22)], [["SELECT 1 -- $($(x))", 1]]),
    ),
    (
        "var block comment '$($(x))'",
        "SELECT 1 /* $($(x)) */\nGO",
        ("ok", [("SELECT 1 /* $($(x)) */", 1, "GO", 1, 0, 25)], [["SELECT 1 /* $($(x)) */", 1]]),
    ),
    (
        "var go tail '$($(x))'",
        "SELECT 1\nGO $($(x))\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it; $($(x) is not substituted",
        ),
    ),
    (
        "var code '$(x)$(y)'",
        "SELECT $(x)$(y)\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(x) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var string '$(x)$(y)'",
        "SELECT '$(x)$(y)' AS s\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(x) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var bracket '$(x)$(y)'",
        "SELECT [$(x)$(y)] FROM t\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(x) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var quoted '$(x)$(y)'",
        'SELECT "$(x)$(y)" FROM t\nGO',
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(x) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var line comment '$(x)$(y)'",
        "SELECT 1 -- $(x)$(y)\nGO",
        ("ok", [("SELECT 1 -- $(x)$(y)", 1, "GO", 1, 0, 23)], [["SELECT 1 -- $(x)$(y)", 1]]),
    ),
    (
        "var block comment '$(x)$(y)'",
        "SELECT 1 /* $(x)$(y) */\nGO",
        ("ok", [("SELECT 1 /* $(x)$(y) */", 1, "GO", 1, 0, 26)], [["SELECT 1 /* $(x)$(y) */", 1]]),
    ),
    (
        "var go tail '$(x)$(y)'",
        "SELECT 1\nGO $(x)$(y)\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it; $(x) is not substituted",
        ),
    ),
    (
        "var code '$(table)'",
        "SELECT $(table)\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(table) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the "
            "text as it is",
        ),
    ),
    (
        "var string '$(table)'",
        "SELECT '$(table)' AS s\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(table) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the "
            "text as it is",
        ),
    ),
    (
        "var bracket '$(table)'",
        "SELECT [$(table)] FROM t\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(table) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the "
            "text as it is",
        ),
    ),
    (
        "var quoted '$(table)'",
        'SELECT "$(table)" FROM t\nGO',
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(table) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the "
            "text as it is",
        ),
    ),
    (
        "var line comment '$(table)'",
        "SELECT 1 -- $(table)\nGO",
        ("ok", [("SELECT 1 -- $(table)", 1, "GO", 1, 0, 23)], [["SELECT 1 -- $(table)", 1]]),
    ),
    (
        "var block comment '$(table)'",
        "SELECT 1 /* $(table) */\nGO",
        ("ok", [("SELECT 1 /* $(table) */", 1, "GO", 1, 0, 26)], [["SELECT 1 /* $(table) */", 1]]),
    ),
    (
        "var go tail '$(table)'",
        "SELECT 1\nGO $(table)\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it; $(table) is not substituted",
        ),
    ),
    (
        "var code '$(a\\nb)'",
        "SELECT $(a\nb)\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(a on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var string '$(a\\nb)'",
        "SELECT '$(a\nb)' AS s\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(a on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var bracket '$(a\\nb)'",
        "SELECT [$(a\nb)] FROM t\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(a on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var quoted '$(a\\nb)'",
        'SELECT "$(a\nb)" FROM t\nGO',
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(a on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var line comment '$(a\\nb)'",
        "SELECT 1 -- $(a\nb)\nGO",
        ("ok", [("SELECT 1 -- $(a\nb)", 1, "GO", 1, 0, 21)], [["SELECT 1 -- $(a\nb)", 1]]),
    ),
    (
        "var block comment '$(a\\nb)'",
        "SELECT 1 /* $(a\nb) */\nGO",
        ("ok", [("SELECT 1 /* $(a\nb) */", 1, "GO", 1, 0, 24)], [["SELECT 1 /* $(a\nb) */", 1]]),
    ),
    (
        "var go tail '$(a\\nb)'",
        "SELECT 1\nGO $(a\nb)\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it; $(a is not substituted",
        ),
    ),
    (
        "var code '$(a\\rb)'",
        "SELECT $(a\rb)\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(a on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var string '$(a\\rb)'",
        "SELECT '$(a\rb)' AS s\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(a on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var bracket '$(a\\rb)'",
        "SELECT [$(a\rb)] FROM t\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(a on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var quoted '$(a\\rb)'",
        'SELECT "$(a\rb)" FROM t\nGO',
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(a on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var line comment '$(a\\rb)'",
        "SELECT 1 -- $(a\rb)\nGO",
        ("ok", [("SELECT 1 -- $(a\rb)", 1, "GO", 1, 0, 21)], [["SELECT 1 -- $(a\rb)", 1]]),
    ),
    (
        "var block comment '$(a\\rb)'",
        "SELECT 1 /* $(a\rb) */\nGO",
        ("ok", [("SELECT 1 /* $(a\rb) */", 1, "GO", 1, 0, 24)], [["SELECT 1 /* $(a\rb) */", 1]]),
    ),
    (
        "var go tail '$(a\\rb)'",
        "SELECT 1\nGO $(a\rb)\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it; $(a is not substituted",
        ),
    ),
    (
        "var code 'x$(y)z'",
        "SELECT x$(y)z\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(y) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var string 'x$(y)z'",
        "SELECT 'x$(y)z' AS s\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(y) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var bracket 'x$(y)z'",
        "SELECT [x$(y)z] FROM t\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(y) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var quoted 'x$(y)z'",
        'SELECT "x$(y)z" FROM t\nGO',
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(y) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var line comment 'x$(y)z'",
        "SELECT 1 -- x$(y)z\nGO",
        ("ok", [("SELECT 1 -- x$(y)z", 1, "GO", 1, 0, 21)], [["SELECT 1 -- x$(y)z", 1]]),
    ),
    (
        "var block comment 'x$(y)z'",
        "SELECT 1 /* x$(y)z */\nGO",
        ("ok", [("SELECT 1 /* x$(y)z */", 1, "GO", 1, 0, 24)], [["SELECT 1 /* x$(y)z */", 1]]),
    ),
    (
        "var go tail 'x$(y)z'",
        "SELECT 1\nGO x$(y)z\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it; $(y) is not substituted",
        ),
    ),
    (
        "var code '$(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)'",
        "SELECT $(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa) on line 1: sqlcmd substitutes it before "
            "the batch is sent, dblift sends the text as it is",
        ),
    ),
    (
        "var string '$(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)'",
        "SELECT '$(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)' AS s\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa) on line 1: sqlcmd substitutes it before "
            "the batch is sent, dblift sends the text as it is",
        ),
    ),
    (
        "var bracket '$(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)'",
        "SELECT [$(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)] FROM t\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa) on line 1: sqlcmd substitutes it before "
            "the batch is sent, dblift sends the text as it is",
        ),
    ),
    (
        "var quoted '$(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)'",
        'SELECT "$(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)" FROM t\nGO',
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa) on line 1: sqlcmd substitutes it before "
            "the batch is sent, dblift sends the text as it is",
        ),
    ),
    (
        "var line comment '$(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)'",
        "SELECT 1 -- $(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)\nGO",
        (
            "ok",
            [("SELECT 1 -- $(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)", 1, "GO", 1, 0, 58)],
            [["SELECT 1 -- $(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)", 1]],
        ),
    ),
    (
        "var block comment '$(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)'",
        "SELECT 1 /* $(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa) */\nGO",
        (
            "ok",
            [("SELECT 1 /* $(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa) */", 1, "GO", 1, 0, 61)],
            [["SELECT 1 /* $(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa) */", 1]],
        ),
    ),
    (
        "var go tail '$(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)'",
        "SELECT 1\nGO $(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it; "
            "$(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa) is not substituted",
        ),
    ),
    (
        "var code '$(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)'",
        "SELECT $(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa on line 1: sqlcmd substitutes it before "
            "the batch is sent, dblift sends the text as it is",
        ),
    ),
    (
        "var string '$(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)'",
        "SELECT '$(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)' AS s\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa on line 1: sqlcmd substitutes it before "
            "the batch is sent, dblift sends the text as it is",
        ),
    ),
    (
        "var bracket '$(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)'",
        "SELECT [$(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)] FROM t\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa on line 1: sqlcmd substitutes it before "
            "the batch is sent, dblift sends the text as it is",
        ),
    ),
    (
        "var quoted '$(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)'",
        'SELECT "$(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)" FROM t\nGO',
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa on line 1: sqlcmd substitutes it before "
            "the batch is sent, dblift sends the text as it is",
        ),
    ),
    (
        "var line comment '$(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)'",
        "SELECT 1 -- $(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)\nGO",
        (
            "ok",
            [("SELECT 1 -- $(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)", 1, "GO", 1, 0, 59)],
            [["SELECT 1 -- $(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)", 1]],
        ),
    ),
    (
        "var block comment '$(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)'",
        "SELECT 1 /* $(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa) */\nGO",
        (
            "ok",
            [("SELECT 1 /* $(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa) */", 1, "GO", 1, 0, 62)],
            [["SELECT 1 /* $(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa) */", 1]],
        ),
    ),
    (
        "var go tail '$(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)'",
        "SELECT 1\nGO $(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it; "
            "$(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa is not substituted",
        ),
    ),
    (
        "var code '$(\\t)'",
        "SELECT $(\t)\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(\t) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the "
            "text as it is",
        ),
    ),
    (
        "var string '$(\\t)'",
        "SELECT '$(\t)' AS s\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(\t) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the "
            "text as it is",
        ),
    ),
    (
        "var bracket '$(\\t)'",
        "SELECT [$(\t)] FROM t\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(\t) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the "
            "text as it is",
        ),
    ),
    (
        "var quoted '$(\\t)'",
        'SELECT "$(\t)" FROM t\nGO',
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(\t) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the "
            "text as it is",
        ),
    ),
    (
        "var line comment '$(\\t)'",
        "SELECT 1 -- $(\t)\nGO",
        ("ok", [("SELECT 1 -- $(\t)", 1, "GO", 1, 0, 19)], [["SELECT 1 -- $(\t)", 1]]),
    ),
    (
        "var block comment '$(\\t)'",
        "SELECT 1 /* $(\t) */\nGO",
        ("ok", [("SELECT 1 /* $(\t) */", 1, "GO", 1, 0, 22)], [["SELECT 1 /* $(\t) */", 1]]),
    ),
    (
        "var go tail '$(\\t)'",
        "SELECT 1\nGO $(\t)\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it; $(\t) is not substituted",
        ),
    ),
    (
        "var context \"SELECT 'a\\nb\\n$(x)\\nc'\"",
        "SELECT 'a\nb\n$(x)\nc'",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(x) on line 3: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var context 'SELECT [a\\nb\\n$(x)'",
        "SELECT [a\nb\n$(x)",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(x) on line 3: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        'var context "SELECT \'a\\n$(x)"',
        "SELECT 'a\n$(x)",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(x) on line 2: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        'var context "SELECT \'a $(x)"',
        "SELECT 'a $(x)",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(x) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var context 'SELECT \"a\\n$(x)\\nGO'",
        'SELECT "a\n$(x)\nGO',
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(x) on line 2: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var context 'SELECT 1 /* $(x)'",
        "SELECT 1 /* $(x)",
        (
            "error",
            "UnsafeStatementSplitError",
            "unterminated block comment opened at line 1, column 10",
        ),
    ),
    (
        "var context 'SELECT $('",
        "SELECT $(",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $( on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var context 'SELECT $(\\nFROM t'",
        "SELECT $(\nFROM t",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $( on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var context 'SELECT 1\\n$(x)'",
        "SELECT 1\n$(x)",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(x) on line 2: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var context 'SELECT 1\\n  $(x)\\nGO'",
        "SELECT 1\n  $(x)\nGO",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(x) on line 2: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var context 'SELECT 1 $(x) \\rGO'",
        "SELECT 1 $(x) \rGO",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 1: a lone carriage return is not a line break sqlcmd was measured on; end the line "
            "with a newline",
        ),
    ),
    (
        "var context 'SELECT 1 \\rGO $(x)'",
        "SELECT 1 \rGO $(x)",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 1: a lone carriage return is not a line break sqlcmd was measured on; end the line "
            "with a newline",
        ),
    ),
    (
        "var context \"SELECT $(x) 'a' $(y)\"",
        "SELECT $(x) 'a' $(y)",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(x) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var context \"SELECT 'a' $(y)\"",
        "SELECT 'a' $(y)",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(y) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "var context '$(x)\\rGO'",
        "$(x)\rGO",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 1: a lone carriage return is not a line break sqlcmd was measured on; end the line "
            "with a newline",
        ),
    ),
    (
        "var context 'SELECT $(a) /* c */ $(b)'",
        "SELECT $(a) /* c */ $(b)",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(a) on line 1: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "cr 'SELECT 1\\rGO'",
        "SELECT 1\rGO",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 1: a lone carriage return is not a line break sqlcmd was measured on; end the line "
            "with a newline",
        ),
    ),
    (
        "cr 'SELECT 1\\r GO'",
        "SELECT 1\r GO",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 1: a lone carriage return is not a line break sqlcmd was measured on; end the line "
            "with a newline",
        ),
    ),
    (
        "cr 'SELECT 1\\r\\tGO'",
        "SELECT 1\r\tGO",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 1: a lone carriage return is not a line break sqlcmd was measured on; end the line "
            "with a newline",
        ),
    ),
    (
        "cr 'SELECT 1\\r\\rGO'",
        "SELECT 1\r\rGO",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 1: a lone carriage return is not a line break sqlcmd was measured on; end the line "
            "with a newline",
        ),
    ),
    (
        "cr 'SELECT 1\\rgo'",
        "SELECT 1\rgo",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 1: a lone carriage return is not a line break sqlcmd was measured on; end the line "
            "with a newline",
        ),
    ),
    (
        "cr 'SELECT 1\\rGOTO'",
        "SELECT 1\rGOTO",
        ("ok", [("SELECT 1\rGOTO", 1, None, 1, 0, 13)], [["SELECT 1\rGOTO", 1]]),
    ),
    (
        "cr 'SELECT 1\\rGO1'",
        "SELECT 1\rGO1",
        ("ok", [("SELECT 1\rGO1", 1, None, 1, 0, 12)], [["SELECT 1\rGO1", 1]]),
    ),
    (
        "cr 'SELECT 1\\r\\nGO'",
        "SELECT 1\r\nGO",
        ("ok", [("SELECT 1", 1, "GO", 1, 0, 12)], [["SELECT 1", 1]]),
    ),
    ("cr 'SELECT 1\\r'", "SELECT 1\r", ("ok", [("SELECT 1", 1, None, 1, 0, 9)], [["SELECT 1", 1]])),
    (
        "cr 'SELECT 1\\r\\n'",
        "SELECT 1\r\n",
        ("ok", [("SELECT 1", 1, None, 1, 0, 10)], [["SELECT 1", 1]]),
    ),
    (
        "cr '\\rGO'",
        "\rGO",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 1: a lone carriage return is not a line break sqlcmd was measured on; end the line "
            "with a newline",
        ),
    ),
    (
        "cr '\\r\\rGO\\nSELECT 1'",
        "\r\rGO\nSELECT 1",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 1: a lone carriage return is not a line break sqlcmd was measured on; end the line "
            "with a newline",
        ),
    ),
    (
        "cr 'SELECT 1\\r\\r\\nGO'",
        "SELECT 1\r\r\nGO",
        ("ok", [("SELECT 1", 1, "GO", 1, 0, 13)], [["SELECT 1", 1]]),
    ),
    (
        "cr 'SELECT 1\\r\\n\\rGO'",
        "SELECT 1\r\n\rGO",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: a lone carriage return is not a line break sqlcmd was measured on; end the line "
            "with a newline",
        ),
    ),
    (
        "cr 'SELECT 1;\\rGO'",
        "SELECT 1;\rGO",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 1: a lone carriage return is not a line break sqlcmd was measured on; end the line "
            "with a newline",
        ),
    ),
    (
        "cr \"SELECT 'a'\\rGO\"",
        "SELECT 'a'\rGO",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 1: a lone carriage return is not a line break sqlcmd was measured on; end the line "
            "with a newline",
        ),
    ),
    (
        "cr 'SELECT [x]\\rGO'",
        "SELECT [x]\rGO",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 1: a lone carriage return is not a line break sqlcmd was measured on; end the line "
            "with a newline",
        ),
    ),
    (
        "cr 'SELECT \"x\"\\rGO'",
        'SELECT "x"\rGO',
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 1: a lone carriage return is not a line break sqlcmd was measured on; end the line "
            "with a newline",
        ),
    ),
    (
        "cr \"SELECT 'a\\rGO';\\nGO\"",
        "SELECT 'a\rGO';\nGO",
        ("ok", [("SELECT 'a\rGO';", 1, "GO", 1, 0, 17)], [["SELECT 'a\rGO';", 1]]),
    ),
    (
        "cr 'SELECT [x\\rGO];\\nGO'",
        "SELECT [x\rGO];\nGO",
        ("ok", [("SELECT [x\rGO];", 1, "GO", 1, 0, 17)], [["SELECT [x\rGO];", 1]]),
    ),
    (
        "cr 'SELECT 1 /* a\\rGO */\\nGO'",
        "SELECT 1 /* a\rGO */\nGO",
        ("ok", [("SELECT 1 /* a\rGO */", 1, "GO", 1, 0, 22)], [["SELECT 1 /* a\rGO */", 1]]),
    ),
    (
        "cr 'SELECT 1 -- a\\rGO\\nGO'",
        "SELECT 1 -- a\rGO\nGO",
        ("ok", [("SELECT 1 -- a\rGO", 1, "GO", 1, 0, 19)], [["SELECT 1 -- a\rGO", 1]]),
    ),
    (
        "cr 'SELECT 1\\rGO\\r'",
        "SELECT 1\rGO\r",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 1: a lone carriage return is not a line break sqlcmd was measured on; end the line "
            "with a newline",
        ),
    ),
    (
        "cr 'SELECT 1\\rGO;'",
        "SELECT 1\rGO;",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 1: a lone carriage return is not a line break sqlcmd was measured on; end the line "
            "with a newline",
        ),
    ),
    (
        "cr 'SELECT 1\\rGO 2'",
        "SELECT 1\rGO 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 1: a lone carriage return is not a line break sqlcmd was measured on; end the line "
            "with a newline",
        ),
    ),
    (
        "cr 'SELECT 1 /* c */\\rGO'",
        "SELECT 1 /* c */\rGO",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 1: a lone carriage return is not a line break sqlcmd was measured on; end the line "
            "with a newline",
        ),
    ),
    (
        "cr 'SELECT 1\\r/* c */ GO'",
        "SELECT 1\r/* c */ GO",
        ("ok", [("SELECT 1\r/* c */ GO", 1, None, 1, 0, 19)], [["SELECT 1\r/* c */ GO", 1]]),
    ),
    (
        "cr 'SELECT 1\\n\\rGO'",
        "SELECT 1\n\rGO",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: a lone carriage return is not a line break sqlcmd was measured on; end the line "
            "with a newline",
        ),
    ),
    (
        "cr 'SELECT 1\\r\\n\\r\\nGO\\r\\n'",
        "SELECT 1\r\n\r\nGO\r\n",
        ("ok", [("SELECT 1", 1, "GO", 1, 0, 16)], [["SELECT 1", 1]]),
    ),
    (
        "cr \"SELECT 1\\rGO'a'\"",
        "SELECT 1\rGO'a'",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 1: a lone carriage return is not a line break sqlcmd was measured on; end the line "
            "with a newline",
        ),
    ),
    (
        "cr 'SELECT 1\\rGO--'",
        "SELECT 1\rGO--",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 1: a lone carriage return is not a line break sqlcmd was measured on; end the line "
            "with a newline",
        ),
    ),
    (
        "cr 'SELECT 1 \\r\\nGO\\r\\nSELECT 2\\r\\n'",
        "SELECT 1 \r\nGO\r\nSELECT 2\r\n",
        (
            "ok",
            [("SELECT 1", 1, "GO", 1, 0, 15), ("SELECT 2", 3, None, 1, 15, 25)],
            [["SELECT 1", 1], ["SELECT 2", 1]],
        ),
    ),
    (
        "unmeasured 'SELECT 1\\nGO\\x0b\\nSELECT 2'",
        "SELECT 1\nGO\x0b\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it",
        ),
    ),
    (
        "unmeasured 'SELECT 1\\nGO\\x0c\\nSELECT 2'",
        "SELECT 1\nGO\x0c\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it",
        ),
    ),
    (
        "unmeasured 'SELECT 1\\nGO \\x0b\\nSELECT 2'",
        "SELECT 1\nGO \x0b\nSELECT 2",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it",
        ),
    ),
    (
        "unmeasured 'SELECT 1\\nGO\\x0b'",
        "SELECT 1\nGO\x0b",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it",
        ),
    ),
    (
        "unmeasured 'SELECT 1\\nGO\\x0b$(x)'",
        "SELECT 1\nGO\x0b$(x)",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it",
        ),
    ),
    (
        "unmeasured 'SELECT 1\\ngo\\x0c2'",
        "SELECT 1\ngo\x0c2",
        (
            "error",
            "UnsafeStatementSplitError",
            "text after GO on line 2: only a count and a '--' comment may follow it",
        ),
    ),
    (
        'unterminated "SELECT \'open"',
        "SELECT 'open",
        ("error", "UnsafeStatementSplitError", "unterminated string opened at line 1, column 8"),
    ),
    (
        "unterminated 'SELECT [open'",
        "SELECT [open",
        (
            "error",
            "UnsafeStatementSplitError",
            "unterminated bracketed identifier opened at line 1, column 8",
        ),
    ),
    (
        "unterminated 'SELECT \"open'",
        'SELECT "open',
        (
            "error",
            "UnsafeStatementSplitError",
            "unterminated quoted identifier opened at line 1, column 8",
        ),
    ),
    (
        "unterminated 'SELECT 1 /* open'",
        "SELECT 1 /* open",
        (
            "error",
            "UnsafeStatementSplitError",
            "unterminated block comment opened at line 1, column 10",
        ),
    ),
    (
        'unterminated "SELECT 1\\nGO\\nSELECT \'open"',
        "SELECT 1\nGO\nSELECT 'open",
        ("error", "UnsafeStatementSplitError", "unterminated string opened at line 3, column 8"),
    ),
    (
        'unterminated "SELECT \'a\\n$(x)\\n"',
        "SELECT 'a\n$(x)\n",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(x) on line 2: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "unterminated 'SELECT [a\\n$(x)\\n'",
        "SELECT [a\n$(x)\n",
        (
            "error",
            "UnsupportedMetaCommandError",
            "scripting variable $(x) on line 2: sqlcmd substitutes it before the batch is sent, dblift sends the text "
            "as it is",
        ),
    ),
    (
        "unterminated \"SELECT 'a'\\nGO\\nSELECT 'b\\n:setvar x y\\n\"",
        "SELECT 'a'\nGO\nSELECT 'b\n:setvar x y\n",
        ("error", "UnsafeStatementSplitError", "unterminated string opened at line 3, column 8"),
    ),
]


def engine(spec=SQLSERVER_SPEC):
    return LexicalEngine(spec)


def records(script, spec=SQLSERVER_SPEC):
    return [
        (r.text, r.line, r.terminator, r.repeat, r.source_start, r.source_end)
        for r in engine(spec).split(script)
    ]


def strings(script, spec=SQLSERVER_SPEC):
    return [[k, len(list(g))] for k, g in itertools.groupby(engine(spec).split_statements(script))]


def texts(script, spec=SQLSERVER_SPEC):
    return [r.text for r in engine(spec).split(script)]


def varied(**changes):
    return replace(SQLSERVER_SPEC, batch_script=replace(SQLSERVER_SPEC.batch_script, **changes))


@pytest.mark.parametrize("name, script, outcome", CASES, ids=[c[0] for c in CASES])
def test_matches_the_recorded_outcome(name, script, outcome):
    if outcome[0] == "error":
        _, error_class, message = outcome
        for call in (records, strings):
            with pytest.raises((UnsafeStatementSplitError, UnsupportedMetaCommandError)) as raised:
                call(script)
            assert (type(raised.value).__name__, str(raised.value)) == (error_class, message)
        return
    _, expected_records, expected_strings = outcome
    assert records(script) == expected_records
    assert strings(script) == expected_strings


COLON_WORDS = (
    "setvar r connect on exit quit list listvar error out perftrace help serverlist xml reset ed"
).split()


@pytest.mark.parametrize("word", COLON_WORDS)
@pytest.mark.parametrize("form", [str.lower, str.upper, str.capitalize])
def test_colon_command_refused_for_each_word(word, form):
    spelled = form(word)
    with pytest.raises(
        UnsupportedMetaCommandError,
        match=rf"^sqlcmd command ':{spelled}' on line 2: dblift does not run client commands$",
    ):
        engine().split(f"SELECT 1\n:{spelled} x\nGO")


@pytest.mark.parametrize("script", [":setvarx", ":foo", ":setvar_x"])
def test_an_unknown_colon_word_is_text(script):
    assert texts(f"SELECT 1\n{script}\nGO") == [f"SELECT 1\n{script}"]


@pytest.mark.parametrize("follower", list(" \t\r-=(['/") + [""])
@pytest.mark.parametrize("word", ["EXIT", "QUIT", "RESET", "ED"])
def test_bare_command_follower_rule_refuses(word, follower):
    with pytest.raises(UnsupportedMetaCommandError, match=f"sqlcmd command '{word}' on line 2"):
        engine().split(f"SELECT 1\n{word.lower()}{follower}{'x' if follower else ''}\nSELECT 2")


@pytest.mark.parametrize("follower", list(".,;+)*:|<@") + ["a", "_", "9", "#", "$"])
@pytest.mark.parametrize("word", ["EXIT", "QUIT", "RESET", "ED"])
def test_bare_command_follower_rule_text(word, follower):
    script = f"SELECT 1\n{word}{follower}x\nSELECT 2"
    assert texts(script) == [script]


@pytest.mark.parametrize("line", ["!!echo hi", ":!!echo hi", "!!"])
def test_shell_prefix_refused(line):
    with pytest.raises(UnsupportedMetaCommandError, match="dblift does not run client commands"):
        engine().split(f"SELECT 1\n{line}\nGO")


@pytest.mark.parametrize(
    "script",
    ["SELECT 1\n/* c */ :setvar a b", "SELECT 1\n/* c */ EXIT", "SELECT 1\n/* a\nb */ !!x"],
)
def test_command_after_a_comment_is_refused(script):
    with pytest.raises(UnsupportedMetaCommandError):
        engine().split(script)


@pytest.mark.parametrize(
    "script",
    [
        "SELECT '\n:setvar x y\n'",
        "SELECT [\nEXIT\n]",
        'SELECT "\n!!dir\n"',
        "SELECT 1 -- :setvar x\nGO",
        "SELECT 1 /*\nEXIT\n*/\nGO",
    ],
)
def test_directive_inside_a_lexeme_or_comment_is_text(script):
    assert texts(script)[0].startswith("SELECT")


def test_command_mid_statement_is_refused():
    with pytest.raises(UnsupportedMetaCommandError, match="line 2"):
        engine().split("CREATE TABLE t (id INT,\n:setvar x y\n x INT)\nGO")


@pytest.mark.parametrize(
    "blank", ["\xa0", "\x0c", "\x1c", "\x1d", "\x1e", "\x1f", "\x85", "\u2028", "\u2029", "\x0b"]
)
@pytest.mark.parametrize("word", [":setvar x y", "EXIT", "!!dir"])
def test_non_blank_before_a_command_word_makes_it_text(blank, word):
    script = f"SELECT 1\n{blank}{word}\nSELECT 2"
    assert texts(script) == [script]


@pytest.mark.parametrize(
    "script, text",
    [
        ("SELECT $(x)", "$(x)"),
        ("SELECT $(a'b)'", "$(a"),
        ("SELECT $(", "$("),
        ("SELECT $(" + "a" * 41 + ")", "$(" + "a" * 40),
    ],
)
def test_variable_reference_message_text(script, text):
    with pytest.raises(UnsupportedMetaCommandError) as raised:
        engine().split(script)
    assert str(raised.value).startswith(f"scripting variable {text} on line 1: ")


def test_variable_reference_line_is_the_line_of_the_match():
    with pytest.raises(UnsupportedMetaCommandError, match=r"\$\(x\) on line 3: "):
        engine().split("SELECT 'a\nb\nc $(x)\nd'")


def test_go_tail_carries_the_variable_hint():
    with pytest.raises(
        UnsafeStatementSplitError, match=r"may follow it; \$\(n\) is not substituted$"
    ):
        engine().split("SELECT 1\nGO $(n)\n")


def test_lone_cr_before_go_is_refused_in_code_only():
    with pytest.raises(UnsafeStatementSplitError, match="lone carriage return"):
        engine().split("SELECT 'a'\rGO")
    assert len(texts("SELECT 1\r\nGO\r\nSELECT 2\r\n")) == 2
    assert texts("SELECT 'a\rGO';\nGO") == ["SELECT 'a\rGO';"]
    assert texts("SELECT 1\r") == ["SELECT 1"]


@pytest.mark.parametrize("script", ["SELECT 1\nGO\x0b\nSELECT 2", "SELECT 1\nGO\x0c\nSELECT 2"])
def test_unmeasured_blank_after_go_is_refused(script):
    with pytest.raises(UnsafeStatementSplitError, match="text after GO on line 2: only a count"):
        engine().split(script)


@pytest.mark.parametrize("word", ["setvar", "SetVar", "SETVAR", "Exit", "ConNect", "LISTvar"])
def test_mixed_case_colon_commands_are_commands(word):
    with pytest.raises(UnsupportedMetaCommandError, match=f"command ':{word}' on line 1"):
        engine().split(f":{word} a b")


PAIRS = json.loads((Path(__file__).parent / "sqlserver_refusal_pairs.json").read_text())


@pytest.mark.parametrize("script, expected", PAIRS, ids=[f"pair-{i}" for i in range(len(PAIRS))])
def test_refusals_are_raised_in_source_order(script, expected):
    if expected is None:
        engine().split(script)
        return
    error_class, message = expected
    with pytest.raises((UnsafeStatementSplitError, UnsupportedMetaCommandError)) as raised:
        engine().split(script)
    assert (type(raised.value).__name__, str(raised.value)) == (error_class, message)


def test_a_lone_cr_in_a_segment_is_refused_before_an_earlier_variable_of_that_segment():
    with pytest.raises(UnsafeStatementSplitError, match="lone carriage return"):
        engine().split("SELECT 1 $(x) \rGO")
    with pytest.raises(UnsupportedMetaCommandError, match=r"\$\(x\)"):
        engine().split("SELECT 1 $(x) 'a'\rGO")


def test_bare_commands_are_a_spec_field():
    assert texts("SELECT 1\nQUIT\nGO", varied(bare_commands=("EXIT",))) == ["SELECT 1\nQUIT"]
    with pytest.raises(UnsupportedMetaCommandError, match="command 'FOO'"):
        engine(varied(bare_commands=("FOO",))).split("SELECT 1\nfoo\nGO")


def test_colon_commands_are_a_spec_field():
    spec = varied(colon_commands=("r",))
    assert texts("SELECT 1\n:setvar a b\nGO", spec) == ["SELECT 1\n:setvar a b"]
    with pytest.raises(UnsupportedMetaCommandError, match="command ':r'"):
        engine(spec).split("SELECT 1\n:r f\nGO")


def test_shell_prefix_is_a_spec_field():
    assert texts("SELECT 1\n!!x\nGO", varied(shell_prefix="##")) == ["SELECT 1\n!!x"]
    with pytest.raises(UnsupportedMetaCommandError, match="command '##x'"):
        engine(varied(shell_prefix="##")).split("SELECT 1\n##x\nGO")


def test_unmeasured_blanks_are_a_spec_field():
    script = "SELECT 1\nGO\x0b\nSELECT 2"
    with pytest.raises(UnsafeStatementSplitError, match="text after GO on line 2"):
        engine().split(script)
    assert texts(script, varied(unmeasured_blanks=frozenset())) == [script]


def test_lone_cr_words_are_a_spec_field():
    spec = varied(lone_cr_words=("STOP",))
    assert texts("SELECT 1\rGO\nSELECT 2", spec) == ["SELECT 1\rGO\nSELECT 2"]
    with pytest.raises(UnsafeStatementSplitError, match="lone carriage return"):
        engine().split("SELECT 1\rGO\nSELECT 2")
    with pytest.raises(UnsafeStatementSplitError, match="lone carriage return"):
        engine(spec).split("SELECT 1\rSTOP")


def test_variable_reference_is_a_spec_field():
    spec = varied(variable_reference=("@(", ")"))
    assert texts("SELECT $(x)", spec) == ["SELECT $(x)"]
    with pytest.raises(UnsupportedMetaCommandError, match=r"scripting variable @\(x\) on line 1"):
        engine(spec).split("SELECT @(x)")
