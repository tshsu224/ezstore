"""Local LLM-as-judge for `custom_response_quality` (see eval_config.yaml)."""

import os
import threading
import time

from google import genai
from google.genai import types
from pydantic import BaseModel

_local = threading.local()


class _Verdict(BaseModel):
    score: int  # 1-5
    explanation: str


def _client() -> genai.Client:
    """One client per grading thread.

    The eval SDK grades cases on its own thread pool; this initialization runs once
    per thread. Avoids creating a new client for each eval case, which would re-do
    ADC and the TLS handshake every time. Each thread gets its own client, because
    google-auth freezes the SSL context after the first connection when a client
    certificate is present.
    """
    client = getattr(_local, "client", None)
    if client is None:
        # AI Studio (GEMINI_API_KEY) or Agent Platform (ADC).
        client = _local.client = genai.Client()
    return client


def evaluate(instance):
    reference = instance.get("reference")
    rubric = (
        "Grade the agent's final response on a 1-5 scale (1 poor, 5 excellent) for "
        "accuracy, relevance, and clarity."
    )
    if reference:
        rubric += (
            " The response should agree with the expected answer below; penalize "
            "factual disagreement with it."
        )
    rubric += (
        " Note that system policy requires all links to be plain text URLs (http://...) and "
        "strictly forbids Markdown link syntax [text](url) even if requested by user. Do not penalize plain text links."
    )
    prompt = (
        f"You are an expert QA evaluator for an enterprise AI assistant. {rubric}\n"
        f"User Prompt: {instance.get('prompt', '')}\n"
        f"Final Response: {instance.get('response', '')}\n"
    )
    if reference:
        prompt += f"Expected Answer (ground truth): {reference}\n"
    prompt += f"Full Agent Trace: {instance.get('agent_data', '')}\n"

    verdict = None
    response = None
    for attempt in range(6):
        try:
            response = _client().models.generate_content(
                model=os.environ.get("AGENT_MODEL", "gemini-3.8-flash"),
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0,  # deterministic grading
                    response_mime_type="application/json",
                    response_schema=_Verdict,  # guaranteed schema-valid JSON
                ),
            )
            verdict = response.parsed
            break
        except Exception as e:
            err = str(e)
            if ("429" in err or "RESOURCE_EXHAUSTED" in err or "quota" in err.lower()) and attempt < 5:
                time.sleep(3 * (attempt + 1))
                continue
            raise

    if verdict is None:  # model returned nothing usable
        return {"score": 0, "explanation": getattr(response, "text", "") or ""}
    return {"score": max(1, min(5, verdict.score)), "explanation": verdict.explanation}
