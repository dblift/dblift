CREATE TABLE sentinel (id INTEGER PRIMARY KEY, value TEXT);
UPDATE rollback_marker SET value = 'attempted' WHERE id = 1;
INSERT INTO missing_table (id) VALUES (1);
INSERT INTO sentinel (id, value) VALUES (1, 'never');
