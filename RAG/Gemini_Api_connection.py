from Security.get_secretes import load_env_from_secret
from Security.Advance_Logger import logger

from google import genai
from groq import Groq

import numpy as np
import asyncio


GEMINI_CHAT_MODEL = "gemini-2.5-flash-lite"
GEMINI_EMBEDDING_MODEL = "gemini-embedding-2"
GROQ_CHAT_MODEL = "llama-3.3-70b-versatile"

class GeminiFunctions:
    def __init__(self):
        self.gemini_client = genai.Client(
            api_key=load_env_from_secret("GEMINI_API_KEY")
        )

        self.groq_client = Groq(
            api_key=load_env_from_secret("GROQ_API_KEY")
        )

    async def generate_response(self, query: str) -> str:
        """
        Primary: Gemini
        Fallback: Groq (on rate limit / quota issues)
        """
        try:
            response = self.gemini_client.models.generate_content(
                model=GEMINI_CHAT_MODEL,
                contents=query
            )
            return response.text

        except Exception as e:
            error_text = str(e).lower()
            logger.error("Gemini.generate_response", e)
            rate_limit_errors = [
                "429",
                "rate limit",
                "quota",
                "resource exhausted",
                "too many requests"
            ]
            should_fallback = any(
                err in error_text for err in rate_limit_errors
            )
            if not should_fallback:
                return ""
            logger.warning(
                "Gemini rate limited. Switching to Groq fallback."
            )
        try:
            completion = self.groq_client.chat.completions.create(
                model=GROQ_CHAT_MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": query
                    }
                ],
                temperature=0.7
            )

            return completion.choices[0].message.content

        except Exception as groq_error:
            logger.error("Groq.generate_response", groq_error)
            return ""

    async def generate_embeddings(self, query: str) -> np.ndarray:
        """
        Gemini embeddings only.
        Groq currently does not provide embeddings API compatible here.
        """
        try:
            result = self.gemini_client.models.embed_content(
                model=GEMINI_EMBEDDING_MODEL,
                contents=query
            )
            vector = np.array(
                result.embeddings[0].values,
                dtype=np.float32
            )
            return vector

        except Exception as e:
            logger.error("Gemini.generate_embeddings", e)
            return np.array([], dtype=np.float32)

    async def groq_response(self, query: str) -> str:
        completion = self.groq_client.chat.completions.create(
                model=GROQ_CHAT_MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": query
                    }
                ],
                temperature=0.7
            )

        return completion.choices[0].message.content

async def main():
    ai = GeminiFunctions()

    response = await ai.groq_response("Hello bro")
    print(response)

if __name__ == "__main__":
    asyncio.run(main())