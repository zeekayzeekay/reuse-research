# Offline tests

Run from the repository root with Python 3.11+:

```bash
python -m unittest discover -s tests -p "test_reuse*.py" -v
```

Fixtures are synthetic and network requests are replaced by controlled transports or mocks. Tests cover discovery/provenance, evidence/source ownership, screening/case/cache mechanics, timing/handoff repairs and preservation of whole-solution alternatives. `trace_retrieval.py` supports tests for missing historical traces and repository identity boundaries; it is not part of the installed skill.

Counterexample tests intentionally exercise rejected inputs and can print diagnostic messages. The unittest result determines success. Passing checks do not measure live recall, agent judgment, runtime suitability or automatic invocation. See [validation notes](../docs/VALIDATION.md).
