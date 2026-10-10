CREATE TABLE IF NOT EXISTS callback_log (id INTEGER PRIMARY KEY AUTOINCREMENT, event TEXT);
INSERT INTO callback_log (event) VALUES ('beforeMigrate');
