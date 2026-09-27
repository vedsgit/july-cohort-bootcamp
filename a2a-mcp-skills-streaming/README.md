# Learner lab

Refund check for sample orders 1042–1045. READY_FOR_REVIEW means ask a human. It is not an approval and not a payment.

Keep `python run.py` running while you use the CLI or UI.

## Start

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock.txt
cp .env.example .env
python run.py
```

UI: http://127.0.0.1:8611

In a second terminal from this folder:

```bash
source .venv/bin/activate
python -m pytest -q
```

Pytest needs the launcher. It briefly stops and restores this kit's order agent.

## A2A

```bash
python -m demo.cli card hello
python -m demo.cli hello --name Nachiketh
python -m demo.cli hello --name Nachiketh --raw
```

## Skills

```bash
python -m demo.cli skills
python -m demo.cli skill-show clear-explanation
python -m demo.cli skill-run --without
python -m demo.cli skill-run
```

## MCP

```bash
python -m demo.cli mcp order --order 1042
python -m demo.cli mcp policy
python -m demo.cli mcp order --order 1043
```

## Refund

```bash
python -m demo.cli card coordinator
python -m demo.cli refund --order 1042
python -m demo.cli refund --order 1043
python -m demo.cli refund --order 1044
python -m demo.cli refund --order 1042 --raw
```

- 1042: READY_FOR_REVIEW
- 1043: BLOCKED — already fully refunded
- 1044: BLOCKED — outside the 30-day window
- refund_executed is always false

## Order agent down

```bash
python -m demo.cli service order off
python -m demo.cli refund --order 1042
python -m demo.cli service order on
python -m demo.cli refund --order 1042
```

Wait for the launcher to print `order stopped` / `order` before the next command.
Off: INCOMPLETE, policy CLEAR, order ERROR. After restore: READY_FOR_REVIEW with a new task id.

## Live model

Put `OPENAI_API_KEY` and `OPENAI_MODEL` in `.env`. Restart `python run.py`. In the UI choose Live model, or pass `--mode live`.

```bash
python -m demo.cli skill-run --without --mode live
python -m demo.cli skill-run --mode live
python -m demo.cli refund --order 1042 --mode live
python -m demo.cli refund --order 1043 --mode live
```

Routing and the decision stay in Python. The model writes the explanation only.

Ctrl+C in the launcher terminal stops this kit.
