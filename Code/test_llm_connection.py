#!/usr/bin/env python3
"""Test LLM connection."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from core.llm import LLMClient, LLMRequest, LLMMessage

def main():
    print("Testing LLM connection...")

    try:
        client = LLMClient()
        print(f"✓ LLM client initialized")
        print(f"  Provider: {client.settings.provider}")
        print(f"  Model: {client.settings.model}")
        print(f"  Base URL: {client.settings.base_url}")
        print(f"  Timeout: {client.settings.timeout_seconds}s")

        # Simple test request
        print("\nSending test request...")
        request = LLMRequest(
            messages=[LLMMessage(role="user", content="Say 'hello' in JSON format")],
            response_format="json_object"
        )

        response = client.complete(request)
        print(f"✓ Response received:")
        print(f"  Content: {response.content[:100]}...")
        print(f"  Model: {response.model}")

    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
