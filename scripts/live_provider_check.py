from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv
from google import genai
from groq import AsyncGroq


async def main() -> int:
    load_dotenv()
    prompt = "In one sentence, tell visitors to contact ZIT Admissions for course information."
    failures: list[str] = []
    google_key = os.getenv("GOOGLE_AI_API_KEY")
    groq_key = os.getenv("GROQ_API_KEY")
    if not google_key and not groq_key:
        print("LIVE SKIPPED\tprovider keys missing")
        return 0
    if google_key:
        try:
            client = genai.Client(api_key=google_key)
            stream = await client.aio.models.generate_content_stream(
                model="gemini-3.5-flash-lite",
                contents=prompt,
                config={"max_output_tokens": 80},
            )
            first = ""
            async for event in stream:
                if getattr(event, "text", None):
                    first += str(event.text)
                    break
            if not first:
                failures.append("gemini")
        except Exception as exc:
            failures.append(f"gemini:{type(exc).__name__}")
    if groq_key:
        try:
            client = AsyncGroq(api_key=groq_key)
            stream = await client.chat.completions.create(
                model="openai/gpt-oss-20b",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=80,
                stream=True,
            )
            first = ""
            async for event in stream:
                choices = getattr(event, "choices", None)
                if choices:
                    content = getattr(choices[0].delta, "content", None)
                    if content:
                        first += str(content)
                        break
                    reasoning = getattr(choices[0].delta, "reasoning", None)
                    if reasoning:
                        first += str(reasoning)
                        break
            if not first:
                failures.append("groq")
        except Exception as exc:
            failures.append(f"groq:{type(exc).__name__}")
    if failures:
        print("LIVE FAIL\t" + ",".join(failures))
        return 1
    print("LIVE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
