# Must match database vector dimension (see db/migrations/002_*.sql) and BGE model card.

EMBEDDING_MODEL_NAME = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIMENSION = 384

# BGE: query and passage differ for retrieval quality.
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
