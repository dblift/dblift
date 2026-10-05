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

## A new change, step by step

"New change" in the project view opens a guided flow for one schema change:

1. **Describe** what the change does. The first line names the migration and
   its undo script, the commit and the pull request. In a git repository on
   `main`, `master` or `develop`, a branch named after that line is offered
   (`feature/add-invoices`) and created before the scripts.
2. **Write** the migration and its undo script, side by side. They are saved
   when you go on.
3. **Test** them on a scratch database (see below), or continue without the
   test.
4. **Commit**: the changed files are listed with the two new scripts ticked,
   and the message is the description's first line.
5. **Publish** the branch to `origin` (or push it, once it has a remote
   branch). For a GitHub, GitLab or Bitbucket remote, a link opens the host's
   pull-request page with the title and the description filled in. For any
   other remote, the title and the description are shown, ready to copy.

The last two steps appear only in a git repository. The description of the
pull request lists the two scripts and says how the scratch test ended.

### The scratch test

The test never touches the project's own databases. It builds a database
from zero by applying every migration, the new one included, then runs the
new migration's undo script, then applies the new migration again. A failure
shows the phase that failed and the database's own error. The scripts can then
be fixed and the test run again.

Where it runs is chosen from the configuration and shown before anything runs:

- **A SQLite project** is tested on a temporary SQLite file. The file is
  created, used and deleted.
- **Any other engine** is tested on the environment literally named `scratch`
  in the configuration. That environment's database is **emptied first**, after
  a confirming click.
- Without either, the test is not available.

Safety rules:

- Only the environment named `scratch` is ever emptied.
- The test refuses to run, and changes nothing, when `scratch` points at the
  same database as the default connection or another environment. It also
  refuses when its database cannot be identified.
- The `scratch` environment must be a database of its own. The comparison
  reads the configured addresses, so two different addresses for one server
  (a host name and its IP address, say) are not detected.

Known limits:

- The undo check undoes the last applied migration, so the new migration
  must have the highest version.
- Migrations that hard-code schema names can fail on, or reach outside, the
  scratch environment.
- Replaying every migration from zero can take long on a very large project.

To skip the test, choose "Continue without the test". The pull request then
says "Skipped. CI should run the migrations before this is merged." If the
developer goes on after a failed run, it says the test failed and why.

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
