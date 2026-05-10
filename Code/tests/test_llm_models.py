from openpilot.llm import LLMMessage, LLMRequest, LLMResponse


def test_llm_request_and_response_serialize():
    request = LLMRequest(
        messages=[LLMMessage(role="user", content="hello")],
        response_format="json_object",
        metadata={"trace": "unit"},
    )
    response = LLMResponse(
        content='{"ok": true}',
        parsed_json={"ok": True},
        model="test-model",
        provider="test-provider",
        finish_reason="stop",
    )

    assert request.model_dump()["response_format"] == "json_object"
    assert response.model_dump()["parsed_json"] == {"ok": True}


