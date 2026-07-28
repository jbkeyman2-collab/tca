# Future Possibilities: What TCA Enables

*This document is not part of the core Tiered Cognitive Architecture proposal. It describes downstream capabilities that become possible only after the kernel is proven.*

*Status: Research direction — do not merge into main architecture doc until Part IV benchmarks pass.*

---

## Cognitive Experience Consolidation

### The distinction that matters

The core TCA claim is independent:

> Deterministic executive substrate + probabilistic specialized workers = lower cost, better coherence, auditable state.

This document is about what you can do *after* that works.

Current systems produce transcripts: input text → output text. A TCA system produces something else as a byproduct of how it works: a structured, versioned record of cognition.

### Transcript vs. Cognitive Trace

**Transcript (what we have today):**
```
User: The budget is 500k
Assistant: Got it, budget is 500k
```

**Cognitive trace (what TCA produces for free):**
```
- user_input: "The budget is 500k"
- segmentation: [statement]
- extraction: {type: fact, content: "The budget is 500k", confidence: 0.92}
- anchor_candidates: {entities: ["project_budget"], method: "jaccard_content_words", scores: [...]}
- merge_check: {contradicts: false, semantic_ambiguities: []}
- commit_gate: {decision: commit, expected_costs: {commit: 8, branch: 25, ask: 20}}
- commit: {id: "a3f1...", parent: "ef97...", snapshot_ref: "...", diff: {added: [...]}}
- downstream: {correction: none, provenance: turn_14}
```

If later corrected:
```
- correction: {type: revert, from: "a3f1...", to: "ef97...", reason: "user stated 350k"}
- audit: diff shows added then removed, with timestamps
```

The first is language. The second is cognition made observable.

### What the telemetry layer actually logs

The kernel already maintains this to function. Persisting it is the "Cognitive Telemetry Layer" — the mechanism inside the broader idea of Consolidation.

Per turn, log:

1.  Semantic interpretation + per-slot confidence
2.  Entity resolution scores and anchor candidates
3.  Graph delta (typed edges: supports / contradicts / supersedes / depends_on)
4.  Commit gate inputs: P(wrong), cost_of_late_correction, fatigue_term, decision
5.  Branch lifecycle: base, head, divergent commits, merge or abandon reason
6.  Compiled context: anchor_ids, traversal depth, payload size, entities included
7.  Post-hoc signals: did Tier Two reference an unfetched entity? Did user correct a fact that was in state but not retrieved? (compilation miss)
8.  Provenance for every entity: which turn/call, which model, which schema version

This is an OS log, not a chat log.

### Why this is not "models training on their own slop"

The failure mode everyone will cite is real: training on raw model outputs degrades quality.

This is a different claim:

> **The system creates a verified record of cognition, and that record becomes the training substrate.**

Quality comes from the verification structure, not from model cleverness:

-  Facts have confidence, provenance, and status (active/superseded/retracted)
-  Conflicts are detected structurally, not silently absorbed
-  Corrections are reverts to a known-good snapshot, not manual overwrites
-  Audit trail is diffable: added vs removed is explicit
-  Failed reasoning paths are preserved as rejected branches, not deleted

You curate traces of *successful reasoning under uncertainty, including recovery*, not raw generations.

This is analogous to how a human expert learns: not just from final answers, but from the worked example with the crossed-out attempt still visible.

### What not to do

- **No online self-modification.** No real-time weight updates from interaction traces. This is offline, batched, curated, human-gated.
- **No auto-promotion of high-confidence commits.** Confidence is a gate input, not a quality label for training. Quality label comes from downstream outcome + lack of correction over time.
- **No training on uncorrected branches.** A branch that was never resolved is not data. It's ambiguity preserved, not knowledge.

### Roadmap placement

This belongs after benchmarks, not before. The logical progression:

1.  Build kernel with snapshot-based git ops (done in v2)
2.  Demonstrate: 30-40% token reduction + 50% correction reduction on 20-turn tasks with abandoned ideas
3.  Add richer semantic components (typed properties, schema evolution)
4.  Collect cognitive traces at scale under the telemetry layer
5.  Curate traces into datasets representing verified reasoning processes
6.  Use datasets to improve future small embedded classifiers and, eventually, larger models

If 1-2 fail, 4-6 are irrelevant. That's why this stays in a separate note until 2 passes.

### Naming

-   **Section title:** Cognitive Experience Consolidation (preferred — maps to biology, avoids overpromising)
-   **Mechanism name inside it:** Cognitive Telemetry Layer (fits OS analogy perfectly)
-   **Avoid:** Flywheel (buzzword), Self-Improving Infrastructure (invites autonomy debates), Post-Deployment Model Evolution (too bland, sounds like MLOps)

### One-sentence test

If someone asks what this is, answer:

> TCA doesn't learn from itself — it produces a verified log of its own cognition that we can later curate into better training data than raw transcripts.

If that sentence holds, the framing is correct.

---
*Companion to: Tiered Cognitive Architecture for AI Systems. Keep separate until Part V thresholds met.*
