# Starter — Governed LLM Agent

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Put keys/mode in `.env` (see `.env.example`). Prefer `GOVERNED_LLM_MODE=fake` while coding.

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

Complete TODOs 1–7 (see pack `docs/learner_lab.md`), then:

```bash
python src/governed_llm_agent/demo.py
python src/governed_llm_agent/demo.py "Please refund $120 for ord_A100"
# Audit trail (JSONL): logs/audit.jsonl
```

While coding, show symptom + test together:

```bash
python src/governed_llm_agent/show_problems.py policy
python src/governed_llm_agent/show_problems.py all
```

TODOs:
1. `support_agent/contracts.py` — `extra="forbid"`
2. `support_agent/policy.py` — deny-by-default checks
3. `support_agent/tools.py` — idempotent refund
4–5. `support_agent/gateway.py` — invalid I/O handling + output validation
6. `governed_llm_agent/assemble.py` — trusted actor + IDs
7. `governed_llm_agent/graph.py` — HITL route in `after_enforce`
