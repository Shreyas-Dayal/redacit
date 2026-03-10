"""
Drop-in OpenAI client wrapper that anonymizes prompts before sending
and deanonymizes responses before returning.

Usage:
    from privacy_wrapper import PrivacyClient

    client = PrivacyClient()  # reads OPENAI_API_KEY from env
    response = client.chat("Summarize the contract for John Smith at john@acme.com")
    print(response)  # "John Smith" and email are restored in the reply
"""

import os
from openai import OpenAI
from .anonymizer import Anonymizer


class PrivacyClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-4o-mini",
        anonymizer: Anonymizer | None = None,
    ):
        self._openai = OpenAI(api_key=api_key or os.environ["OPENAI_API_KEY"])
        self.model = model
        self._anonymizer = anonymizer or Anonymizer()

    def chat(self, prompt: str, system: str | None = None) -> str:
        """
        Anonymize prompt → call LLM → deanonymize response.
        Returns the final response string with original values restored.
        """
        result = self._anonymizer.anonymize(prompt)

        if result.mapping:
            print(f"[Privacy] {len(result.mapping)} replacement(s) made before sending.")

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": result.anonymized_text})

        response = self._openai.chat.completions.create(
            model=self.model,
            messages=messages,
        )

        raw_reply = response.choices[0].message.content or ""
        return self._anonymizer.deanonymize(raw_reply, result.mapping)
