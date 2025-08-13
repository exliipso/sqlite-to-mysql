# SQLite → MySQL Migrator

Simple desktop tool to copy tables from a SQLite database (including Garry's Mod `sv.db`) into a MySQL database (for mysqloo-based addons or general use). Pick your DB, choose tables, enter MySQL details, hit Start.

## What it does
- Reads a SQLite database file (e.g., GMod `sv.db` or any other `.db/.sqlite`)
- Lets you select which tables to migrate
- Creates matching tables in MySQL with sensible type mapping
- Copies data in batches with progress and a live log

## Download and install
- Download the latest `sqlite2mysql.exe` from Releases and run it. No installation needed.


## How to use
1) Open the app.
2) Click “Browse…” and select your `sv.db` (usually in `garrysmod/sv.db`).
3) Click “Load Tables”.
4) Select one or more tables (or click “Select All”).
5) Fill in MySQL details: host, port, user, password, database.
6) Options (optional):
   - Drop and recreate tables: clears existing tables before migrating
   - Disable foreign key checks: helps when tables reference each other
7) Click “Start Migration” and watch the log. When it says “Migration completed successfully.” you’re done.

## Tips
- Back up your data first.
- If you’re unsure, test with a new/empty MySQL database.
- Large tables are handled in chunks so the app stays responsive.
- If your MySQL user doesn’t have permission to create databases/tables, uncheck “Create database if missing” and pre-create them.

## Troubleshooting
- Can’t connect / access denied: check host/port/user/password. Try connecting with another MySQL client to verify.
- Unknown database: either create it in MySQL first or keep “Create database if missing” enabled.
- Foreign key errors: enable “Disable foreign key checks during import” or migrate referenced tables first.
- Character issues (e.g., emojis): the app creates tables with `utf8mb4` by default. Ensure your MySQL server supports it.

## Notes
- Type mapping is best-effort. Most GMod tables work out-of-the-box; addons with unusual schemas may need tweaks after migration.
