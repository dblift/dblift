# dblift-ui

Local web interface for DBLift migrations.

    pip install dblift-ui
    dblift ui

The command starts a server on `127.0.0.1`, prints a one-time URL and opens it
in the browser. Nothing is sent anywhere else.

Status: early development. The interface shows a list of projects and the
migration status of each project per environment. Projects are added by
opening a folder or cloning a repository; the config files in it are found
automatically, a repository may hold several, and projects of one repository
are grouped together in the list. From the status view you can preview the SQL of pending migrations
and apply them, undo the last migration, validate, repair the history after a
failed run, and baseline a database that has no history yet. Nothing that
changes a database runs without a confirming click. A run's full log can be
opened from its run log.

A migration opens in a code editor from the status view, with its undo script
on a second tab; a migration that is already applied opens with a warning
about its checksum. New migrations, SQL or Python, versioned (with an empty
undo script beside them) or repeatable, are created from the interface. Only
files in the project's configured migration directories can be read or
written, and job logs are kept out of the project folder.

A configuration can be created for a folder that has migrations but no config
file, and edited from the project view. Both go through a form with a live
preview of the file, checked by the DBLift config loader before it can be
saved; editing keeps the file's comments. A password defaults to an
environment-variable placeholder, and a password already saved in the file is
never displayed.

A Flyway project found in a folder can be converted: its settings pre-fill the
configuration form (its password is never copied), and the project view then
offers to import its Flyway history, after a preview, so that what Flyway
already applied is not offered again.

For a project in a git repository, the header shows the current branch with
the number of uncommitted files and of commits ahead of and behind its remote
branch. Its menu lists the local and remote branches to switch to (a remote
one becomes a local branch that tracks it), creates a branch, fetches, pulls
when that needs no merge (fast-forward only), pushes the current branch
(publishing it to `origin` the first time), and commits: the changed files are
listed with the project's own changed scripts and config ticked, and only the
ticked files are committed. Uncommitted migrations are marked in the
migration list, and a script open in the editor shows its changes since the
last commit. After a switch or a pull, configs the branch brought in are
offered as new projects, and a project whose config is not on the current
branch is shown as such. Merging, rebasing, stashing and forced pushes are
deliberately absent: when a pull would need a merge, or git refuses a switch,
the interface says why and leaves the rest to your own git tool.

## Development

The interface lives in `frontend/` (React, TypeScript, Vite). It is built into
`dblift_ui/static/app/`, which the server serves. That folder is not committed.

    cd packages/dblift-ui/frontend
    npm ci
    npm run build:watch        # rebuilds on change

In another terminal:

    pip install -e "packages/dblift-ui[dev]"
    dblift ui

Checks:

    npm run typecheck && npm test          # interface
    npx playwright install chromium        # once, before the first browser test run
    npm run build && npm run e2e           # browser tests; set PYTHON to an interpreter with dblift-ui installed
    python -m pytest packages/dblift-ui/tests   # server

Without a build, the server shows a placeholder page.

The interface loads nothing from the network: fonts are bundled, and it talks
only to the local server that started it.
