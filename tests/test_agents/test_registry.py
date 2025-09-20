from stackbench.agents import list_agents


def test_list_agents_filters_cli_aliases():
    cli_agents = list_agents("cli")
    assert "openai-cli" in cli_agents
    assert "cursor" not in cli_agents


def test_list_agents_returns_all_when_no_filter():
    all_agents = list_agents()
    assert "cursor" in all_agents
    assert "anthropic-cli" in all_agents
