# Phase 6 Product Demo v3

This write-once snapshot adds a 30-file, 10-task portfolio to the preserved v2 sanity demo.
It is an exploratory product demonstration, not a research benchmark.

- Before: 6/10 processable, 4/10 blocked
- After: 8/10 processable, 2/10 blocked
- Before blockers: one semantic conflict, one insufficient-evidence case, and two missing-information cases
- The return-policy conflict is not reproduced After; the two genuinely missing fields remain open
- Static Readiness is 100 in both states, with zero probable-version groups

Verify with: `python -m scripts.verify_phase6_demo_v3`
