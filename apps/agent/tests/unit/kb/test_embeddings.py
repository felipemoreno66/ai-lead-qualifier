from __future__ import annotations

import httpx
import pytest
import respx

from lead_qualifier.config import Settings
from lead_qualifier.infrastructure.db.tables import KB_EMBEDDING_MODELS
from lead_qualifier.infrastructure.embeddings import FakeEmbeddings, build_embeddings
from lead_qualifier.infrastructure.embeddings.fastembed import FastEmbeddings
from lead_qualifier.infrastructure.embeddings.openai import OPENAI_URL, OpenAIEmbeddings


def test_fake_embeddings_are_deterministic_unit_vectors():
    fake = FakeEmbeddings()
    a, b = fake.embed(["refund policy", "refund policy"])
    assert a == b
    assert len(a) == fake.dimension == 384
    assert sum(x * x for x in a) == pytest.approx(1.0)
    assert fake.embed([""])[0][0] == 1.0


def test_similar_texts_score_higher_than_unrelated_ones():
    q, near, far = FakeEmbeddings().embed(
        ["refund policy", "refund policy for the bootcamp", "scholarship application form"]
    )
    dot = lambda x, y: sum(i * j for i, j in zip(x, y, strict=True))  # noqa: E731
    assert dot(q, near) > dot(q, far)


def test_factory_picks_the_provider_and_model_ids_are_allowed_by_the_database():
    assert isinstance(build_embeddings(Settings(embeddings_provider="fake")), FakeEmbeddings)
    fast = build_embeddings(Settings(embeddings_provider="fastembed"))
    assert isinstance(fast, FastEmbeddings)  # lazy: nothing is downloaded yet
    ids = {FakeEmbeddings.model_id, FastEmbeddings.model_id, OpenAIEmbeddings.model_id}
    assert ids == set(KB_EMBEDDING_MODELS)


def test_openai_requires_a_key_and_sends_shortened_embeddings():
    with pytest.raises(ValueError):
        OpenAIEmbeddings("")
    with respx.mock:
        route = respx.post(OPENAI_URL).mock(
            return_value=httpx.Response(
                200,
                json={"data": [{"index": 1, "embedding": [0.2]}, {"index": 0, "embedding": [0.1]}]},
            )
        )
        out = OpenAIEmbeddings("k").embed(["a", "b"])
    assert out == [[0.1], [0.2]]
    assert b'"dimensions":384' in route.calls[0].request.content.replace(b" ", b"")


def test_the_similarity_threshold_defaults_to_the_models_own():
    assert FastEmbeddings.default_min_similarity == 0.45
    assert FakeEmbeddings.default_min_similarity == 0.3
    # `KB_MIN_SIMILARITY=` (empty) in a .env file means "use the model's default"
    assert Settings(_env_file=None).kb_min_similarity is None
    assert Settings(kb_min_similarity=0.5).kb_min_similarity == 0.5
