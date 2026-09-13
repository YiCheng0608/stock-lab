"""Repair the historical NewsItem JSON server-default drift.

Revision 0004 created the two relation columns with a SQLite server default,
but the declarative model did not.  Fresh databases made directly from the
model therefore rejected raw inserts that omitted either column.  SQLite has
no supported ``ALTER COLUMN SET DEFAULT`` operation, so an existing table
needs a careful, atomic rebuild when either default is absent.

The rebuild deliberately uses the table's own checked-in SQLite DDL as its
source.  That preserves extra columns and table-level constraints instead of
silently replacing a user's schema with the current ORM metadata.  Explicit
indexes and triggers are captured and recreated as well.  A table referenced
by another table is rejected before any DDL because replacing it would need a
larger graph-wide migration that this repair cannot safely provide.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from sqlalchemy import inspect, text


_TARGET_COLUMNS = ("symbols_json", "theme_ids_json")
_REBUILD_SUFFIX = "__news_json_defaults_rebuild"
_DEFAULT_LITERAL = "'[]'"


def _normalize_default(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    while normalized.startswith("(") and normalized.endswith(")"):
        normalized = normalized[1:-1].strip()
    if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in "'\"":
        normalized = normalized[1:-1]
    return normalized.replace("''", "'")


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _find_matching_parenthesis(sql: str, opening: int) -> int:
    depth = 0
    quote: str | None = None
    index = opening
    while index < len(sql):
        character = sql[index]
        if quote is not None:
            if character == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    index += 2
                    continue
                quote = None
        elif character in "'\"`[":
            quote = "]" if character == "[" else character
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    raise RuntimeError("cannot repair news_items: malformed CREATE TABLE SQL")


def _split_table_definitions(body: str) -> list[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    quote: str | None = None
    index = 0
    while index < len(body):
        character = body[index]
        if quote is not None:
            if character == quote:
                if index + 1 < len(body) and body[index + 1] == quote:
                    index += 2
                    continue
                quote = None
        elif character in "'\"`[":
            quote = "]" if character == "[" else character
        elif character == "(":
            depth += 1
        elif character == ")":
            if depth == 0:
                raise RuntimeError("cannot repair news_items: malformed table definition")
            depth -= 1
        elif character == "," and depth == 0:
            parts.append(body[start:index])
            start = index + 1
        index += 1
    if quote is not None or depth != 0:
        raise RuntimeError("cannot repair news_items: malformed table definition")
    parts.append(body[start:])
    return parts


def _unquote_identifier(token: str) -> str:
    token = token.strip()
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"`":
        return token[1:-1].replace(token[0] * 2, token[0])
    if token.startswith("[") and token.endswith("]"):
        return token[1:-1]
    return token


def _definition_name(definition: str) -> str | None:
    match = re.match(
        r"\s*(\"(?:\"\"|[^\"])+\"|`(?:``|[^`])+`|\[[^]]+\]|[A-Za-z_][A-Za-z0-9_$]*)",
        definition,
    )
    return _unquote_identifier(match.group(1)) if match else None


def _replace_table_name(sql: str, old_name: str, new_name: str) -> str:
    match = re.match(
        r"(?is)(\s*CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?)(\"(?:\"\"|[^\"])+\"|`(?:``|[^`])+`|\[[^]]+\]|[A-Za-z_][A-Za-z0-9_$]*)(\s*\()",
        sql,
    )
    if not match or _unquote_identifier(match.group(2)) != old_name:
        raise RuntimeError("cannot repair news_items: unsupported CREATE TABLE SQL")
    return (
        f"{match.group(1)}{_quote_identifier(new_name)}{match.group(3)}"
        + sql[match.end(3) :]
    )


def _replace_self_references(sql: str, temporary_name: str) -> str:
    result: list[str] = []
    index = 0
    while index < len(sql):
        if sql.startswith("--", index):
            end = sql.find("\n", index)
            end = len(sql) if end < 0 else end
            result.append(sql[index:end])
            index = end
            continue
        if sql.startswith("/*", index):
            end = sql.find("*/", index + 2)
            if end < 0:
                raise RuntimeError("cannot repair news_items: malformed SQL comment")
            end += 2
            result.append(sql[index:end])
            index = end
            continue
        if sql[index] in "'\"`[":
            quote = "]" if sql[index] == "[" else sql[index]
            start = index
            index += 1
            while index < len(sql):
                if sql[index] == quote:
                    if index + 1 < len(sql) and sql[index + 1] == quote:
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            else:
                raise RuntimeError("cannot repair news_items: malformed quoted SQL")
            result.append(sql[start:index])
            continue
        if sql[index : index + 10].upper() == "REFERENCES":
            before = sql[index - 1] if index else " "
            after = sql[index + 10] if index + 10 < len(sql) else " "
            if not (before.isalnum() or before in "_$") and not (
                after.isalnum() or after in "_$"
            ):
                start = index
                index += 10
                while index < len(sql) and sql[index].isspace():
                    index += 1
                identifier_start = index
                if index < len(sql) and sql[index] in "\"`[":
                    quote = "]" if sql[index] == "[" else sql[index]
                    index += 1
                    while index < len(sql) and sql[index] != quote:
                        if index + 1 < len(sql) and sql[index] == quote and sql[index + 1] == quote:
                            index += 2
                        else:
                            index += 1
                    if index >= len(sql):
                        raise RuntimeError("cannot repair news_items: malformed FK identifier")
                    index += 1
                else:
                    while index < len(sql) and (sql[index].isalnum() or sql[index] in "_$."):
                        index += 1
                identifier = _unquote_identifier(sql[identifier_start:index])
                if identifier == "news_items":
                    result.append(sql[start:identifier_start])
                    result.append(_quote_identifier(temporary_name))
                    continue
                result.append(sql[start:index])
                continue
        result.append(sql[index])
        index += 1
    return "".join(result)


def _patched_create_table_sql(table_sql: str, temporary_name: str) -> str:
    open_paren = table_sql.find("(")
    if open_paren < 0:
        raise RuntimeError("cannot repair news_items: missing CREATE TABLE body")
    close_paren = _find_matching_parenthesis(table_sql, open_paren)
    body = table_sql[open_paren + 1 : close_paren]
    definitions = _split_table_definitions(body)
    patched: list[str] = []
    found: set[str] = set()
    for definition in definitions:
        name = _definition_name(definition)
        if name in _TARGET_COLUMNS:
            found.add(name)
            if re.search(r"\bDEFAULT\b", definition, flags=re.IGNORECASE):
                patched.append(definition)
            else:
                patched.append(f"{definition} DEFAULT {_DEFAULT_LITERAL}")
        else:
            patched.append(definition)
    if found != set(_TARGET_COLUMNS):
        missing = sorted(set(_TARGET_COLUMNS) - found)
        raise RuntimeError(
            "cannot repair news_items: target column definition(s) missing "
            f"from SQLite DDL: {missing}"
        )
    rebuilt_body = ",".join(patched)
    rebuilt_sql = table_sql[: open_paren + 1] + rebuilt_body + table_sql[close_paren:]
    return _replace_table_name(rebuilt_sql, "news_items", temporary_name)


def _sqlite_master_sql(connection, object_type: str, *, table_name: str) -> list[tuple[str, str]]:
    rows = connection.execute(
        text(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type = :object_type AND tbl_name = :table_name "
            "AND sql IS NOT NULL ORDER BY name"
        ),
        {"object_type": object_type, "table_name": table_name},
    ).all()
    return [(str(name), str(sql)) for name, sql in rows]


def _assert_no_dependent_views(connection, table_name: str) -> None:
    rows = connection.execute(
        text("SELECT name, sql FROM sqlite_master WHERE type = 'view' AND sql IS NOT NULL")
    ).all()
    for name, sql in rows:
        if re.search(
            rf"(?i)(?:\"{re.escape(table_name)}\"|`{re.escape(table_name)}`|\[{re.escape(table_name)}\]|\b{re.escape(table_name)}\b)",
            sql,
        ):
            raise RuntimeError(
                "cannot repair news_items: dependent view cannot be "
                f"safely rebound: {name}"
            )


def _assert_no_external_trigger_dependencies(connection, table_name: str) -> None:
    rows = connection.execute(
        text(
            "SELECT name, tbl_name, sql FROM sqlite_master "
            "WHERE type = 'trigger' AND sql IS NOT NULL"
        )
    ).all()
    for name, trigger_table, sql in rows:
        if trigger_table == table_name:
            continue
        if re.search(
            rf"(?i)(?:\"{re.escape(table_name)}\"|`{re.escape(table_name)}`|\[{re.escape(table_name)}\]|\b{re.escape(table_name)}\b)",
            sql,
        ):
            raise RuntimeError(
                "cannot repair news_items: external trigger depends on "
                f"news_items: {name}"
            )


def _foreign_key_check(connection) -> list[Any]:
    return list(connection.exec_driver_sql("PRAGMA foreign_key_check").all())


def _assert_no_inbound_foreign_keys(connection, table_name: str) -> None:
    inspector = inspect(connection)
    for candidate in inspector.get_table_names():
        if candidate == table_name or candidate.startswith("sqlite_"):
            continue
        pragma_name = _quote_identifier(candidate)
        for foreign_key in connection.exec_driver_sql(
            f"PRAGMA foreign_key_list({pragma_name})"
        ).all():
            if foreign_key[2] == table_name:
                raise RuntimeError(
                    "cannot repair news_items: table is referenced by "
                    f"foreign key from {candidate}.{foreign_key[3]}"
                )


def _assert_copyable_columns(connection, table_name: str, columns: list[dict[str, Any]]) -> None:
    # PRAGMA table_xinfo marks generated/hidden columns.  They cannot be part
    # of the explicit INSERT column list used for byte-preserving copying.
    rows = connection.exec_driver_sql(
        f"PRAGMA table_xinfo({_quote_identifier(table_name)})"
    ).all()
    hidden_by_name = {str(row[1]): int(row[6] or 0) for row in rows if len(row) > 6}
    unsupported = [column["name"] for column in columns if hidden_by_name.get(column["name"], 0)]
    if unsupported:
        raise RuntimeError(
            "cannot repair news_items: generated or hidden column(s) cannot "
            f"be copied safely: {unsupported}"
        )


def _inject_failure(failure_injector: Callable[[str], None] | None, phase: str) -> None:
    if failure_injector is not None:
        failure_injector(phase)


def _repair_sqlite_news_defaults(
    connection,
    *,
    failure_injector: Callable[[str], None] | None = None,
) -> None:
    inspector = inspect(connection)
    columns = inspector.get_columns("news_items")
    _assert_copyable_columns(connection, "news_items", columns)
    _assert_no_inbound_foreign_keys(connection, "news_items")
    _assert_no_dependent_views(connection, "news_items")
    _assert_no_external_trigger_dependencies(connection, "news_items")
    violations = _foreign_key_check(connection)
    if violations:
        raise RuntimeError(
            "cannot repair news_items: existing foreign-key violation(s) "
            f"detected before rebuild: {violations[:3]!r}"
        )

    table_sql = connection.execute(
        text("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'news_items'")
    ).scalar_one_or_none()
    if not table_sql:
        raise RuntimeError("cannot repair news_items: SQLite table DDL is unavailable")
    if re.search(r"\bAUTOINCREMENT\b", str(table_sql), flags=re.IGNORECASE):
        raise RuntimeError(
            "cannot repair news_items: AUTOINCREMENT requires explicit "
            "sqlite_sequence preservation and is fail-closed"
        )

    indexes = _sqlite_master_sql(connection, "index", table_name="news_items")
    triggers = _sqlite_master_sql(connection, "trigger", table_name="news_items")
    temporary_name = f"news_items{_REBUILD_SUFFIX}"
    old_name = f"news_items{_REBUILD_SUFFIX}_old"
    if set(inspector.get_table_names()) & {temporary_name, old_name}:
        raise RuntimeError(
            "cannot repair news_items: rebuild scratch table already exists; "
            "refusing to overwrite it"
        )

    quoted_table = _quote_identifier("news_items")
    quoted_temporary = _quote_identifier(temporary_name)
    quoted_old = _quote_identifier(old_name)
    column_names = [str(column["name"]) for column in columns]
    columns_sql = ", ".join(_quote_identifier(column) for column in column_names)
    savepoint = "news_json_defaults_repair"
    connection.exec_driver_sql(f"SAVEPOINT {_quote_identifier(savepoint)}")
    try:
        _inject_failure(failure_injector, "before_create")
        # Move the original away first.  This makes the temporary table's
        # self-FK point at itself, so SQLite can keep foreign_keys=ON while
        # the old table is dropped; creating the temporary table while the
        # old name still exists would make DROP TABLE fail on that FK.
        connection.exec_driver_sql(
            f"ALTER TABLE {quoted_table} RENAME TO {quoted_old}"
        )
        patched_sql = _patched_create_table_sql(str(table_sql), temporary_name)
        patched_sql = _replace_self_references(patched_sql, temporary_name)
        connection.exec_driver_sql(patched_sql)
        _inject_failure(failure_injector, "after_create")

        connection.exec_driver_sql(
            f"INSERT INTO {quoted_temporary} ({columns_sql}) "
            f"SELECT {columns_sql} FROM {quoted_old}"
        )
        _inject_failure(failure_injector, "after_copy")

        connection.exec_driver_sql(f"DROP TABLE {quoted_old}")
        _inject_failure(failure_injector, "after_drop")
        connection.exec_driver_sql(
            f"ALTER TABLE {quoted_temporary} RENAME TO {quoted_table}"
        )
        _inject_failure(failure_injector, "after_rename")

        for _name, sql in indexes:
            connection.exec_driver_sql(sql)
        for _name, sql in triggers:
            connection.exec_driver_sql(sql)
        _inject_failure(failure_injector, "after_objects")

        repaired_columns = {
            column["name"]: _normalize_default(column.get("default"))
            for column in inspect(connection).get_columns("news_items")
        }
        default_mismatches = {
            name: repaired_columns.get(name)
            for name in _TARGET_COLUMNS
            if repaired_columns.get(name) != "[]"
        }
        if default_mismatches:
            raise RuntimeError(
                "cannot repair news_items: post-rebuild server-default "
                f"contract mismatch: {default_mismatches}"
            )

        if connection.exec_driver_sql("PRAGMA integrity_check").scalar() != "ok":
            raise RuntimeError("cannot repair news_items: SQLite integrity_check failed")
        remaining_violations = _foreign_key_check(connection)
        if remaining_violations:
            raise RuntimeError(
                "cannot repair news_items: foreign-key violation(s) after "
                f"rebuild: {remaining_violations[:3]!r}"
            )
        _inject_failure(failure_injector, "before_release")
        connection.exec_driver_sql(f"RELEASE SAVEPOINT {_quote_identifier(savepoint)}")
    except BaseException:
        try:
            connection.exec_driver_sql(
                f"ROLLBACK TO SAVEPOINT {_quote_identifier(savepoint)}"
            )
        finally:
            connection.exec_driver_sql(f"RELEASE SAVEPOINT {_quote_identifier(savepoint)}")
        raise


def ensure_news_json_server_defaults(
    connection,
    *,
    failure_injector: Callable[[str], None] | None = None,
) -> bool:
    """Ensure both NewsItem JSON columns have a SQL server default of ``[]``.

    Returns ``True`` when a table rebuild or ALTER operation was required.
    The helper never changes SQLite's ``foreign_keys`` pragma and its repair
    work is protected by a savepoint, so callers can compose it with either
    Alembic's transaction or the compatibility fallback transaction.
    """

    inspector = inspect(connection)
    if not inspector.has_table("news_items"):
        return False
    columns = {column["name"]: column for column in inspector.get_columns("news_items")}
    missing = [name for name in _TARGET_COLUMNS if name not in columns]
    if missing:
        raise RuntimeError(
            "cannot repair news_items: target column(s) missing: "
            f"{missing}"
        )
    unexpected_defaults = {
        name: _normalize_default(columns[name].get("default"))
        for name in _TARGET_COLUMNS
        if columns[name].get("default") is not None
        and _normalize_default(columns[name].get("default")) != "[]"
    }
    if unexpected_defaults:
        raise RuntimeError(
            "cannot repair news_items: refusing to replace non-empty "
            f"server default(s): {unexpected_defaults}"
        )
    needs_repair = [
        name for name in _TARGET_COLUMNS if columns[name].get("default") is None
    ]
    if not needs_repair:
        return False

    if connection.dialect.name != "sqlite":
        for name in needs_repair:
            connection.exec_driver_sql(
                f'ALTER TABLE "news_items" ALTER COLUMN "{name}" SET DEFAULT \'[]\''
            )
        return True

    _repair_sqlite_news_defaults(connection, failure_injector=failure_injector)
    return True


__all__ = ["ensure_news_json_server_defaults"]
