"""Ids of the newest rows per partition, for reads that keep only those (#462).

Several API reads load a table's whole history in ``ORDER BY date DESC, id DESC``
and keep the first row (or first N rows) of each group, entity or instrument.
On the production copy that hydrated thousands of rows with large JSON columns
per request. ``ranked_ids`` selects the same rows in SQL with ``ROW_NUMBER()``
over the same order, so the caller loads only the rows it keeps and the
selection rule is unchanged: the first ``limit`` rows of each partition in that
order. SQLite has window functions from 3.25.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, func, select


def ranked_ids(
    id_column: Any,
    *,
    partition_by: Any,
    order_by: tuple[Any, ...],
    where: tuple[Any, ...] = (),
    limit: int = 1,
) -> Select[Any]:
    """``SELECT id``: the first LIMIT rows of each PARTITION_BY in ORDER_BY order.

    ORDER_BY must end in a unique column (the id) so ties cannot change which
    rows are kept between two reads.
    """

    rank = (
        func.row_number()
        .over(partition_by=partition_by, order_by=order_by)
        .label("row_rank")
    )
    inner = select(id_column.label("row_id"), rank).where(*where).subquery()
    return select(inner.c.row_id).where(inner.c.row_rank <= limit)
