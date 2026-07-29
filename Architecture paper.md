# A Tiered Cognitive Architecture for AI Systems — v2.1 patched
*Incorporates ChatGPT Ideas triage: #1/#8/#12 as tight inserts, preserves snapshot semantics*

## Executive Summary

Current AI systems are built around a remarkably capable computational engine: the large language model (LLM). As these systems have evolved, the language model has gradually assumed responsibility for functions extending well beyond probabilistic inference — conversation state reconstruction, memory management, planning, constraint tracking, tool routing, and execution coordination.

This concentration of responsibility forces fundamentally different classes of computation through the same probabilistic engine. The result is structural inefficiency: repeated reconstruction of conversational state, growing computational cost, degradation over long interactions, and mounting friction for users who must repeatedly correct incorrect assumptions or redirect the conversation.

What follows is not an incremental refinement of today's agent frameworks. Today's frameworks — agents, wrappers, copilots — are patchwork: each improvises its own memory format, its own retry logic, its own notion of state, none of it composable, none of it auditable, none of it held to any shared invariant. That works well enough to demo. It does not work well enough to trust with decision-critical work.

The proposal here is architectural, not incremental: separate **executive cognition** from **inference**, and give the executive layer the discipline of an operating system — persistent, deterministic, versioned, auditable — rather than the discipline of a script holding a conversation together with tool calls.

A single distinction runs underneath everything that follows: **conversation is not state — it is evidence from which state is inferred and maintained.** A transcript is one observation stream. The kernel's job is to maintain the durable cognitive state that the transcript is evidence *of* — goals, facts, preferences, open questions — not to treat the transcript itself as the thing to be remembered. This is what separates the proposal from "conversation memory": memory implies storing what was said; this architecture stores what is *true*, with the transcript demoted to input.

> **Guiding principle:** different classes of cognitive work should be performed by the computational substrate best suited to perform them — and the substrate that decides *which* work goes where must itself be deterministic, not another inference call.

---

## Part I — The Problem

### The current architecture and its structural limitations

Modern AI systems already consist of sophisticated infrastructure surrounding a language model: CPUs, GPUs, retrieval systems, databases, serving engines, orchestration layers, safety systems, external tools. Despite this complexity, the language model frequently functions as the system's de facto executive controller. Each interaction reconstructs conversational state, interprets user intent, selects relevant information, performs planning, and generates a response — all through repeated neural inference.

Many of the limitations commonly attributed to language models may instead arise from this arrangement, not from the models themselves.

**Reconstructing working state.** Systems repeatedly ask a probabilistic model to reconstruct its own working state from conversational history. Working state becomes an inference byproduct rather than an explicitly managed resource. As conversations grow longer, reconstruction becomes more expensive and more susceptible to ambiguity, outdated assumptions, and accumulated error.

**Repeated context processing.** Conversation histories continually expand while much of their content becomes irrelevant to the current task. Repeatedly reconstructing state from growing history is architectural overhead independent of any particular model implementation.

**Context degradation.** Long conversations accumulate abandoned ideas, superseded assumptions, and corrected mistakes. These elements can continue influencing subsequent inference despite no longer representing the desired cognitive state — and recovering from this typically requires additional interactions whose sole purpose is correcting previous generations.

**Human productivity cost.** This is the part that matters most and is measured least. When bad state is committed silently, the user doesn't get pulled in for a quick confirmation — they get pulled in later, after the fact, to debug. That's expensive precisely because it's unstructured and delayed: the user has to first figure out *what* went wrong before they can even say the correction. Every unnecessary correction interrupts concentration, pollutes conversational history, and reduces productivity. The goal of a better architecture is not fewer questions to the user — it's moving the user's involvement from reactive debugging to a small, cheap, proactive confirmation, asked at the moment of uncertainty rather than several turns downstream.

### Architectural comparison

| Dimension | Monolithic LLM | Agentic Systems (patchwork) | Tiered Cognitive Architecture |
|---|---|---|---|
| Executive Control | Neural model | Neural planner | Executive Cognitive Kernel |
| Working Context | Replay history | Replay + retrieval | Compiled execution context |
| Persistent State | Conversation transcript | External memory, ad hoc | Versioned, typed state graph |
| Primary Reasoning | Neural inference | Neural inference | Specialised heterogeneous computation |
| System State | Ephemeral | Semi-persistent | Persistent, deterministic, auditable |
| Auditability | None | Inconsistent, per-framework | Structural — commit history is the audit trail |

---

## Part II — The Architecture

### Compute placement: two tiers, not three

At the infrastructure level, this is as much a workload-routing discipline as a software design. Most of what current systems route to large GPU-cluster inference is actually deterministic housekeeping — state lookups, conflict checks, routing decisions — that belongs on the CPU fleet, which is typically underutilized relative to the GPU cluster in the same facility. The architecture enforces that split rather than defaulting everything to the model because it's easier to prompt than to engineer a deterministic service.

The one place the kernel needs a model at all — interpreting ambiguous natural-language input — does **not** constitute a third tier. It's a small, narrow, purpose-built model living inside the kernel's own footprint, co-located with the CPU tier rather than the large GPU cluster, serving the kernel's own executive function. It never produces user-facing output and never writes state directly; it only ever proposes a diff that the deterministic core gates.

- **Tier One (kernel)** — deterministic core plus a small embedded model for bounded translation tasks
- **Tier Two (specialized computation)** — the large GPU cluster and other heavy engines, reserved for genuinely general-purpose or open-ended work, dispatched to by the kernel and never doing the kernel's own job

### Tier One: The Executive Cognitive Kernel

The Executive Cognitive Kernel is the persistent operating system of the architecture. Unlike today's stateless inference model, it maintains continuous cognitive state independently of any individual model invocation. Its responsibilities: maintaining persistent state; tracking goals and objectives; selecting relevant information; compiling execution contexts; dispatching specialized computation; integrating returned results; coordinating heterogeneous resources.

The kernel is deterministic in its decision logic — commit gate, merge policy, routing — even though one of its internal components uses a small model as a sensor, much as a deterministic control system can incorporate a noisy sensor without the controller itself ceasing to be a controller. The kernel owns and gates the model's output; the model doesn't own any part of the kernel's function.

**1. State model.** Persistent cognitive state is a small typed graph, not a document.

- *Entities* — goals, facts, preferences, open questions, projects. Each has an ID, a confidence score, a timestamp, provenance (which turn or call produced it), and a status (active / superseded / retracted).
- *Edges* — typed relationships: `supports`, `contradicts`, `supersedes`, `depends_on`. This makes drift and conflict detectable structurally, rather than something re-derived by re-reading history.
- *Versioning* — the state graph is a git-like history, not an append log. Every accepted change is a **commit**: an atomic diff against a known parent state.

This layer is fully deterministic: schema validation, conflict detection, storage, retrieval. No model involved.

**Three kinds of memory, not two.** The pipeline from language to state implicitly spans three distinct layers, and keeping them named separately avoids blurring them into one undifferentiated "context":

- *Long-term semantic state* — the state graph itself: persistent facts, goals, projects, preferences. Durable across the life of the relationship with the user or system, changed only through commits.
- *Working memory* — the current task's execution state: intermediate reasoning, scratchpad values, in-progress plans. Lives for the duration of a task, then is either promoted into long-term state (if durable) or discarded.
- *Ephemeral inference context* — the actual compiled payload sent to a Tier Two model for a single call. Reconstructed per call from the other two layers, then thrown away.

Conflating these — treating "what we send the model" as if it were the same thing as "what the system durably knows" — is exactly the blur that lets transcript replay masquerade as memory in current systems. Keeping them distinct is what makes the state graph authoritative rather than just another cache.

**[PATCH #1 INTEGRATED — State outlives models]**

> **State longevity:** A direct consequence of this separation is that the durable asset is not the model — it is the versioned cognitive state. Current systems preserve conversations. This architecture preserves knowledge. Conversation history becomes evidence; state becomes the canonical representation. As models improve, the same state graph can be reused without rebuilding conversations or replaying transcripts. Models become replaceable inference engines operating over a persistent substrate whose value compounds rather than resets with each generation. The state moves. The models do not.

**2. Git-like operations as first-class primitives.** Taking the repository analogy literally adds three native operations — validated in a working reference implementation, not just asserted as concepts:

- *Revert* — undo a bad commit by rolling state back to the last known-good commit, rather than manually unwinding everything built on top of it. Implemented as a real snapshot restore: every commit stores the resulting active-entity set, and revert restores from that snapshot rather than appending a no-op. Tested directly — a bad fact was committed, reverted, and confirmed absent from active state afterward, with entity counts returning exactly to their pre-commit value.
- *Branch* — when the ingestion pipeline is genuinely ambiguous between interpretations, the kernel doesn't have to force an immediate commit-or-ask decision. It holds both as parallel branches, proceeds on the higher-confidence one, and keeps the alternate available to switch to cheaply. This is a genuine third option between "commit" and "ask." (The reference implementation currently forks a shallow copy of active state per branch; a full forked commit chain remains future work.)
- *Diff* — any two versions of the state graph can be compared directly, giving a structured answer to "when did this change and why" instead of requiring a re-read of transcript history. Implemented against real commit snapshots rather than a placeholder count — tested to correctly report an added fact going forward and the same fact as removed after a revert.

**3. Ingestion pipeline (where language meets state).** This is the seam where translation from natural language to structured state happens — the hardest part, and the one that has to stay narrow:

1. *Segmentation* (deterministic) — split the turn into candidate statements, questions, instructions.
2. *Narrow classification/extraction* (the kernel's embedded model) — classify each candidate and extract structured slots, each with its own confidence score. Fixed schema, bounded output — not open-ended reasoning, and not a Tier Two workload.
3. *Merge check* (deterministic) — attempt a three-way merge of the proposed diff against current state. A strict, non-contradictory extension auto-merges. A genuine conflict blocks the commit pending resolution — the same semantics as a merge conflict in source control, not a silent overwrite.
4. *Commit gate* (deterministic policy) — decide: commit, branch, or escalate.

Stage 2 never writes state directly. It only ever produces a proposed diff; the kernel decides whether to apply it.

**4. The commit gate — the actual center of the design.** It is tempting to treat the state graph as the contribution here; graph memories, event sourcing, and CRDTs already exist elsewhere. What's genuinely novel is the control policy sitting in front of the graph: **commit, branch, or ask** as a triage decision, replacing today's binary of *guess silently* or *always interrupt*. That third option — branch — is what makes this richer than either alternative: it acknowledges that not every ambiguity is worth a user's attention, and lets the system defer resolution until it's actually needed rather than paying an interruption cost up front or a correctness cost later. Rather than a fixed confidence cutoff, the gate weighs expected cost:

```
expected_cost(commit)  = P(wrong) × cost_of_late_correction
expected_cost(branch)  = cost_of_maintaining_parallel_state
expected_cost(ask)     = cost_of_one_question + fatigue_term(ask_frequency)
```

`cost_of_late_correction` is weighted heavily, since a wrong fact compounds by seeding further wrong inferences before it's caught — though atomic commits keep this cost lower than it would otherwise be, since the fix is a revert rather than a manual unwind. `branch` is the genuine middle option when ambiguity is real but neither guessing nor interrupting is clearly cheaper. `fatigue_term` guards against over-asking, which has its own real cost: users who are interrupted too often start reflexively confirming without reading, defeating the purpose.

Escalation, when it happens, must be cheap by construction: closed-form questions, not open-ended ones; batched per turn, not one interruption per fact; default-and-confirm where a good guess exists. Even confident, auto-committed changes should be lightly surfaced, not silent — a passing-glance receipt costs nothing but catches misplaced confidence before it propagates. Timing matters as much as accuracy: the check happens at ingestion, synchronous with the turn, while the user still holds full context and correction is nearly free.

**5. Context compilation.** The kernel does not replay conversations — it compiles context. A static, hand-authored mapping from task type to a fixed field list ("coding task pulls active project + recent decisions + open questions") is fragile: it retrieves what someone anticipated at design time, and silently omits anything relevant that the template's author didn't foresee — a dependency two hops away in the graph, connected by a relationship nobody wrote a rule for. That's a correctness failure, not just a cost problem, and it's distinct from every other failure mode in this design: nothing errors, the payload just quietly lacks something it needed.

The fix is to use the graph structure the kernel already maintains, rather than a flat field list:

1. *Anchor* — deterministically identify the entities directly relevant to the task (the active project, the stated goal).
2. *Traverse* — walk outward from the anchors along the typed edges already defined in the state model (`supports`, `contradicts`, `supersedes`, `depends_on`) to a bounded depth, rather than pulling a fixed list keyed on task type. A dependency two hops away surfaces automatically because the relationship is already encoded in the graph, not because a template author thought to include it.
3. *Bound* — cap the traversal by depth and payload size, preserving the same cost control as before: the payload stays size-capped, just bounded by traversal radius instead of a static field list. This is still a fully deterministic graph query, not a model judging relevance.

Traversal reduces the miss rate but won't eliminate it, so pair it with cheap, after-the-fact detection rather than relying on prevention alone: if a Tier Two response references an entity connected to the compiled payload's anchors but not included in it, that's a structural signal the traversal under-fetched — log it. The clearest signal of all is a user correction on a fact that already existed in the state graph but simply wasn't retrieved: that's a compilation miss, not an ingestion miss, and should feed back into recalibrating traversal depth and budget per task type — the same closed-loop discipline the ingestion classifier needs, applied to retrieval instead of extraction.

**6. Dispatch.** A deterministic routing table maps task type to which Tier Two engine(s) get called. This is the boundary where work actually leaves the kernel's own footprint for the large-scale specialized compute layer — the embedded ingestion model never appears here, since it's internal to Tier One, not something the kernel dispatches to. Start as a plain lookup table; only promote entries to a learned router once failure data justifies it, since a large router model just re-creates the monolith one layer up.

### Tier Two: Specialized Computation Layer

Tier Two consists of heterogeneous resources optimized for different classes of computation, invoked only when a task genuinely requires them. The routing criterion, in principle, is not the task's surface-level type but whether **a deterministic procedure exists that can be verified correct independent of a model's judgment**. Where one exists, the task belongs there; where none exists, it stays with neural inference.

**[Content unchanged from your current doc for brevity — see original]**

### Deployment: Tier Two as a driver interface, not a datacenter design

[Content unchanged — your driver contract section is strong as-is]

---

## Part III — Why Now

Three forces are converging that make this the right moment to build this, not merely an interesting one:

**Energy is now the hard constraint.** Power draw and grid interconnect delays are gating datacenter buildout speed industry-wide. This architecture is one of the few levers that helps immediately, because it requires no new fabs or power plants — it's a routing discipline applied to compute that already exists. Deterministic housekeeping currently running on GPU clusters moves to the CPU tier, where it belongs, freeing real GPU headroom without adding a single chip.

**Capital scrutiny is real and immediate.** IPOs and public-market attention mean unit economics — cost per inference, GPU utilization, idle capacity — get audited in a way they weren't when this was private, venture-funded experimentation. Cost discipline is no longer an unglamorous afterthought; it's a number analysts will ask about directly.

**This is not a tradeoff against bigger models — it's what makes them pay off.** A frontier model running under this kernel isn't also asked to be an operating system: reconstructing state, tracking its own prior decisions, compensating for a polluted context. It spends its entire compute budget on what it's actually for. Every dollar invested in scaling the model converts more fully into capability, instead of a growing share going toward the model doing a job it was never the right substrate for. The kernel is what gives scaling headroom rather than competing with it.

**[PATCH #2 INTEGRATED — Efficiency is not the real win]**

> **Beyond efficiency:** Reduced token usage is valuable, but the larger contribution is the separation of persistent cognition from probabilistic inference. That distinction remains valuable even if future models have effectively unlimited context windows and near-zero inference cost. Unlimited transcript replay still reconstructs state, still accumulates abandoned ideas, and still lacks auditability. Efficiency is the near-term wedge; separation is the durable architectural claim.

### Why this unlocks adoption, not just efficiency

[Remainder of Part III unchanged — trust/audit trail argument is strong]

---

## Part IV — Open Questions and Risks

This is an architectural research agenda, not a completed implementation. Key open questions, both empirical and engineering:

- Does compiled execution context reduce inference cost in practice, and by how much relative to the overhead of maintaining the state graph itself?
- Does structured, versioned state measurably improve long-horizon coherence relative to transcript replay?
- **Confidence calibration drift** — narrow extractors' confidence scores need periodic recalibration against ground truth, or the commit gate quietly degrades.
- **Traversal calibration** — bounded graph traversal reduces but doesn't eliminate incomplete context compilation; the miss-detection signal (Tier Two referencing an unfetched but connected entity, or a user correcting a fact that was already in state but not retrieved) needs to actually close the loop into adjusted traversal depth/budget, or misses will recur silently.
- **Merge resolution policy** — auto-merging non-contradictory extensions is straightforward; genuine conflicts usually shouldn't resolve automatically and should escalate or branch rather than let the kernel guess.
- **Branch lifecycle policy** — left unmanaged, branches accumulate and recreate the same drift this architecture exists to prevent, just relocated into the graph. A minimum default: time-based decay (a branch unresolved after N turns auto-collapses to the higher-confidence side), task-bound expiry (a branch dies when the task that created it completes), and a hard cap (e.g. three active branches per anchor entity, forcing resolution before a fourth opens).
- **Schema evolution** — rather than a future migration problem, every entity should carry an `extensions` field (a typed map) from the first version, with schema validation per type version, and every commit should record the schema version it was written against. Migrating live state after the fact is where systems like this tend to fail; designing for extension from day one is cheap insurance against it.
- What execution-dispatch strategies provide the best trade-off between latency and capability, and when (if ever) does a learned router outperform a deterministic lookup table?
- **Multi-resource dispatch order** — start with a simple deterministic state machine per task class (retrieval → solver → generation, with explicit transitions for failure — does a failed solver step trigger re-retrieval, does a generation step that violates a known constraint trigger a loop back), defined alongside the routing table rather than left to a general planner. Promote to a learned router only once failure logs justify it, following the same discipline as dispatch itself.
- **Domain classification for expert-system routing** — deciding whether a task belongs to a regulated domain (legal, medical) is a higher-stakes version of the same judgment-call problem as general ingestion classification. Whether it needs its own dedicated classifier, its own confidence thresholds, or can reuse the existing ingestion pipeline is an open design question.

These are empirical questions and should be evaluated experimentally, not assumed.

### Experimental validation

Each hypothesis above needs a baseline and a metric, not just a claim. A concrete evaluation methodology, testable against current systems:

| Hypothesis | Baseline | Metric |
|---|---|---|
| Compiled context reduces inference cost | Transcript replay | Tokens processed, GPU time, latency |
| Versioned state improves coherence | Standard chat memory | Contradiction rate, recovery time after correction |
| Commit gate reduces user effort | Auto-commit memory | Corrections per task, clarification-request rate, task completion time |
| CPU/GPU separation improves utilization | Monolithic orchestration | GPU utilization, CPU utilization, cost per completed task |
| Auditability improves traceability | Agent framework (ad hoc memory) | Time to identify the source of an incorrect decision |
| **[PATCH #3 INTEGRATED — Litmus test for true separation]** State graph outlives model | Same state graph loaded into next-gen model | Zero-shot task success without transcript replay — can the exact same state graph be loaded into a substantially better model years later and immediately benefit from improved reasoning? |

Note the human-productivity metrics in particular — corrections per task, downstream correction latency, time-to-recover from a bad assumption — since these are arguably better fits for this architecture's actual claims than throughput metrics like perplexity or raw token efficiency. The core argument of this proposal is about debugging cost, not just compute cost, and the evaluation methodology should measure what the proposal actually claims to fix.

---

## Part V — What to Build First

[Your current Part V is good as-is — keep thresholds and honesty notes exactly as written. Those two discoveries (cost-constant sensitivity + length bias) are evidence of empirical evolution, which is ChatGPT idea #10]

---

## Conclusion

[Unchanged from your current doc]
