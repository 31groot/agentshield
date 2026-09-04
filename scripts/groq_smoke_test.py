from __future__ import annotations

from dotenv import load_dotenv

from config import Settings
from groq import Groq
from integrations.groq import GroqIntentParser


load_dotenv()

def main() -> None:
    settings = Settings.from_environment()

    client = Groq(
        api_key=settings.groq_api_key,
    )

    parser = GroqIntentParser(
        client=client,
        model=settings.groq_model,
    )

    result = parser.parse(
        user_message="Buy running shoes from merchant_001 for under ₹5000.",
        user_id=settings.api_user_id,
        agent_id=settings.api_agent_id,
        intent_id="live-groq-smoke-001",
        merchant_context={
            "merchant_id": "merchant_001",
            "category": "footwear",
        },
    )

    print("Groq smoke test: PASS")
    print()
    print("Raw request:")
    print(result.raw_user_prompt)
    print()
    print("Authorization interpretation:")
    print(result.authorization.model_dump())
    print()
    print("Intent proposal:")
    print(result.intent_proposal.model_dump(mode="json"))


if __name__ == "__main__":
    main()

