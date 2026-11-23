"""P0-only Gemini embedding and in-memory search example.

This script embeds sample text only. It does not read or store visitor data.
"""

import math
import os
from typing import Literal

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

TaskType = Literal["RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY"]


class SourceDocument(BaseModel):
    id: str
    title: str
    text: str


class EmbeddedDocument(SourceDocument):
    vector: list[float] = Field(min_length=1)


class SearchQuery(BaseModel):
    text: str


def embed_text(
    client: genai.Client,
    text: str,
    task_type: TaskType,
    model: str,
    dimensions: int,
) -> list[float]:
    result = client.models.embed_content(
        model=model,
        contents=text,
        config=types.EmbedContentConfig(
            task_type=task_type,
            output_dimensionality=dimensions,
        ),
    )
    if not result.embeddings or result.embeddings[0].values is None:
        raise RuntimeError("Gemini returned no embedding.")

    vector = [float(value) for value in result.embeddings[0].values]
    if len(vector) != dimensions:
        raise RuntimeError(f"Expected {dimensions} embedding values, received {len(vector)}.")

    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude == 0:
        raise RuntimeError("Gemini returned a zero-length embedding.")
    return [value / magnitude for value in vector]


def main() -> None:
    load_dotenv()
    api_key = os.getenv("GOOGLE_AI_API_KEY")
    if not api_key:
        raise RuntimeError("Set GOOGLE_AI_API_KEY in .env before running this script.")

    model = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")
    dimensions = int(os.getenv("EMBEDDING_DIM", "768"))
    if dimensions not in {768, 1536, 3072}:
        raise ValueError("EMBEDDING_DIM must be 768, 1536, or 3072.")

    documents = [
        SourceDocument(
            id="apply",
            title="How to apply",
            text="Choose a course and complete the online application form.",
        ),
        SourceDocument(
            id="courses",
            title="Choosing a course",
            text="Compare course details, entry requirements, and duration.",
        ),
    ]
    query = SearchQuery(text="How do I start an application?")

    client = genai.Client(api_key=api_key)
    embedded_documents = [
        EmbeddedDocument(
            **document.model_dump(),
            vector=embed_text(
                client,
                f"title: {document.title} | text: {document.text}",
                "RETRIEVAL_DOCUMENT",
                model,
                dimensions,
            ),
        )
        for document in documents
    ]
    query_vector = embed_text(
        client,
        query.text,
        "RETRIEVAL_QUERY",
        model,
        dimensions,
    )

    best_match = max(
        embedded_documents,
        key=lambda document: sum(
            query_value * document_value
            for query_value, document_value in zip(query_vector, document.vector, strict=True)
        ),
    )
    score = sum(
        query_value * document_value
        for query_value, document_value in zip(query_vector, best_match.vector, strict=True)
    )
    print(f"Model: {model}; vector size: {dimensions}")
    print(f"Best match: {best_match.title} (similarity {score:.3f})")


if __name__ == "__main__":
    main()
