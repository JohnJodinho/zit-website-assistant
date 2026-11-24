from __future__ import annotations

from types import SimpleNamespace

from app.chat.providers import GeminiProvider, GroqProvider, Usage


async def test_groq_stream_requests_usage_and_forwards_only_content(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    async def create(**kwargs: object):
        calls.append(kwargs)

        async def events():
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="answer"))],
                usage=None,
            )
            yield SimpleNamespace(
                choices=[],
                usage=SimpleNamespace(prompt_tokens=12, completion_tokens=4),
            )

        return events()

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr("app.chat.providers.AsyncGroq", lambda **_: fake_client)
    provider = GroqProvider("test-key")

    actual = [
        item async for item in provider.stream(model="model", prompt="prompt", max_output_tokens=20)
    ]

    assert actual == [("answer", None), ("", Usage(12, 4))]
    assert calls[0]["extra_body"] == {"stream_options": {"include_usage": True}}


async def test_gemini_stream_hides_thoughts_and_reports_usage(monkeypatch) -> None:
    async def generate_content_stream(**_: object):
        async def events():
            yield SimpleNamespace(
                candidates=[
                    SimpleNamespace(
                        content=SimpleNamespace(
                            parts=[
                                SimpleNamespace(text="private reasoning", thought=True),
                                SimpleNamespace(text="answer", thought=False),
                            ]
                        )
                    )
                ],
                usage_metadata=SimpleNamespace(
                    prompt_token_count=10,
                    response_token_count=3,
                    thoughts_token_count=2,
                ),
            )

        return events()

    fake_client = SimpleNamespace(
        aio=SimpleNamespace(models=SimpleNamespace(generate_content_stream=generate_content_stream))
    )
    monkeypatch.setattr("app.chat.providers.genai.Client", lambda **_: fake_client)
    provider = GeminiProvider("test-key")

    actual = [
        item async for item in provider.stream(model="model", prompt="prompt", max_output_tokens=20)
    ]

    assert actual == [("answer", None), ("", Usage(10, 5))]
