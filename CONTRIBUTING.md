# Contributing

Help improve the usefulness of research findings, evidence discipline and completion time. Changes should address an observed problem while keeping the skill portable.

## Reporting a retrieval miss or weak recommendation

Open an issue with the task description, constraints, skill version, agent/tools and time budget. Include the report's relevant finding and the primary source that shows what was missed or misjudged. Distinguish whether a project never appeared in search, was lost during selection, or appeared but was not investigated enough. Redact credentials and private project/source content.

An expected repository should be judged for suitability independently of whether it was found. Useful partial and cross-stack references count too; repository count alone is not a quality metric.

## Making a change

- Keep the installable package self-contained under `skills/reuse-research/`.
- Preserve attribution and source/evidence bindings. Keep documented, inspected and tested findings distinct.
- For helper changes, add a meaningful counterexample test and run the offline suite:

```bash
python -m unittest discover -s tests -p "test_reuse*.py" -v
```

For behavioral changes, use a fresh realistic request with expected repository names withheld, or label a saved-evidence replay explicitly. Record the package version, original clock, tools and access failures. Keep raw research artifacts local and summarize the evidence needed to assess the change.

Describe the problem, resulting behavior and validation in your pull request. Narrow fixes for demonstrated failures are preferred to extra rules or infrastructure without evidence of a need.
