#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# dblift Rich console demo — runs against a real PostgreSQL 16 Docker container
#
# Usage:  bash scripts/demo_live.sh
# Requires: Docker running, venv at ./venv
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DBLIFT="$REPO/venv/bin/python -m cli.main"
WORKDIR="$(mktemp -d)/dblift_live_demo"
MIGDIR="$WORKDIR/migrations"
SNAPDIR="$WORKDIR/snapshots"
LOGS="$WORKDIR/logs"
mkdir -p "$LOGS"

# Global flags injected into every command
LOG_ARGS="--log-format text,json,html --log-dir $LOGS"

PG_ARGS="--db-url postgresql+psycopg://localhost:5432/testdb
         --db-username dblift_demo
         --db-password dblift_demo
         --db-schema dblift_demo"

red()    { printf '\033[1;31m%s\033[0m\n' "$*"; }
green()  { printf '\033[1;32m%s\033[0m\n' "$*"; }
cyan()   { printf '\033[1;36m%s\033[0m\n' "$*"; }
bold()   { printf '\033[1m%s\033[0m\n' "$*"; }
banner() { echo; cyan "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"; bold "  $*"; cyan "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"; echo; }
pause()  { echo; read -rp "  $(bold '[enter to continue]') "; echo; }

# ── 0. Bootstrap ─────────────────────────────────────────────────────────────
banner "0 / SETUP"

mkdir -p "$MIGDIR" "$SNAPDIR"
echo "Work dir : $WORKDIR"

# Check container running
if ! docker inspect dblift_demo_pg &>/dev/null; then
  echo "Starting PostgreSQL 16 container..."
  docker run -d \
    --name dblift_demo_pg \
    -e POSTGRES_PASSWORD=demo \
    -e POSTGRES_DB=testdb \
    -p 5432:5432 \
    postgres:16
  until docker exec dblift_demo_pg pg_isready -U postgres -d testdb &>/dev/null; do
    printf '.'; sleep 2
  done
  echo
fi

# (Re-)create demo schema
docker exec -i dblift_demo_pg psql -U postgres testdb <<'SQL' 2>/dev/null || true
DROP SCHEMA IF EXISTS dblift_demo CASCADE;
DROP USER IF EXISTS dblift_demo;
CREATE USER dblift_demo WITH PASSWORD 'dblift_demo';
CREATE SCHEMA dblift_demo AUTHORIZATION dblift_demo;
GRANT ALL PRIVILEGES ON SCHEMA dblift_demo TO dblift_demo;
GRANT CREATE ON DATABASE testdb TO dblift_demo;
SQL
echo "PostgreSQL schema ready."

# ── Write migration scripts ──────────────────────────────────────────────────
cat > "$MIGDIR/V1__baseline_schema.sql" <<'SQL'
CREATE TABLE dblift_demo.users (
    id          SERIAL PRIMARY KEY,
    email       VARCHAR(255) NOT NULL UNIQUE,
    full_name   VARCHAR(100),
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    is_active   BOOLEAN DEFAULT TRUE,
    CHECK (email LIKE '%@%')
);
CREATE TABLE dblift_demo.products (
    id          SERIAL PRIMARY KEY,
    sku         VARCHAR(50) NOT NULL UNIQUE,
    name        VARCHAR(200) NOT NULL,
    price       NUMERIC(10,2) NOT NULL,
    stock_qty   INTEGER DEFAULT 0
);
CREATE TABLE dblift_demo.orders (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES dblift_demo.users(id),
    total_amount    NUMERIC(10,2) NOT NULL,
    status          VARCHAR(20) DEFAULT 'pending',
    placed_at       TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CHECK (status IN ('pending','processing','shipped','delivered','cancelled'))
);
CREATE INDEX idx_orders_user_id ON dblift_demo.orders(user_id);
CREATE INDEX idx_products_sku   ON dblift_demo.products(sku);
CREATE VIEW dblift_demo.v_active_users AS
    SELECT id, email, full_name FROM dblift_demo.users WHERE is_active = TRUE;
CREATE SEQUENCE dblift_demo.invoice_seq START 1000 INCREMENT 1;
SQL

cat > "$MIGDIR/V2__categories.sql" <<'SQL'
CREATE TABLE dblift_demo.categories (
    id    SERIAL PRIMARY KEY,
    slug  VARCHAR(80) NOT NULL UNIQUE,
    label VARCHAR(100) NOT NULL
);
ALTER TABLE dblift_demo.products ADD COLUMN category_id INTEGER REFERENCES dblift_demo.categories(id);
SQL

cat > "$MIGDIR/V3__audit.sql" <<'SQL'
CREATE TABLE dblift_demo.audit_log (
    id         BIGSERIAL PRIMARY KEY,
    table_name VARCHAR(100),
    operation  VARCHAR(10),
    row_id     INTEGER,
    changed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE OR REPLACE FUNCTION dblift_demo.fn_audit_orders() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO dblift_demo.audit_log(table_name, operation, row_id)
    VALUES ('orders', TG_OP, COALESCE(NEW.id, OLD.id));
    RETURN NEW;
END; $$;
CREATE TRIGGER trg_audit_orders
AFTER INSERT OR UPDATE OR DELETE ON dblift_demo.orders
FOR EACH ROW EXECUTE FUNCTION dblift_demo.fn_audit_orders();
SQL

cat > "$MIGDIR/V4__reporting.sql" <<'SQL'
CREATE VIEW dblift_demo.v_order_summary AS
    SELECT u.email, COUNT(o.id) total_orders, SUM(o.total_amount) lifetime_value
    FROM dblift_demo.users u JOIN dblift_demo.orders o ON o.user_id = u.id
    GROUP BY u.email;
CREATE OR REPLACE FUNCTION dblift_demo.fn_order_count(p_user_id INTEGER)
RETURNS INTEGER LANGUAGE sql AS $$
    SELECT COUNT(*) FROM dblift_demo.orders WHERE user_id = p_user_id;
$$;
SQL

cat > "$MIGDIR/R__seed_categories.sql" <<'SQL'
TRUNCATE dblift_demo.categories RESTART IDENTITY CASCADE;
INSERT INTO dblift_demo.categories (slug, label) VALUES
    ('electronics','Electronics'),('clothing','Clothing'),
    ('books','Books'),('home','Home & Garden');
SQL

green "✓  5 migration scripts written."
pause

# ── 1. check-connection ───────────────────────────────────────────────────────
banner "1 / DB CHECK-CONNECTION"
$DBLIFT $LOG_ARGS db check-connection $PG_ARGS
pause

# ── 2. migrate ────────────────────────────────────────────────────────────────
banner "2 / MIGRATE — Rich progress bar + status panel"
echo "  Running 4 versioned migrations + 1 repeatable…"
echo
$DBLIFT $LOG_ARGS migrate $PG_ARGS --scripts "$MIGDIR"
pause

# ── 3. info ───────────────────────────────────────────────────────────────────
banner "3 / INFO — colored migration status table (V=green, R=green)"
$DBLIFT $LOG_ARGS info $PG_ARGS --scripts "$MIGDIR"
pause

# ── 4. snapshot ───────────────────────────────────────────────────────────────
banner "4 / SNAPSHOT — status spinner while capturing live schema"
SNAP="$SNAPDIR/v4.json"
$DBLIFT $LOG_ARGS snapshot $PG_ARGS --source live-database --output "$SNAP"
echo "Snapshot: $(wc -c < "$SNAP") bytes → $SNAP"
pause

# ── 5. introduce schema drift ─────────────────────────────────────────────────
banner "5 / INTRODUCE SCHEMA DRIFT (outside migrations)"
docker exec -i dblift_demo_pg psql -U postgres testdb <<'SQL'
ALTER TABLE dblift_demo.orders ADD COLUMN payment_method VARCHAR(50);
ALTER TABLE dblift_demo.orders ADD COLUMN fulfilled_at   TIMESTAMP WITH TIME ZONE;
DROP VIEW  dblift_demo.v_active_users;
DROP FUNCTION dblift_demo.fn_order_count(INTEGER);
CREATE INDEX idx_orders_status ON dblift_demo.orders(status);
SQL
green "✓  Added 2 columns, dropped 1 view, dropped 1 function, added 1 index."
pause

# ── 6. diff ───────────────────────────────────────────────────────────────────
banner "6 / DIFF live vs snapshot — red panel + Tree + SQL preview"
$DBLIFT $LOG_ARGS diff $PG_ARGS \
    --snapshot-model "$SNAP" \
    --generate-sql \
    --output-file "$WORKDIR/drift.sql" || true   # exits 1 when diffs found
pause

# ── 7. add a pending migration ────────────────────────────────────────────────
banner "7 / INFO again — Pending row (yellow) alongside Success rows (green)"
cat > "$MIGDIR/V5__add_payment_method.sql" <<'SQL'
-- This migration formalises the ad-hoc column already added above
ALTER TABLE dblift_demo.orders
    ALTER COLUMN payment_method SET DEFAULT 'card';
SQL
$DBLIFT $LOG_ARGS info $PG_ARGS --scripts "$MIGDIR"
pause

# ── 8. simulate a failed migration ────────────────────────────────────────────
banner "8 / MIGRATE with a FAILED migration — red Failed row in info table"
cat > "$MIGDIR/V6__intentional_failure.sql" <<'SQL'
-- This will fail: column already exists from the live drift above
ALTER TABLE dblift_demo.orders ADD COLUMN payment_method VARCHAR(50);
SQL
$DBLIFT $LOG_ARGS migrate $PG_ARGS --scripts "$MIGDIR" || true
echo
echo "Now run info — V6 should appear as Failed (red):"
echo
$DBLIFT $LOG_ARGS info $PG_ARGS --scripts "$MIGDIR" || true
pause

# ── 9. repair ─────────────────────────────────────────────────────────────────
banner "9 / REPAIR — clear the failed migration record"
$DBLIFT $LOG_ARGS repair $PG_ARGS --scripts "$MIGDIR"
pause

# ── 10. clean ────────────────────────────────────────────────────────────────
banner "10 / CLEAN — drops all schema objects + SUCCESS panel"
$DBLIFT $LOG_ARGS clean $PG_ARGS --clean-enabled
pause

# ── done ─────────────────────────────────────────────────────────────────────
banner "DEMO COMPLETE"
green "All 10 features demonstrated against live PostgreSQL 16."
echo
echo "Container left running. To remove:"
echo "  docker rm -f dblift_demo_pg"
echo
echo "Work dir : $WORKDIR"
echo
echo "Logs written to: $LOGS"
echo "  Text : $(ls "$LOGS"/*.log  2>/dev/null | head -1 || echo '(none)')"
echo "  JSON : $(ls "$LOGS"/*.json 2>/dev/null | head -1 || echo '(none)')"
echo "  HTML : $(ls "$LOGS"/*.html 2>/dev/null | head -1 || echo '(none)')"
echo
echo "Open the HTML report:"
echo "  open $(ls "$LOGS"/*.html 2>/dev/null | head -1 || echo "$LOGS")"
