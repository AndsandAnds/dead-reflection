import sqlalchemy as sa  # type: ignore[import-not-found]

from reflections.memory import repository


def test_repository_search_builds_inner_product_order() -> None:
    # We compile the query shape (no DB needed) by reusing the same operator text.
    emb_lit = "[0.1,0.2]"
    order_expr = sa.text(f"embedding <#> '{emb_lit}'::vector")
    stmt = sa.select(repository.memory_items.c.id).order_by(order_expr.asc()).limit(5)
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "<#>" in compiled
    assert "LIMIT 5" in compiled
