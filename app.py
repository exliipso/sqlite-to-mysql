import os
import queue
import re
import sqlite3
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import mysql.connector
from mysql.connector import errorcode

import tkinter as tk
from tkinter import filedialog, messagebox
import tkinter.ttk as ttk
import sys

BATCH_SIZE = 1000

@dataclass
class MySQLConfig:
    host: str
    port: int
    user: str
    password: str
    database: str
    create_database: bool

class MigratorApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("SQLite → MySQL Migrator by exliipso")
        self.root.geometry("1000x900+50+50")
        self.root.minsize(900, 700)

        self._current_icon_img: Optional[tk.PhotoImage] = None

        self._build_ui()
        self._apply_default_icon()

        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.is_migrating = False

        self.root.after(100, self._drain_log_queue)

    def _build_ui(self) -> None:
        pad = 8

        sqlite_frame = tk.LabelFrame(self.root, text="SQLite source")
        sqlite_frame.pack(fill=tk.X, padx=pad, pady=pad)

        self.sqlite_path_var = tk.StringVar()
        tk.Label(sqlite_frame, text="File:").grid(row=0, column=0, sticky="w", padx=pad, pady=pad)
        tk.Entry(sqlite_frame, textvariable=self.sqlite_path_var, width=80).grid(row=0, column=1, padx=pad, pady=pad)
        tk.Button(sqlite_frame, text="Browse…", command=self._browse_sqlite).grid(row=0, column=2, padx=pad, pady=pad)
        tk.Button(sqlite_frame, text="Load Tables", command=self._load_tables).grid(row=0, column=3, padx=pad, pady=pad)

        tables_frame = tk.LabelFrame(self.root, text="Tables")
        tables_frame.pack(fill=tk.X, expand=False, padx=pad, pady=pad)
        self.tables_listbox = tk.Listbox(tables_frame, selectmode=tk.EXTENDED, height=6)
        self.tables_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(pad, 0), pady=pad)

        tables_scrollbar = tk.Scrollbar(tables_frame, orient=tk.VERTICAL, command=self.tables_listbox.yview)
        tables_scrollbar.pack(side=tk.LEFT, fill=tk.Y, pady=pad)
        self.tables_listbox.configure(yscrollcommand=tables_scrollbar.set)
        btns_frame = tk.Frame(tables_frame)
        btns_frame.pack(side=tk.LEFT, fill=tk.Y, padx=pad, pady=pad)
        tk.Button(btns_frame, text="Select All", command=self._select_all_tables).pack(fill=tk.X, pady=(0, 4))
        tk.Button(btns_frame, text="Clear", command=self._clear_tables_selection).pack(fill=tk.X)

        mysql_frame = tk.LabelFrame(self.root, text="MySQL destination")
        mysql_frame.pack(fill=tk.X, padx=pad, pady=pad)

        self.mysql_host_var = tk.StringVar(value="127.0.0.1")
        self.mysql_port_var = tk.StringVar(value="3306")
        self.mysql_user_var = tk.StringVar(value="root")
        self.mysql_password_var = tk.StringVar()
        self.mysql_database_var = tk.StringVar()
        self.create_db_var = tk.BooleanVar(value=True)
        self.drop_recreate_var = tk.BooleanVar(value=False)
        self.disable_fk_var = tk.BooleanVar(value=True)

        self._grid_kv(mysql_frame, 0, "Host", self.mysql_host_var)
        self._grid_kv(mysql_frame, 1, "Port", self.mysql_port_var)
        self._grid_kv(mysql_frame, 2, "User", self.mysql_user_var)
        self._grid_kv(mysql_frame, 3, "Password", self.mysql_password_var, show="*")
        self._grid_kv(mysql_frame, 4, "Database", self.mysql_database_var)

        opts_frame = tk.Frame(mysql_frame)
        opts_frame.grid(row=0, column=4, rowspan=5, padx=pad, pady=pad, sticky="nsew")
        tk.Checkbutton(opts_frame, text="Create database if missing", variable=self.create_db_var).pack(anchor="w")
        tk.Checkbutton(opts_frame, text="Drop and recreate tables", variable=self.drop_recreate_var).pack(anchor="w")
        tk.Checkbutton(opts_frame, text="Disable foreign key checks during import", variable=self.disable_fk_var).pack(anchor="w")

        actions_frame = tk.Frame(self.root)
        actions_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=pad, pady=(0, pad))

        self.progress_var = tk.DoubleVar(value=0.0)

        self.progress = ttk.Progressbar(actions_frame, orient="horizontal", mode="determinate", maximum=100.0, variable=self.progress_var)
        self.progress.pack(fill=tk.X, padx=pad, pady=pad)

        self.status_var = tk.StringVar(value="Idle")
        tk.Label(actions_frame, textvariable=self.status_var).pack(side=tk.LEFT, padx=pad)
        self.start_btn = tk.Button(actions_frame, text="Start Migration", command=self._start_migration)
        self.start_btn.pack(side=tk.RIGHT, padx=pad)

        log_frame = tk.LabelFrame(self.root, text="Log")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=pad, pady=pad)
        self.log_text = tk.Text(log_frame, wrap=tk.NONE)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        log_scrollbar = tk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.configure(yscrollcommand=log_scrollbar.set)

    def _grid_kv(self, frame: tk.Misc, row: int, label: str, var: tk.Variable, show: Optional[str] = None) -> None:
        pad = 8
        tk.Label(frame, text=f"{label}:").grid(row=row, column=0, sticky="e", padx=pad, pady=pad)
        entry = tk.Entry(frame, textvariable=var, width=20, show=show)
        entry.grid(row=row, column=1, sticky="w", padx=pad, pady=pad)

    def _browse_sqlite(self) -> None:
        path = filedialog.askopenfilename(title="Select SQLite db (sv.db)", filetypes=[("SQLite DB", "*.db;*.sqlite;*.sqlite3"), ("All files", "*.*")])
        if path:
            self.sqlite_path_var.set(path)

    def _browse_icon(self) -> None:
        path = filedialog.askopenfilename(title="Choose icon file", filetypes=[("Icon files", "*.ico;*.png;*.gif"), ("All files", "*.*")])
        if path:
            self.icon_path_var.set(path)

    def _apply_icon_from_var(self) -> None:
        path = self.icon_path_var.get().strip()
        if not path or not os.path.isfile(path):
            messagebox.showerror("Error", "Please choose a valid icon file (.ico or .png).")
            return
        try:
            self._apply_icon(path)
            self._log(f"Applied custom icon: {os.path.basename(path)}")
        except Exception as exc:
            messagebox.showerror("Error", f"Failed to apply icon: {exc}")

    def _apply_icon(self, path: str) -> None:
        ext = os.path.splitext(path)[1].lower()
        if ext == ".ico":
            self.root.iconbitmap(path)
            self._current_icon_img = None
        else:

            img = tk.PhotoImage(file=path)
            self.root.iconphoto(True, img)

            self._current_icon_img = img

    def _clear_icon(self) -> None:
        try:

            self.root.iconbitmap("")
            self._current_icon_img = None
            self._log("Cleared custom icon; using default.")
        except Exception as exc:
            self._log(f"Failed to clear icon: {exc}", error=True)

    def _apply_default_icon(self) -> None:

        base_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
        for candidate in ("app.ico", "app.png"):
            icon_path = os.path.join(base_dir, candidate)
            if os.path.isfile(icon_path):
                try:
                    self._apply_icon(icon_path)
                    break
                except Exception:
                    pass

    def _load_tables(self) -> None:
        path = self.sqlite_path_var.get().strip()
        if not path or not os.path.isfile(path):
            messagebox.showerror("Error", "Please select a valid SQLite file.")
            return
        try:
            with sqlite3.connect(path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY 1")
                names = [row[0] for row in cursor.fetchall()]
        except Exception as exc:
            messagebox.showerror("Error", f"Failed to read tables: {exc}")
            return

        self.tables_listbox.delete(0, tk.END)
        for n in names:
            self.tables_listbox.insert(tk.END, n)
        self._log(f"Loaded {len(names)} tables from {os.path.basename(path)}")

    def _select_all_tables(self) -> None:
        self.tables_listbox.select_set(0, tk.END)

    def _clear_tables_selection(self) -> None:
        self.tables_listbox.selection_clear(0, tk.END)

    def _start_migration(self) -> None:
        if self.is_migrating:
            return

        path = self.sqlite_path_var.get().strip()
        if not path or not os.path.isfile(path):
            messagebox.showerror("Error", "Please select a valid SQLite file and load tables.")
            return

        selection = [self.tables_listbox.get(i) for i in self.tables_listbox.curselection()]
        if not selection:

            selection = [self.tables_listbox.get(i) for i in range(self.tables_listbox.size())]
        if not selection:
            messagebox.showerror("Error", "No tables to migrate.")
            return

        try:
            port = int(self.mysql_port_var.get().strip())
        except ValueError:
            messagebox.showerror("Error", "MySQL port must be a number.")
            return

        mysql_cfg = MySQLConfig(
            host=self.mysql_host_var.get().strip() or "127.0.0.1",
            port=port,
            user=self.mysql_user_var.get().strip(),
            password=self.mysql_password_var.get(),
            database=self.mysql_database_var.get().strip(),
            create_database=self.create_db_var.get(),
        )

        if not mysql_cfg.user or not mysql_cfg.database:
            messagebox.showerror("Error", "MySQL user and database are required.")
            return

        self.is_migrating = True
        self.start_btn.configure(state=tk.DISABLED)
        self.progress_var.set(0)
        self.status_var.set("Migrating…")

        drop_recreate = self.drop_recreate_var.get()
        disable_fk = self.disable_fk_var.get()

        t = threading.Thread(target=self._migrate_thread, args=(path, selection, mysql_cfg, drop_recreate, disable_fk), daemon=True)
        t.start()

    def _migrate_thread(self, sqlite_path: str, tables: List[str], mysql_cfg: MySQLConfig, drop_recreate: bool, disable_fk: bool) -> None:
        try:
            with sqlite3.connect(sqlite_path) as sqlite_conn:
                sqlite_conn.row_factory = sqlite3.Row
                mysql_conn = self._connect_mysql(mysql_cfg)
                try:
                    if disable_fk:
                        self._execute_mysql(mysql_conn, "SET FOREIGN_KEY_CHECKS = 0")

                    if mysql_cfg.create_database:
                        self._execute_mysql(mysql_conn, f"CREATE DATABASE IF NOT EXISTS {self._qi(mysql_cfg.database)}")
                    self._execute_mysql(mysql_conn, f"USE {self._qi(mysql_cfg.database)}")

                    total_tables = len(tables)
                    for idx, table in enumerate(tables, start=1):
                        self._log(f"Processing table: {table}")
                        self._update_progress(0)

                        schema = self._read_sqlite_table_schema(sqlite_conn, table)
                        if schema is None:
                            self._log(f"Skipping {table}: unable to read schema", error=True)
                            continue

                        if drop_recreate:
                            self._execute_mysql(mysql_conn, f"DROP TABLE IF EXISTS {self._qi(table)}")

                        create_sql = self._build_mysql_create_table_sql(table, schema)
                        self._execute_mysql(mysql_conn, create_sql)

                        self._copy_table_data(sqlite_conn, mysql_conn, table, schema)

                        self._log(f"Finished table: {table} ({idx}/{total_tables})")

                    if disable_fk:
                        self._execute_mysql(mysql_conn, "SET FOREIGN_KEY_CHECKS = 1")

                    mysql_conn.commit()
                    self._log("Migration completed successfully.")
                finally:
                    try:
                        mysql_conn.close()
                    except Exception:
                        pass
        except mysql.connector.Error as err:
            self._log(f"MySQL error: {err}", error=True)
            if err.errno == errorcode.ER_ACCESS_DENIED_ERROR:
                self._log("Check your MySQL user/password.", error=True)
            elif err.errno == errorcode.ER_BAD_DB_ERROR:
                self._log("Database does not exist and could not be created.", error=True)
        except Exception as exc:
            self._log(f"Unexpected error: {exc}", error=True)
        finally:
            self.root.after(0, self._finish_migration_ui)

    def _finish_migration_ui(self) -> None:
        self.is_migrating = False
        self.start_btn.configure(state=tk.NORMAL)
        self.status_var.set("Idle")
        self.progress_var.set(100)

    def _connect_mysql(self, cfg: MySQLConfig) -> mysql.connector.connection.MySQLConnection:
        self._log(f"Connecting to MySQL at {cfg.host}:{cfg.port}…")
        conn = mysql.connector.connect(
            host=cfg.host,
            port=cfg.port,
            user=cfg.user,
            password=cfg.password,
            autocommit=False,
        )
        return conn

    def _execute_mysql(self, conn: mysql.connector.connection.MySQLConnection, sql: str, params: Optional[Sequence] = None) -> None:
        self._log(f"MySQL: {sql}")
        cur = conn.cursor()
        try:
            cur.execute(sql, params or ())
            conn.commit()
        finally:
            cur.close()

    def _read_sqlite_table_schema(self, sqlite_conn: sqlite3.Connection, table: str) -> Optional[Dict]:
        try:
            cur = sqlite_conn.cursor()
            cur.execute(f"PRAGMA table_info({self._qi_sqlite(table)})")
            cols = cur.fetchall()
            if not cols:
                return None
            columns: List[Dict] = []
            primary_keys: List[str] = []
            for cid, name, col_type, notnull, dflt_value, pk in cols:
                columns.append({
                    "name": name,
                    "type": col_type or "TEXT",
                    "notnull": bool(notnull),
                    "default": dflt_value,
                    "pk": bool(pk),
                })
                if pk:
                    primary_keys.append(name)
            return {
                "columns": columns,
                "primary_keys": primary_keys,
            }
        except Exception:
            return None

    def _build_mysql_create_table_sql(self, table: str, schema: Dict) -> str:
        col_defs: List[str] = []
        for col in schema["columns"]:
            mysql_type = self._map_sqlite_type_to_mysql(col["type"])
            parts = [self._qi(col["name"]) + " " + mysql_type]
            if col["notnull"]:
                parts.append("NOT NULL")
            if col["default"] is not None:
                default_sql = self._normalize_default(col["default"])
                if default_sql is not None:
                    parts.append(f"DEFAULT {default_sql}")
            col_defs.append(" ".join(parts))

        pk = schema.get("primary_keys") or []
        if pk:
            col_defs.append("PRIMARY KEY (" + ", ".join(self._qi(c) for c in pk) + ")")

        create_sql = f"CREATE TABLE IF NOT EXISTS {self._qi(table)} (\n  " + ",\n  ".join(col_defs) + "\n) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
        return create_sql

    def _normalize_default(self, default_val: str) -> Optional[str]:

        val = default_val.strip()
        if val.upper() in ("NULL", "CURRENT_TIMESTAMP"):
            return val.upper()
        if re.fullmatch(r"[-+]?\d+", val) or re.fullmatch(r"[-+]?\d*\.\d+", val):
            return val

        if (val.startswith("'") and val.endswith("'")) or (val.startswith('"') and val.endswith('"')):
            val = val[1:-1]
        val = val.replace("'", "''")
        return f"'{val}'"

    def _map_sqlite_type_to_mysql(self, sqlite_type: str) -> str:
        t = sqlite_type.strip().upper()

        m = re.match(r"([A-Z]+)\s*\(([^)]+)\)", t)
        base = t
        length = None
        if m:
            base = m.group(1)
            length = m.group(2)

        if "INT" in base:
            return "INT"
        if any(x in base for x in ["CHAR", "CLOB", "TEXT", "VARCHAR"]):
            if length:
                try:
                    n = int(length.split(",")[0].strip())
                    n = max(1, min(n, 65535))
                    return f"VARCHAR({n})"
                except Exception:
                    return "TEXT"
            return "TEXT"
        if "BLOB" in base:
            return "LONGBLOB"
        if any(x in base for x in ["REAL", "FLOA", "DOUB"]):
            return "DOUBLE"
        if any(x in base for x in ["NUMERIC", "DECIMAL"]):
            return "DECIMAL(38,10)"
        if "BOOL" in base:
            return "TINYINT(1)"
        if base in ("DATE",):
            return "DATE"
        if base in ("DATETIME", "TIMESTAMP"):
            return "DATETIME"
        if base in ("TIME",):
            return "TIME"
        return "TEXT"

    def _copy_table_data(self, sqlite_conn: sqlite3.Connection, mysql_conn: mysql.connector.connection.MySQLConnection, table: str, schema: Dict) -> None:

        cur_sqlite = sqlite_conn.cursor()
        cur_sqlite.execute(f"SELECT COUNT(*) FROM {self._qi_sqlite(table)}")
        total_rows = cur_sqlite.fetchone()[0]
        self._log(f"Rows to migrate: {total_rows}")

        columns = [c["name"] for c in schema["columns"]]
        cols_sql = ", ".join(self._qi(c) for c in columns)
        placeholders = ", ".join(["%s"] * len(columns))
        insert_sql = f"INSERT INTO {self._qi(table)} ({cols_sql}) VALUES ({placeholders})"

        cur_sqlite.execute(f"SELECT {', '.join(self._qi_sqlite(c) for c in columns)} FROM {self._qi_sqlite(table)}")

        cur_mysql = mysql_conn.cursor()
        try:
            rows_done = 0
            while True:
                rows = cur_sqlite.fetchmany(BATCH_SIZE)
                if not rows:
                    break
                data = [tuple(row[c] for c in columns) for row in rows]
                cur_mysql.executemany(insert_sql, data)
                mysql_conn.commit()
                rows_done += len(data)
                progress_pct = (rows_done / max(1, total_rows)) * 100.0
                self._update_progress(progress_pct)
            self._update_progress(100.0)
        finally:
            cur_mysql.close()

    def _qi(self, ident: str) -> str:
        return "`" + ident.replace("`", "``") + "`"

    def _qi_sqlite(self, ident: str) -> str:

        return '"' + ident.replace('"', '""') + '"'

    def _log(self, message: str, error: bool = False) -> None:
        prefix = "ERROR: " if error else ""
        self.log_queue.put(prefix + message)

    def _drain_log_queue(self) -> None:
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.log_text.insert(tk.END, msg + "\n")
                self.log_text.see(tk.END)
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self._drain_log_queue)

    def _update_progress(self, pct: float) -> None:
        self.root.after(0, lambda: self.progress_var.set(max(0.0, min(100.0, pct))))

def main() -> None:
    root = tk.Tk()
    app = MigratorApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()