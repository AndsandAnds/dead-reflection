-- Read-heavy benchmark for pgvector-based memory retrieval.
--
-- Expects the following table to exist:
--   bench_vectors(id bigserial pk, user_id int, avatar_id int, embedding vector(384), content text)
--
-- Pattern: pick a random row id, use its embedding as the query vector, and
-- perform a top-k similarity search with metadata filters.

\set qid random(1, :max_id)

SELECT id
FROM bench_vectors
WHERE user_id = 1 AND avatar_id = 1
ORDER BY embedding <#> (SELECT embedding FROM bench_vectors WHERE id = :qid)
LIMIT 8;


