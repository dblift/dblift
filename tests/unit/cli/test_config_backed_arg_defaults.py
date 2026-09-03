"""Config-backed properties reach the command handlers, not just the config object.

``dblift config`` advertises an environment variable for every registry
property, and ``DbliftConfig.from_env_dict`` really does read them — but the
command handlers took their values from the argparse namespace alone, so the
config layer was inert for anything the handlers own.

The dangerous case is ``dry_run``. Setting ``DBLIFT_DRY_RUN=true`` and running
``migrate`` applied every migration for real and exited 0, with nothing in the
output to say the flag had been ignored. The tool advertised the variable
itself, which is what makes it a trap rather than a missing feature.
"""

from argparse import Namespace

import pytest

from dblift.cli.main import _apply_config_backed_defaults

pytestmark = [pytest.mark.unit]


class _Config:
    """Stand-in for DbliftConfig carrying only what the helper reads."""

    def __init__(self, **values):
        self.__dict__.update(values)


def test_an_explicit_clean_enabled_is_not_re_disabled():
    """The trap a falsy "is it set?" test walks into.

    ``clean_disabled`` defaults True and ``--clean-enabled`` sets it False, so
    False there is the user unlocking a destructive command, not an absent
    value. Reading it as absent would put the guard back on silently.
    """
    args = Namespace(clean_disabled=False, command="clean")
    _apply_config_backed_defaults(args, _Config(clean_disabled=True))

    assert args.clean_disabled is False


def test_an_unset_flag_takes_the_config_value():
    """The env layer already fills the config; the handler must see it."""
    args = Namespace(dry_run=False, command="migrate")
    _apply_config_backed_defaults(args, _Config(dry_run=True))

    assert args.dry_run is True


def test_an_explicit_flag_beats_the_config():
    """Precedence is CLI over environment over file, in that order."""
    args = Namespace(target_version="7", command="migrate")
    _apply_config_backed_defaults(args, _Config(target_version="3"))

    assert args.target_version == "7"


def test_a_config_default_does_not_invent_a_value():
    """A config that says nothing must leave the namespace alone."""
    args = Namespace(dry_run=False, target_version=None, command="migrate")
    _apply_config_backed_defaults(args, _Config(dry_run=False, target_version=None))

    assert args.dry_run is False
    assert args.target_version is None


def test_arguments_the_namespace_does_not_carry_are_left_alone():
    """Subcommands only declare their own flags; the walk must not add any.

    A handler reads ``getattr(args, name)`` for the flags its own parser
    declared. Inventing attributes here would let a value set for one
    subcommand leak into another that never offered it.
    """
    args = Namespace(command="info")
    _apply_config_backed_defaults(args, _Config(dry_run=True, target_version="3"))

    assert not hasattr(args, "dry_run")
    assert not hasattr(args, "target_version")


def test_a_missing_config_is_not_an_error():
    """``db`` subcommands run without a config at all."""
    args = Namespace(dry_run=False, command="db")
    _apply_config_backed_defaults(args, None)

    assert args.dry_run is False


def test_database_fields_are_left_to_their_own_machinery():
    """``database.*`` has its own DBLIFT_DB_* allowlist and aliasing.

    Those fields are already merged into the config before the parser runs,
    and their argparse dests do not match the dotted registry names, so the
    walk must skip them rather than half-apply a second path.
    """
    args = Namespace(db_url="postgresql://cli/db", command="migrate")
    _apply_config_backed_defaults(args, _Config(database=_Config(url="postgresql://file/db")))

    assert args.db_url == "postgresql://cli/db"
