"""Db2 lexical facts from docs/sql-parsing/db2.md."""

from dblift.core.sql_parser.lexical_spec import LexicalSpec, RoutineRules, TerminatorScriptRules

DB2_ROUTINES = RoutineRules(
    create_verb="CREATE",
    replace_word="OR",
    kinds=frozenset({"PROCEDURE", "FUNCTION", "TRIGGER", "METHOD"}),
    package_kind="PACKAGE",
    package_openers=frozenset({"AS", "IS"}),
    alter_verb="ALTER",
    alter_kinds=frozenset({"MODULE"}),
    body_open="BEGIN",
    depth_words=frozenset({"BEGIN", "CASE"}),
    body_close="END",
    end_qualifiers=frozenset({"IF", "WHILE", "FOR", "LOOP", "REPEAT"}),
    case_word="CASE",
)

#: First words of CLP commands that no SQL statement starts with (the CLP's own ``?`` listing).
FIRST_WORDS = frozenset("""
    ACTIVATE ADD ARCHIVE ATTACH AUTOCONFIGURE BACKUP BIND CATALOG CHANGE COMPLETE CONNECT
    DEACTIVATE DECOMPOSE DEREGISTER DESCRIBE DETACH ECHO EDIT EXPORT FORCE GET HELP HISTORY
    IMPORT INITIALIZE INSPECT LIST LOAD PING PRECOMPILE PREP PRUNE PUT QUERY QUIESCE QUIT
    REBIND RECOVER REDISTRIBUTE REGISTER REORG REORGCHK RESET RESTART RESTORE REWIND
    ROLLFORWARD RUNCMD RUNSTATS START STOP TAKEOVER TERMINATE UNCATALOG UNQUIESCE UPGRADE
    """.split())

#: CLP commands whose first word also starts an SQL statement: the next words decide.
#: ``CREATE DATABASE`` and ``DROP DATABASE`` are not here on purpose: the server rejects them
#: with an error, and ``CREATE DATABASE LINK`` is SQL other dialects write.
FIRST_PHRASES = frozenset(
    {
        ("DROP", "DBPARTITIONNUM"),
        ("REFRESH", "LDAP"),
        ("SET", "CLIENT"),
        ("SET", "RUNTIME"),
        ("SET", "TABLESPACE"),
        ("SET", "TAPE"),
        ("SET", "UTIL_IMPACT_PRIORITY"),
        ("SET", "WRITE"),
        ("UPDATE", "COMMAND", "OPTIONS"),
        ("UPDATE", "DATABASE", "CONFIGURATION"),
        ("UPDATE", "DATABASE", "MANAGER"),
        ("UPDATE", "DB", "CFG"),
        ("UPDATE", "DB", "CONFIGURATION"),
        ("UPDATE", "DB", "MANAGER"),
        ("UPDATE", "DBM", "CFG"),
        ("UPDATE", "DBM", "CONFIGURATION"),
        ("UPDATE", "ALERT", "CFG"),
        ("UPDATE", "ALERT", "CONFIGURATION"),
        ("UPDATE", "CLI", "CFG"),
        ("UPDATE", "CLI", "CONFIGURATION"),
        ("UPDATE", "HISTORY", "FOR"),
        ("UPDATE", "HISTORY", "EID"),
        ("UPDATE", "LDAP", "NODE"),
        ("UPDATE", "MONITOR", "SWITCHES"),
    }
)

DB2_RULES = TerminatorScriptRules(
    initial=";",
    blanks=" \t",
    directive_name="--#SET TERMINATOR",
    directive=r"[ \t]*--#SET +TERMINATOR(?!\w)",
    directive_value=r" +(\S{1,2})[ \t]*\Z",
    directive_syntax="one or two characters after the keyword, separated from it by blanks",
    line_comment="--",
    comment_block="(=",
    word=r"[A-Za-z_][A-Za-z0-9_$#@]*",
    leading_word=r"[A-Za-z_][A-Za-z0-9_]*",
    command_prefixes="!?",
    command_words=FIRST_WORDS,
    command_phrases=FIRST_PHRASES,
    sql_phrases=frozenset({("GET", "DIAGNOSTICS")}),
    epilogue_words=frozenset({("TERMINATE",), ("QUIT",), ("CONNECT", "RESET")}),
    epilogue=r"(?i)(?:QUIT|TERMINATE|CONNECT[ \t]+RESET)[ \t]*(?:--.*|/\*.*?\*/[ \t]*)?\Z",
    driver_name="ibm_db",
    routine=DB2_ROUTINES,
)

DB2_SPEC = LexicalSpec(
    name="db2",
    client_name="CLP",
    nested_comments=True,
    quoted_identifier='"',
    leading_bom_is_blank=True,
    redaction_reads_engine=False,
    terminator_script=DB2_RULES,
)
