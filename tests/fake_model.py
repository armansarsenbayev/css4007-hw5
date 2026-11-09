"""TEST DOUBLE: a scripted chat model used only in tests.

ScriptedChatModel is not a real language model. It returns prepared
AIMessage objects (with or without tool calls) in order, so the graph can
be tested without an API key. It also records the messages it received.
"""

from typing import Any, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field


class ScriptedChatModel(BaseChatModel):
    """Test double. Returns the scripted replies in order.

    If repeat_last is True, the last reply is repeated forever (with fresh
    tool call ids), which simulates a model that never stops asking for tools.
    """

    responses: list[AIMessage]
    repeat_last: bool = False
    received: list[list[BaseMessage]] = Field(default_factory=list)
    position: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted-test-double"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedChatModel":
        return self

    def _generate(self, messages: list[BaseMessage], stop: Optional[list[str]] = None, run_manager=None, **kwargs: Any) -> ChatResult:
        self.received.append(list(messages))
        if self.position < len(self.responses):
            template = self.responses[self.position]
        elif self.repeat_last:
            template = self.responses[-1]
        else:
            raise RuntimeError("ScriptedChatModel ran out of scripted replies")
        n = self.position
        self.position += 1
        tool_calls = [
            {**call, "id": f"call_{n}_{i}", "type": "tool_call"}
            for i, call in enumerate(template.tool_calls)
        ]
        message = AIMessage(content=template.content, tool_calls=tool_calls)
        return ChatResult(generations=[ChatGeneration(message=message)])


def tool_call(name: str, **args: Any) -> AIMessage:
    """Scripted reply that requests one tool."""
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "x"}])


def answer(text: str) -> AIMessage:
    """Scripted final answer with no tool calls."""
    return AIMessage(content=text)
