-- Create and populate a pgvector benchmark table for "memory retrieval"-style queries.
--
-- Usage:
--   psql ... -v vec_rows=200000 -f bench/sql/vector_setup.sql
--
-- Note: We generate normalized random embeddings to match our production choice:
-- L2-normalized embeddings + inner product search.

\set ON_ERROR_STOP on

CREATE EXTENSION IF NOT EXISTS vector;

DROP TABLE IF EXISTS bench_vectors;
CREATE TABLE bench_vectors (
  id bigserial PRIMARY KEY,
  user_id int NOT NULL,
  avatar_id int NOT NULL,
  embedding vector(384) NOT NULL,
  content text NOT NULL
);

-- Populate vectors
INSERT INTO bench_vectors (user_id, avatar_id, embedding, content)
SELECT
  1,
  1,
  l2_normalize(ARRAY(SELECT random() FROM generate_series(1,384))::vector),
  md5(random()::text)
FROM generate_series(1, :vec_rows);

-- Indexes similar to production usage
CREATE INDEX bench_vectors_hnsw_ip ON bench_vectors
USING hnsw (embedding vector_ip_ops);

CREATE INDEX bench_vectors_user_avatar ON bench_vectors (user_id, avatar_id);

ANALYZE bench_vectors;


