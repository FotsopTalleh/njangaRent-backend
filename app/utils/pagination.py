# ---------------------------------------------------------------------------
# pagination.py — Firestore pagination helper
# ---------------------------------------------------------------------------
from typing import Any, Dict, List, Tuple


def paginate_query(
    query,
    page: int = 1,
    limit: int = 20,
    sort_key: str = "createdAt",
    sort_reverse: bool = True,
) -> Tuple[List[Dict[str, Any]], int]:
    """Paginate a Firestore query using offset-based pagination.

    Sorting is done in Python after fetching, so services do NOT need to call
    .order_by() — which would require Firestore composite indexes when combined
    with .where() filters on different fields.

    Args:
        query:        A Firestore CollectionReference or Query (already filtered).
        sort_key:     Document field to sort by (default: "createdAt").
        sort_reverse: True = descending order (newest first).
        page:  1-based page number.
        limit: Number of documents per page.

    Returns:
        Tuple of:
          - list of document dicts (with 'id' field added)
          - total document count for the **unfiltered** query
            NOTE: Firestore does not support server-side COUNT natively in all
            versions of the Admin SDK; we count by fetching all doc IDs here.
            For large collections consider maintaining a separate counter field.

    Usage::

        docs, total = paginate_query(
            db.collection("payments").where("landlordId", "==", uid),
            page=page,
            limit=limit,
        )
    """
    if page < 1:
        page = 1
    if limit < 1:
        limit = 20

    offset = (page - 1) * limit

    # Fetch total count by streaming only document references (no field data).
    # This is more efficient than fetching full documents for the count.
    count_docs = list(query.stream())
    total = len(count_docs)

    # Sort in Python — avoids the Firestore composite-index requirement that
    # arises when combining .where() on one field with .order_by() on another.
    def _sort_val(doc):
        val = doc.to_dict().get(sort_key)
        # Firestore Timestamps and Python datetimes are both comparable.
        # Fallback to empty string so unsortable docs don't crash.
        return val if val is not None else ""

    try:
        count_docs.sort(key=_sort_val, reverse=sort_reverse)
    except TypeError:
        pass  # Mixed/incomparable types — leave in Firestore order

    # Apply offset + limit for the actual page.
    paginated_docs = count_docs[offset : offset + limit]

    results = []
    for doc in paginated_docs:
        data = doc.to_dict()
        data["id"] = doc.id
        results.append(data)

    return results, total


def parse_pagination_args(args) -> Tuple[int, int]:
    """Parse ?page= and ?limit= from Flask request.args.

    Returns:
        Tuple of (page, limit) with sensible defaults.
    """
    try:
        page = max(1, int(args.get("page", 1)))
    except (TypeError, ValueError):
        page = 1

    try:
        limit = max(1, min(100, int(args.get("limit", 20))))
    except (TypeError, ValueError):
        limit = 20

    return page, limit
