import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from oskill.hybrid_search import SearchResult, hybrid_search


async def test_hybrid_integration():
    # Mock LLM and Registry
    llm = MagicMock(return_value={"content": "0: 9\n1: 1"})

    with (
        patch("obase.provider_registry.ProviderRegistry.get_caller", return_value=llm),
        patch("oskill.hybrid_search._bm25_search", return_value=[("d1", 0.5), ("d2", 0.4)]),
        patch("oskill.hybrid_search._dense_search", new_callable=AsyncMock, return_value=[]),
        patch(
            "oskill.hybrid_search._enrich",
            side_effect=lambda hits, **kwargs: [
                SearchResult(type="sub", id=h[0], title=h[0], score=h[1], highlight="")
                for h in hits
            ],
        ),
    ):
        # 1. Basic
        r1 = await hybrid_search(query="test", corpus_id="user_demo", top_k=5)
        print(f"basic: {len(r1)} results")

        # 2. With rerank (from oprim)
        from oprim.llm_judge_rerank import llm_judge_rerank

        # We need to wrap it because hybrid_search expects Reranker protocol
        def rerank_fn(*, query, documents, top_k=None):
            return llm_judge_rerank(query=query, documents=documents, llm=llm, top_k=top_k)

        r2 = await hybrid_search(
            query="test",
            corpus_id="user_demo",
            top_k=5,
            rerank=rerank_fn,
        )
        print(f"with rerank: {len(r2)} results, best score: {r2[0].score}")

        # 3. With expand
        from oprim.llm_query_expand import llm_query_expand

        def expand_fn(*, query, num_variants):
            # mock llm for expand
            expand_llm = MagicMock(return_value={"content": "var 1\nvar 2"})
            return llm_query_expand(query=query, llm=expand_llm, num_variants=num_variants)

        r3 = await hybrid_search(
            query="test",
            corpus_id="user_demo",
            top_k=5,
            expand=expand_fn,
        )
        print(f"with expand: {len(r3)} results")


if __name__ == "__main__":
    asyncio.run(test_hybrid_integration())
