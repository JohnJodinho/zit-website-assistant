"""Small Gemini text-generation check using credentials from .env."""

import os

from dotenv import load_dotenv
from google import genai


def main() -> None:
    load_dotenv()
    api_key = os.getenv("GOOGLE_AI_API_KEY")
    if not api_key:
        raise RuntimeError("Set GOOGLE_AI_API_KEY in .env before running this script.")

    model = os.getenv("GEMINI_MODEL_ID", "gemini-3.5-flash-lite")
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents="Explain how AI works in a few words.",
    )
    if not response.text:
        raise RuntimeError("Gemini returned no text.")

    print(response.text)


if __name__ == "__main__":
    main()
