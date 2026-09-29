# Claude recordings

This folder is for recordings of real Claude investigations, one JSON file per scenario. To create them (needs an Anthropic API key once):

```bash
python scripts/fetch_data.py
healpipe eval --planner claude --record docs/claude_recordings
```

Anyone can then replay them without a key:

```bash
healpipe eval --planner replay
```

The replay re-executes Claude's recorded tool calls against the live tools and guardrails. It fails as a "stale recording" if the live results no longer match what Claude saw. The format is documented in `src/healpipe/replay.py`.
