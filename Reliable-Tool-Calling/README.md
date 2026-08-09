# Starter Code

## Reliability lab (no API keys)

```bash
python -m unittest discover -s tests -v
```

Implement the eight TODOs in `reliability.py`. Do not change the public interfaces or the tests.

Expected starting state: 19 intentional errors. Expected completed state: 19 passing tests.

## Live stack (after TODOs pass)

```bash
cp .env.example .env   # OPENAI_API_KEY + TAVILY_API_KEY
pip install -r requirements.txt
python demo.py --live "Summarize what FastMCP is"
```

| File | Role |
|---|---|
| `reliability.py` | Policy gateway (your TODOs) |
| `mcp_server.py` | FastMCP server + Tavily `web_search` |
| `adapters.py` | MCP adapter + direct Tavily fallback |
| `agent.py` | LangChain `create_agent` via ChatOpenAI |
| `demo.py` | Scripted demo or `--live` agent run |

After the TODOs pass, run the deterministic scenarios:

```bash
python demo.py --scenario all
```

Named scenarios: `retry`, `fallback`, `forbidden`, `contract`, `breaker`, `rate-limit`, and `idempotency`.
