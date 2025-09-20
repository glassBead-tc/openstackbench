"""Agent implementations and registry helpers for StackBench."""

from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Literal

from .anthropic_cli import AnthropicCLIAgent
from .base import Agent
from .cursor_ide import CursorIDEAgent
from .local_exec import LocalExecAgent
from .openai_cli import OpenAICLIAgent


AgentCategory = Literal["ide", "cli"]


@dataclass(frozen=True)
class AgentDescriptor:
    """Descriptor storing factory and category metadata for an agent alias."""

    factory: Callable[[], Agent]
    category: AgentCategory


def _descriptor(factory: Callable[[], Agent], category: AgentCategory) -> AgentDescriptor:
    return AgentDescriptor(factory=factory, category=category)


_CURSOR = _descriptor(CursorIDEAgent, "ide")
_OPENAI = _descriptor(OpenAICLIAgent, "cli")
_ANTHROPIC = _descriptor(AnthropicCLIAgent, "cli")
_LOCAL = _descriptor(LocalExecAgent, "cli")


AGENT_REGISTRY: Dict[str, AgentDescriptor] = {
    "cursor": _CURSOR,
    "cursor-ide": _CURSOR,
    "openai": _OPENAI,
    "openai-cli": _OPENAI,
    "anthropic": _ANTHROPIC,
    "anthropic-cli": _ANTHROPIC,
    "claude": _ANTHROPIC,
    "local": _LOCAL,
    "local-exec": _LOCAL,
}


def create_agent(name: str) -> Agent:
    """Instantiate an agent by alias."""

    normalized = name.lower()
    try:
        descriptor = AGENT_REGISTRY[normalized]
    except KeyError as exc:  # pragma: no cover - defensive branch
        raise ValueError(f"Unsupported agent '{name}'") from exc
    return descriptor.factory()


def list_agents(category: AgentCategory | None = None) -> List[str]:
    """Return sorted agent aliases, optionally filtered by category."""

    aliases: Iterable[str]
    if category is None:
        aliases = AGENT_REGISTRY.keys()
    else:
        aliases = (
            name
            for name, descriptor in AGENT_REGISTRY.items()
            if descriptor.category == category
        )
    # Deduplicate aliases (aliases may point to the same descriptor) and sort for stability
    return sorted(set(aliases))


__all__ = [
    "Agent",
    "CursorIDEAgent",
    "OpenAICLIAgent",
    "AnthropicCLIAgent",
    "LocalExecAgent",
    "AgentDescriptor",
    "create_agent",
    "list_agents",
    "AGENT_REGISTRY",
]