# Price catalog

MCD prices usage at the providers' published standard API rates so the Agents page can compare what
the work would cost through the API with your flat subscriptions, for every task, project and agent.
It is an estimate for comparison, not an invoice.

## Where the prices live

`apps/api/pricing_catalog.json` is the single source. It lists, for each platform, the recent models
MCD agents use:

| Platform | Agents | Source |
|---|---|---|
| OpenAI | Codex | developers.openai.com/api/docs/pricing |
| Anthropic | Claude Code | platform.claude.com/docs/en/about-claude/pricing |
| Google | Hermes and OpenClaw (BYOK fallback) | ai.google.dev/gemini-api/docs/pricing |
| OpenRouter | Hermes and OpenClaw `:free` routes | openrouter.ai/api/v1/models |

Each model has input, output, cache read, 5 minute and 1 hour cache write prices per million tokens, the
long-context tier where the provider has one, an optional list of dated price changes, and the date it
was last checked. Models that left the pricing page stay as `legacy` so old usage keeps its price.

Free OpenRouter models are listed under `free_models` and cost 0. Any model whose name ends in `:free`
is priced at 0 even without a catalog entry and even when a run reports no token counts.

Your own rates (Agents → Billing & rates → Model rates) override the catalog for the model you enter.
A cost the agent itself reports always wins.

## Keeping it current

```bash
scripts/pricing/check.py            # compare with the live pages; exit 1 if a price differs
scripts/pricing/check.py --new      # also list models on the pages that are not in the catalog
scripts/pricing/check.py --apply    # write the changed prices and today's date into the catalog
```

The check reads only what it can read without guessing. A page it cannot read is reported, never treated
as unchanged. It does not add models: choose which new models MCD will use, add an entry (copy a
neighbour), run the check, and it confirms the numbers against the page. Review the diff of
`pricing_catalog.json`, then release it like any change.

Dated changes (for example Gemini 3.x prices rising on 2027-01-01) are in the model's `changes` list
and apply to usage on or after their date, so history keeps the price in force at the time.

## What is not in the estimate

Tools, search grounding, batch, flex and priority tiers, regional or residency surcharges and taxes.
Usage with no token counts (for example a run that failed before the model answered) stays unpriced
rather than being counted as zero.
