import os

from openai import APIError, APITimeoutError

from app.models import RiskFlag


def inspect_transfer(amount_minor: int, currency: str, tx_id: str) -> RiskFlag | None:
    \"\"\"Transparent starter rules; an LLM can explain a flag but cannot decide the outcome.\"\"\"
    thresholds = {\"USD\": 1_000_000, \"EUR\": 1_000_000, \"GBP\": 800_000}
    if amount_minor < thresholds.get(currency, 1_000_000):
        return None
    reason = f\"High-value transfer: {amount_minor} minor units {currency}\"
    explanation = None
    api_key = os.getenv(\"OPENAI_API_KEY\")
    if api_key:
        try:
            from openai import OpenAI

            response = OpenAI(api_key=api_key).chat.completions.create(
                model=os.getenv(\"OPENAI_MODEL\", \"gpt-4o-mini\"),
                messages=[
                    {\"role\": \"system\", \"content\": \"Explain this deterministic transaction risk flag in one neutral sentence. Do not recommend approval or denial.\"},
                    {\"role\": \"user\", \"content\": reason},
                ],
                max_tokens=80,
            )
            explanation = (response.choices[0].message.content or \"\").strip()[:1000] or None
        except (APIError, APITimeoutError, ValueError):
            explanation = None
    return RiskFlag(transaction_id=tx_id, reason=reason, score=70, explanation=explanation)
