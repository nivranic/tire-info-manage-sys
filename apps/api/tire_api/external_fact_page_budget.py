"""Explicit, cumulative allocation/work bounds for one owned SQLite page.

All payload queries declare their model, predicates and selected columns. Length
queries run before SQLAlchemy JSON processors. This is not an OS memory sandbox.
"""
import math

from sqlalchemy import JSON, LargeBinary, String, Text, cast, func, literal, select


class PageCapacityError(Exception):
    """Kept outside ValueError so trusted legacy validators cannot swallow it."""


class PageReadBudget:
    MAX_ROWS = 8192
    MAX_STORAGE_BYTES = 16 * 1024 * 1024
    MAX_JSON_NODES = 262144
    MAX_JSON_DEPTH = 16
    MAX_HISTORY = 4096
    MAX_VALUES = 4096
    MAX_FINAL = 256
    MAX_ITEM_BYTES = 8 * 1024 * 1024
    MAX_ITEM_NODES = 65536

    def __init__(self):
        self.actual_rows = self.charged_rows = self.storage_bytes = 0
        self.json_nodes = self.value_calls = self.final_calls = 0
        self.item_bytes = self.item_nodes = 0
        self._history = set()

    @staticmethod
    def _check(value, maximum):
        if value > maximum:
            raise PageCapacityError('page_capacity')

    def reserve_rows(self, count):
        self.charged_rows += count
        self._check(self.charged_rows, self.MAX_ROWS)

    def storage(self, count):
        self.storage_bytes += count
        self._check(self.storage_bytes, self.MAX_STORAGE_BYTES)

    def json(self, value, *, maximum_depth=None, maximum_nodes=None):
        """Bound values before hashing/canonicalizing; no recursive traversal."""
        depth_limit = self.MAX_JSON_DEPTH if maximum_depth is None else maximum_depth
        node_limit = self.MAX_JSON_NODES if maximum_nodes is None else maximum_nodes
        pending, count = [(value, 0)], 0
        while pending:
            item, depth = pending.pop()
            count += 1
            self._check(count, node_limit)
            self._check(depth, depth_limit)
            self.json_nodes += 1
            self._check(self.json_nodes, self.MAX_JSON_NODES)
            if type(item) is dict:
                self._check(count + len(pending) + len(item), node_limit)
                self._check(self.json_nodes + len(pending) + len(item), self.MAX_JSON_NODES)
                for key, child in item.items():
                    if type(key) is not str:
                        raise PageCapacityError('page_json_type')
                    try:
                        key.encode('utf-8', errors='strict')
                    except UnicodeError:
                        raise PageCapacityError('page_json_unicode') from None
                    pending.append((child, depth + 1))
            elif type(item) is list:
                self._check(count + len(pending) + len(item), node_limit)
                self._check(self.json_nodes + len(pending) + len(item), self.MAX_JSON_NODES)
                pending.extend((child, depth + 1) for child in item)
            elif type(item) is str:
                try:
                    item.encode('utf-8', errors='strict')
                except UnicodeError:
                    raise PageCapacityError('page_json_unicode') from None
            elif item is None or type(item) in (bool, int):
                pass
            elif type(item) is float and math.isfinite(item):
                pass
            else:
                raise PageCapacityError('page_json_type')
        return count

    def history(self, model, rows):
        for row in rows:
            self._history.add((model.__tablename__, row.id))
            self._check(len(self._history), self.MAX_HISTORY)

    def projection(self, *, final=False):
        if final:
            self.final_calls += 1
            self._check(self.final_calls, self.MAX_FINAL)
        else:
            self.value_calls += 1
            self._check(self.value_calls, self.MAX_VALUES)

    def item(self, item):
        nodes = self.json(item, maximum_depth=5, maximum_nodes=272)
        from .domain import stable_json
        encoded = stable_json(item).encode('utf-8')
        self.item_nodes += nodes
        self.item_bytes += len(encoded)
        self._check(len(encoded), 65536)
        self._check(self.item_nodes, self.MAX_ITEM_NODES)
        self._check(self.item_bytes, self.MAX_ITEM_BYTES)

    def preflight(self, db, model, *where, maximum=1, limits=None, columns=None, order=()):
        """Only length integers are materialized here; probe rows are charged."""
        limits = limits or {}
        selected = [column for column in model.__table__.columns
                    if (columns is None or column.key in columns)
                    and isinstance(column.type, (String, JSON, LargeBinary))]
        expressions = [func.length(cast(cast(column, Text), LargeBinary)).label(column.key)
                       for column in selected]
        remaining = self.MAX_ROWS - self.charged_rows
        statement = (select(*expressions, literal(1).label('_present')).select_from(model)
                     .where(*where).order_by(*(order or tuple(model.__table__.primary_key.columns)))
                     .limit(min(maximum, remaining) + 1))
        rows = []
        for row in db.execute(statement).mappings():
            self.actual_rows += 1
            self.reserve_rows(1)
            rows.append(dict(row))
            self._check(len(rows), maximum)
            for column in selected:
                default = (column.type.length * 4 if isinstance(column.type, String)
                           and column.type.length else 65536)
                length = row[column.key]
                if length is not None and (type(length) is not int or length < 0
                                          or length > limits.get(column.key, default)):
                    raise PageCapacityError('page_column_capacity')
        return rows

    def load(self, db, model, *where, maximum=1, columns=None, extra=(), order=(), limits=None):
        """Load declared ORM or narrow columns after reserving every payload row."""
        metadata = self.preflight(db, model, *where, maximum=maximum, columns=columns,
                                  order=order, limits=limits)
        self.reserve_rows(len(metadata))
        self.storage(sum(length or 0 for row in metadata
                         for key, length in row.items() if key != '_present'))
        selected = None if columns is None else [getattr(model, name) for name in columns]
        statement = (select(model) if selected is None else select(*selected, *extra))
        statement = (statement.where(*where)
                     .order_by(*(order or tuple(model.__table__.primary_key.columns)))
                     .limit(maximum + 1))
        result = db.scalars(statement) if selected is None else db.execute(statement)
        rows = list(result)
        self.actual_rows += len(rows)
        if len(rows) != len(metadata):
            raise PageCapacityError('page_read_set_changed')
        for row in rows:
            for column in model.__table__.columns:
                if isinstance(column.type, JSON) and (columns is None or column.key in columns):
                    self.json(getattr(row, column.key))
        return rows

    def get(self, db, model, identifier, *, limits=None):
        primary, = model.__table__.primary_key.columns
        rows = self.load(db, model, primary == identifier, limits=limits)
        return rows[0] if rows else None

    def scalar(self, db, statement):
        """Only declared numeric computations: payload columns use load instead."""
        self.reserve_rows(1)
        rows = list(db.execute(statement.limit(1)))
        self.actual_rows += len(rows)
        return rows[0][0] if rows else None

    def schema(self, connection):
        # Fixed SQL reads at most two short version strings, with lengths first.
        from sqlalchemy import text
        lengths = list(connection.execute(text(
            "SELECT length(CAST(version AS BLOB)) FROM tire_schema_versions WHERE version IN "
            "('025_external_fact_governance','026_query_ownership') LIMIT 3")))
        self.actual_rows += len(lengths)
        self.reserve_rows(len(lengths))
        if len(lengths) > 2 or any(type(row[0]) is not int or row[0] > 320 for row in lengths):
            raise PageCapacityError('page_schema_capacity')
        self.reserve_rows(len(lengths))
        self.storage(sum(row[0] for row in lengths))
        rows = list(connection.execute(text(
            "SELECT version FROM tire_schema_versions WHERE version IN "
            "('025_external_fact_governance','026_query_ownership') LIMIT 3")))
        self.actual_rows += len(rows)
        if len(rows) != len(lengths):
            raise PageCapacityError('page_read_set_changed')
        return {row[0] for row in rows}
