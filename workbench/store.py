"""`.workbench/` — the rebuildable projection store.  Delete it and lose nothing.

Two shapes of the same rows, because two very different readers need them:

  `index.sqlite`   full-text + filterable, for `research search`
  `*.jsonl`        flat line-per-row, for an agent that wants the whole view in one read

Invariants this module is responsible for:

* **Rebuildable.** `rebuild()` drops every table and rewrites every file.  No row here is
  authored — all of it comes from the machine and the vault, so a corrupt or stale store is
  fixed by rebuilding, never by hand-editing.
* **Contained.** Nothing is written outside the resolved `.workbench/` root.
* **Degrades, never crashes.** A SQLite built without FTS5 falls back to a plain table
  searched with `LIKE`; `search()` reports which engine answered so a caller can say so.

The store is a cache, so it is gitignored.  It is deliberately placed under the machine
package (not the workspace root) so it inherits the machine's `.gitignore` and matches how
every other tool here resolves paths off the package root.  `RAT_WORKBENCH_ROOT` overrides.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Optional

from .model import ArtifactRow, ProjectRow, TaskRow

SCHEMA_VERSION = 1
_PKG_ROOT = Path(__file__).resolve().parent.parent          # research_agent_teams/
_DIR_NAME = ".workbench"

_JSONL_VIEWS = ("projects", "artifacts", "tasks", "capabilities")


def workbench_root(root: Optional[str] = None) -> Path:
    """Where the projection lives.  Explicit arg > env override > under the machine package."""
    if root:
        return Path(root)
    env = os.environ.get("RAT_WORKBENCH_ROOT")
    if env:
        return Path(env)
    return _PKG_ROOT / _DIR_NAME


# CJK has no word delimiters, and FTS5's default `unicode61` tokenizer cannot segment it —
# a Chinese query would only ever match a whole identical run. Substring search is genuinely
# better there, so a CJK query is routed to LIKE and the answer says which engine ran.
_CJK = re.compile(r"[㐀-鿿぀-ヿ가-힯]")
# Either an explicitly quoted phrase, or a run of word characters.
_TERM = re.compile(r'"[^"]+"|[^\W_]+', re.UNICODE)


def fts_expression(query: str) -> str:
    """Quote every term so ordinary prose never trips FTS5 operator syntax.

    A director types `state-relative intent`, not query syntax; unquoted, FTS5 reads the
    hyphen as NOT and errors with `no such column: relative`. Quoting each term turns it into
    an implicit AND over the words, which is what a search box is expected to do. An
    explicitly quoted phrase the caller typed is passed through untouched.
    """
    terms = _TERM.findall(query)
    return " ".join(term if term.startswith('"') else f'"{term}"' for term in terms)


def _fts5_available(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("CREATE VIRTUAL TABLE _fts5_probe USING fts5(x)")
        conn.execute("DROP TABLE _fts5_probe")
        return True
    except sqlite3.OperationalError:
        return False


class WorkbenchStore:
    """Owns `.workbench/`.  Open it, rebuild it, query it.  It never writes elsewhere."""

    def __init__(self, root: Optional[str] = None) -> None:
        self.root = workbench_root(root)
        self.db_path = self.root / "index.sqlite"
        self._conn: Optional[sqlite3.Connection] = None
        self._fts = False

    # ------------------------------------------------------------------ lifecycle

    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self.root.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._fts = _fts5_available(self._conn)
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "WorkbenchStore":
        self.connect()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @property
    def search_engine(self) -> str:
        """Which engine will answer `search()` — callers surface this, never hide it."""
        self.connect()
        return "fts5" if self._fts else "like"

    # ------------------------------------------------------------------ schema

    def _create_schema(self) -> None:
        conn = self.connect()
        conn.executescript(
            """
            DROP TABLE IF EXISTS artifacts;
            DROP TABLE IF EXISTS artifacts_fts;
            DROP TABLE IF EXISTS tasks;
            DROP TABLE IF EXISTS projects;
            DROP TABLE IF EXISTS meta;

            CREATE TABLE artifacts (
                artifact_id     TEXT PRIMARY KEY,
                project         TEXT NOT NULL,
                kind            TEXT NOT NULL,
                title           TEXT NOT NULL,
                path            TEXT NOT NULL,
                source          TEXT NOT NULL,
                updated         TEXT,
                run_id          TEXT,
                evidence_state  TEXT,
                evidence_reason TEXT,
                lifecycle       TEXT
            );
            CREATE INDEX idx_artifacts_project ON artifacts(project);
            CREATE INDEX idx_artifacts_source  ON artifacts(source);

            CREATE TABLE tasks (
                task_id         TEXT PRIMARY KEY,
                project         TEXT NOT NULL,
                title           TEXT NOT NULL,
                priority        TEXT,
                work_state      TEXT NOT NULL,
                evidence_state  TEXT NOT NULL,
                evidence_reason TEXT,
                why_now         TEXT,
                next_action     TEXT,
                blockers        TEXT,
                source_path     TEXT,
                source_status   TEXT
            );
            CREATE INDEX idx_tasks_project ON tasks(project);

            CREATE TABLE projects (
                slug     TEXT PRIMARY KEY,
                payload  TEXT NOT NULL
            );

            CREATE TABLE meta (
                key   TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )
        if self._fts:
            conn.execute(
                "CREATE VIRTUAL TABLE artifacts_fts USING fts5("
                "artifact_id UNINDEXED, project, kind, title, path, body)"
            )
        else:
            # Same columns, plain table; `search()` degrades to LIKE over them.
            conn.execute(
                "CREATE TABLE artifacts_fts ("
                "artifact_id TEXT, project TEXT, kind TEXT, title TEXT, path TEXT, body TEXT)"
            )
        conn.commit()

    # ------------------------------------------------------------------ write

    def rebuild(
        self,
        *,
        projects: Iterable[ProjectRow] = (),
        artifacts: Iterable[ArtifactRow] = (),
        tasks: Iterable[TaskRow] = (),
        capabilities: Iterable[dict[str, Any]] = (),
        built_at: str = "",
        sources: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        """Wipe and rewrite the whole projection.  This is the only supported write path."""
        projects = list(projects)
        artifacts = list(artifacts)
        tasks = list(tasks)
        capabilities = list(capabilities)

        self._create_schema()
        conn = self.connect()
        conn.executemany(
            "INSERT INTO artifacts (artifact_id, project, kind, title, path, source, updated,"
            " run_id, evidence_state, evidence_reason, lifecycle)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [
                (a.artifact_id, a.project, a.kind, a.title, a.path, a.source, a.updated,
                 a.run_id, a.evidence_state, a.evidence_reason, a.lifecycle)
                for a in artifacts
            ],
        )
        conn.executemany(
            "INSERT INTO artifacts_fts (artifact_id, project, kind, title, path, body)"
            " VALUES (?,?,?,?,?,?)",
            [(a.artifact_id, a.project, a.kind, a.title, a.path, a.text) for a in artifacts],
        )
        conn.executemany(
            "INSERT INTO tasks (task_id, project, title, priority, work_state, evidence_state,"
            " evidence_reason, why_now, next_action, blockers, source_path, source_status)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (t.task_id, t.project, t.title, t.priority, t.work_state, t.evidence_state,
                 t.evidence_reason, t.why_now, t.next_action,
                 json.dumps(list(t.blockers), ensure_ascii=False), t.source_path, t.source_status)
                for t in tasks
            ],
        )
        conn.executemany(
            "INSERT INTO projects (slug, payload) VALUES (?,?)",
            [(p.slug, json.dumps(p.as_dict(), ensure_ascii=False)) for p in projects],
        )
        meta = {
            "schema_version": str(SCHEMA_VERSION),
            "built_at": built_at,
            "search_engine": self.search_engine,
            "counts": json.dumps(
                {"projects": len(projects), "artifacts": len(artifacts),
                 "tasks": len(tasks), "capabilities": len(capabilities)},
                ensure_ascii=False,
            ),
            "sources": json.dumps(sources or {}, ensure_ascii=False),
            "note": "投影层，可随时删除重建；不是任何事实的来源",
        }
        conn.executemany("INSERT INTO meta (key, value) VALUES (?,?)", list(meta.items()))
        conn.commit()

        self._write_jsonl("projects", [p.as_dict() for p in projects])
        self._write_jsonl("artifacts", [a.as_dict() for a in artifacts])
        self._write_jsonl("tasks", [t.as_dict() for t in tasks])
        self._write_jsonl("capabilities", capabilities)
        (self.root / "meta.json").write_text(
            json.dumps({**meta, "counts": json.loads(meta["counts"]),
                        "sources": json.loads(meta["sources"])},
                       ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return self.meta()

    def _write_jsonl(self, name: str, rows: Iterable[dict[str, Any]]) -> None:
        path = self.root / f"{name}.jsonl"
        with path.open("w", encoding="utf-8", newline="\n") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------ read

    def exists(self) -> bool:
        return self.db_path.is_file()

    def meta(self) -> dict[str, Any]:
        if not self.exists():
            return {"available": False, "note": "还没建索引，跑一次 reindex 就有了"}
        conn = self.connect()
        try:
            rows = conn.execute("SELECT key, value FROM meta").fetchall()
        except sqlite3.OperationalError:
            return {"available": False, "note": "索引不完整，重建一次即可"}
        out: dict[str, Any] = {"available": True}
        for row in rows:
            out[row["key"]] = row["value"]
        for key in ("counts", "sources"):
            if isinstance(out.get(key), str):
                try:
                    out[key] = json.loads(out[key])
                except json.JSONDecodeError:
                    pass
        return out

    def projects(self) -> list[dict[str, Any]]:
        if not self.exists():
            return []
        conn = self.connect()
        try:
            rows = conn.execute("SELECT payload FROM projects ORDER BY slug").fetchall()
        except sqlite3.OperationalError:
            return []
        return [json.loads(row["payload"]) for row in rows]

    def tasks(self, project: Optional[str] = None) -> list[dict[str, Any]]:
        if not self.exists():
            return []
        conn = self.connect()
        sql = "SELECT * FROM tasks"
        args: tuple[Any, ...] = ()
        if project:
            sql += " WHERE project = ?"
            args = (project,)
        sql += " ORDER BY priority, task_id"
        try:
            rows = conn.execute(sql, args).fetchall()
        except sqlite3.OperationalError:
            return []
        out = []
        for row in rows:
            item = dict(row)
            try:
                item["blockers"] = json.loads(item.get("blockers") or "[]")
            except json.JSONDecodeError:
                item["blockers"] = []
            out.append(item)
        return out

    def artifact(self, artifact_id: str) -> Optional[dict[str, Any]]:
        if not self.exists():
            return None
        conn = self.connect()
        try:
            row = conn.execute(
                "SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,)
            ).fetchone()
        except sqlite3.OperationalError:
            return None
        return dict(row) if row else None

    def search(
        self,
        query: str,
        *,
        project: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 20,
        raw: bool = False,
    ) -> dict[str, Any]:
        """Full-text over titles + bodies.  Reports the engine that actually answered.

        `raw=True` passes the query to FTS5 verbatim for a caller who wants its operators;
        by default the query is treated as prose.
        """
        query = (query or "").strip()
        if not query or not self.exists():
            return {"engine": self.search_engine if self.exists() else "none",
                    "query": query, "hits": []}
        conn = self.connect()
        # Route per query, not per store: CJK goes to substring search even when FTS5 exists.
        engine = "fts5" if (self.search_engine == "fts5" and not _CJK.search(query)) else "like"
        if engine == "fts5":
            expression = query if raw else fts_expression(query)
            if not expression:
                return {"engine": engine, "query": query, "hits": []}
            sql = (
                "SELECT f.artifact_id, a.project, a.kind, a.title, a.path, a.source,"
                " a.updated, a.evidence_state, a.evidence_reason,"
                " snippet(artifacts_fts, 5, '«', '»', '…', 12) AS excerpt"
                " FROM artifacts_fts f JOIN artifacts a ON a.artifact_id = f.artifact_id"
                " WHERE artifacts_fts MATCH ?"
            )
            args: list[Any] = [expression]
        else:
            sql = (
                "SELECT f.artifact_id, a.project, a.kind, a.title, a.path, a.source,"
                " a.updated, a.evidence_state, a.evidence_reason,"
                " substr(f.body, 1, 200) AS excerpt"
                " FROM artifacts_fts f JOIN artifacts a ON a.artifact_id = f.artifact_id"
                " WHERE (f.title LIKE ? OR f.body LIKE ?)"
            )
            like = f"%{query}%"
            args = [like, like]
        if project:
            sql += " AND a.project = ?"
            args.append(project)
        if source:
            sql += " AND a.source = ?"
            args.append(source)
        sql += " LIMIT ?"
        args.append(int(limit))
        try:
            rows = conn.execute(sql, tuple(args)).fetchall()
        except sqlite3.OperationalError as exc:
            # A malformed FTS expression is a user error, not a crash.
            return {"engine": engine, "query": query, "hits": [],
                    "note": f"查询写法 SQLite 不认: {exc}"}
        return {"engine": engine, "query": query, "hits": [dict(r) for r in rows]}


def destroy(root: Optional[str] = None) -> dict[str, Any]:
    """Delete the projection.  Safe by construction — it holds no source of truth."""
    target = workbench_root(root)
    removed = []
    for name in (*(f"{v}.jsonl" for v in _JSONL_VIEWS), "index.sqlite", "meta.json"):
        path = target / name
        if path.is_file():
            path.unlink()
            removed.append(name)
    return {"root": str(target), "removed": removed}


__all__ = ["SCHEMA_VERSION", "WorkbenchStore", "destroy", "fts_expression", "workbench_root"]
