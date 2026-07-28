# A Tiered Cognitive Architecture for AI Systems

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

**2. Git-like operations as first-class primitives.** Taking the repository analogy literally adds three native operations:

- *Revert* — undo a bad commit by rolling state back to the last known-good commit and replaying forward, rather than manually unwinding everything built on top of it. This is the direct fix for cascading errors: catching something late no longer means reconstructing what should have happened, it means checking out an earlier state.
- *Branch* — when the ingestion pipeline is genuinely ambiguous between interpretations, the kernel doesn't have to force an immediate commit-or-ask decision. It holds both as parallel branches, proceeds on the higher-confidence one, and keeps the alternate available to switch to cheaply. This is a genuine third option between "commit" and "ask."
- *Diff* — any two versions of the state graph can be compared directly, giving a structured answer to "when did this change and why" instead of requiring a re-read of transcript history. This is the debugging and audit tool for the rare cases something does go wrong.

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

Tier Two consists of heterogeneous resources optimized for different classes of computation, invoked only when a task genuinely requires them. The routing criterion, in principle, is not the task's surface-level type but whether **a deterministic procedure exists that can be verified correct independent of a model's judgment**. Where one exists, the task belongs there; where none exists, it stays with neural inference. What follows is a working inventory of resource categories, grouped by why each is worth routing to rather than left to a model to approximate.

**Deterministic, formally verifiable procedures** — no reason to make a model guess at these:
- *Arithmetic and symbolic math* — algebraic, statistical, and numerical computation, computed exactly rather than estimated.
- *Constraint satisfaction / SAT / SMT solvers* — scheduling, resource allocation, "does a valid assignment exist given these rules," using mature solvers that can prove satisfiability rather than reason toward it step by step.
- *Formal logic / theorem proving* — verifying that a set of statements is internally consistent, or that a conclusion follows from stated premises. Directly relevant to the kernel's own merge-conflict logic — "does fact B contradict fact A" is sometimes itself a small logic problem, not just a lookup.
- *Graph algorithms* — shortest path, reachability, cycle detection, topological sort. Well-known exact algorithms, and a natural fit given the state graph is already graph-shaped.
- *Digital signal processing* — audio, image, video, and sensor-stream processing (filtering, transforms, compression), using well-defined mathematical transformations (FFTs, convolutions, wavelets) with known, exact algorithms. Often backed by genuinely specialized hardware — DSP chips and signal-tuned FPGAs are a real, decades-old hardware category distinct from both general CPUs and GPUs. Worth noting: DSP work sometimes sits *upstream* of the kernel's language-based ingestion pipeline, not just alongside it as a dispatch target — raw audio or sensor input often needs deterministic preprocessing before it's in a form the ingestion pipeline can classify at all, meaning not every input starts as language.

**Search, optimization, and simulation** — problems with a cost function or state space, not a language problem:
- *Combinatorial optimization / operations research solvers* — route planning, packing, scheduling under constraints with a cost to minimize, not just a feasibility check.
- *Search algorithms over structured spaces* — A*, Monte Carlo tree search, and similar, for problems with defined state spaces and transition rules.
- *Simulation engines* — physics, discrete-event, or Monte Carlo simulation for "what would happen if" questions, as distinct from "what does the language imply."

**Retrieval and indexing** — lookup problems, not reasoning problems:
- *Vector similarity search* — finding semantically similar but structurally unconnected material, distinct from the typed-edge graph traversal used for context compilation; both are legitimate tools for different jobs.
- *Full-text / structured query engines* — traditional database queries when the task is genuinely just "look this up."

**Domain expert systems** — a distinct middle category, not fully deterministic in the DSP/solver sense but far more rule-governed than open-ended generation: codified professional knowledge such as statutory logic, clinical guidelines, drug-interaction tables, actuarial tables, or tax code. These are better served by a maintained, versioned rules engine or certified decision-support system than by a general model improvising from training data — which is exactly the hallucination risk that makes regulated industries distrust general inference for this kind of question in the first place. Routing to a domain engine requires its own classification step (is this task legal, medical, or otherwise domain-specific), handled the same way as any other uncertain judgment call in this architecture — a confidence-gated proposal from the narrow classifier, escalating when unclear, rather than a silent guess. The payoff is concrete: when a decision touches a regulated domain, the audit trail shows exactly which certified engine handled it, under which version and ruleset — not "a language model inferred something."

**Neural inference** — still the right tool where no deterministic procedure exists: open-ended generation, synthesis, style, creative work, and the ambiguous natural-language judgment calls the ingestion classifier itself performs.

The architecture is intentionally hardware-agnostic, organized around computational specialization rather than particular technologies. Persistent knowledge — semantic graphs, structured key-value state, relational stores, vector indices where appropriate — is owned by the kernel; Tier Two engines consume it but do not own it.

Not every task requires full orchestration: simple conversational requests may be dispatched directly to a neural inference engine, while complex tasks assemble combinations of retrieval, symbolic verification, optimization, planning, simulation, and neural synthesis as the kernel determines. The precise decision procedure for multi-resource tasks — sequential, parallel, or conditional dispatch — remains an open design question, noted in Part IV.

### Deployment: Tier Two as a driver interface, not a datacenter design

The kernel is an operating system. A real operating system kernel doesn't hand-implement behavior for every disk controller or network card on the market — it defines a **driver interface**: a fixed contract of what any given hardware or backend must expose, and lets a vendor- or platform-specific driver handle the messy reality underneath. Tier Two dispatch works the same way. The architecture defines the contract; how a *particular* deployment satisfies it is a driver's job, not the kernel's.

This is a deliberate scope boundary, not an omission. Everything about how a specific inference stack batches requests, caches state, disaggregates prefill from decode, or offloads memory is platform-specific detail that belongs inside a driver implementation — it should never need to be re-litigated in the kernel's design just because the deployment target changes. The same kernel — same state graph, same commit gate, same context compilation — should sit as comfortably in front of a large distributed GPU cluster as in front of a single local model running on a home machine talking to one user with no batching and no distributed anything at all. If the architecture only makes sense assuming one specific deployment shape, it isn't a kernel design — it's that deployment's design wearing a kernel's name. Working for both is the actual test of whether the abstraction is at the right level.

**The driver contract, at minimum, needs to define:**

- How a compiled payload (the kernel's stable-state/volatile-task-context structure) is handed to the backend for execution.
- What the driver reports back — did it hit a cache, how long did execution take, did anything need to be evicted — so the kernel can adapt its own behavior without needing to know *why* a particular backend behaves the way it does.
- What latency and consistency guarantees the kernel can assume from any driver, at minimum, so dispatch and scheduling logic can be written once against the contract rather than once per backend.
- How a driver signals its own capacity or backpressure, so the kernel doesn't assume unlimited throughput from something that may be a single shared machine.

**Everything from the earlier datacenter-specific discussion still matters — just relocated.** Prefix-cache compatibility (structuring durable state so it's addressable by a stable key, letting cache invalidation track real state changes rather than arbitrary re-serialization), batching-latency consistency, disaggregated prefill/decode alignment, KV-offload interaction, and shard/partition strategy for the state graph are all real considerations — but they're properties a *specific driver* needs to get right for its specific backend, not properties the kernel's own design needs to solve in the abstract. A datacenter driver and a home-machine driver will satisfy the same contract very differently, and that's exactly the point: the kernel doesn't need to know which one it's talking to.

### Anticipated objections

**"This is just event sourcing / CQRS / a knowledge graph / an operating system."** None of these comparisons are wrong individually, and none of them are the point. The proposal isn't inventing version control, graph storage, or workload scheduling — all of that exists. The claim is the synthesis: *version control should become the cognitive substrate beneath inference*, with a commit gate that treats language-derived facts the way source control treats code changes — attributable, reversible, mergeable — and with the language model demoted from manager to worker, dispatched by that substrate rather than running it. Individually familiar components, combined this way, are what's uncommon.

**"Isn't the kernel just another bottleneck?"** No, for a specific reason: nearly all of the kernel's operations are deterministic graph queries, merges, indexing, and scheduling — not GPU inference. That class of workload scales horizontally the way databases and schedulers already do in production systems today. The bottleneck risk in current architectures is the opposite: forcing housekeeping work through a shared, contended, expensive GPU pool. Moving that work to commodity deterministic infrastructure relieves a bottleneck rather than creating one.

### Translation and trade-offs

Separating executive cognition from inference does not eliminate probabilistic judgment — it contains it. Translating human language into structured state is imperfect, and the ingestion pipeline's narrow classifier is where that imperfection lives. Rather than assuming perfect interpretation, the kernel evaluates confidence and blocks or escalates before committing changes it isn't confident about.

Front-loaded context compilation and ingestion classification introduce their own overhead. The hypothesis is that this overhead is repaid many times over by eliminating repeated inference cycles, unnecessary computation, repeated user corrections, and long-term conversational drift — but this, like the compilation strategy itself, is an empirical claim requiring validation, not a given.

---

## Part III — Why Now

Three forces are converging that make this the right moment to build this, not merely an interesting one:

**Energy is now the hard constraint.** Power draw and grid interconnect delays are gating datacenter buildout speed industry-wide. This architecture is one of the few levers that helps immediately, because it requires no new fabs or power plants — it's a routing discipline applied to compute that already exists. Deterministic housekeeping currently running on GPU clusters moves to the CPU tier, where it belongs, freeing real GPU headroom without adding a single chip.

**Capital scrutiny is real and immediate.** IPOs and public-market attention mean unit economics — cost per inference, GPU utilization, idle capacity — get audited in a way they weren't when this was private, venture-funded experimentation. Cost discipline is no longer an unglamorous afterthought; it's a number analysts will ask about directly.

**This is not a tradeoff against bigger models — it's what makes them pay off.** A frontier model running under this kernel isn't also asked to be an operating system: reconstructing state, tracking its own prior decisions, compensating for a polluted context. It spends its entire compute budget on what it's actually for. Every dollar invested in scaling the model converts more fully into capability, instead of a growing share going toward the model doing a job it was never the right substrate for. The kernel is what gives scaling headroom rather than competing with it.

### Why this unlocks adoption, not just efficiency

The deeper unlock is trust, not cost.

Entire categories of enterprise use — healthcare, finance, legal, anything under real regulatory scrutiny — cannot adopt LLM-based systems for decision-critical work today, not because the models aren't capable, but because there is no way to produce what a regulator or auditor actually requires: a reconstructable account of what the system believed, when that belief was formed, what it was based on, and proof nothing was silently altered along the way.

A conversation transcript is not that. A wrapper's ad hoc memory is not that. "The model said so" is not an audit trail — it's a liability.

The kernel produces the audit trail as a structural byproduct of how it works, not as a compliance feature bolted on afterward: every state change is an atomic, attributable commit; contradictions are detected structurally instead of silently absorbed; nothing enters persistent state without passing a deterministic, inspectable gate. Diff and revert aren't conveniences here — they are literally what "show me what changed, when, why, and prove it's reversible" means in a regulated context. This cannot be retrofitted onto a patchwork of agents after the fact; it has to be true of the state layer from the start.

And once it's a real substrate — a standard, not one team's convention — it stops being a patchwork of individually clever agents and becomes something other systems can build against. That is the difference between an interesting architecture and infrastructure real applications get built on: an ecosystem, not a pile of incompatible one-offs. That is the precondition for the industries currently locked out to say yes.

### An ecosystem, not a framework

The driver interface (see Part II) isn't just an implementation convenience — it's what makes durable third-party investment possible in a way today's agent landscape doesn't. Right now, a legal-tech or medical-device company that wants to plug domain expertise into an LLM system has nothing stable to build against — they'd be integrating against one team's bespoke agent framework, which can change under them at any time, is uncertified, and isn't auditable in a way their own regulators would accept. There's no foundation, so nobody commits serious engineering — let alone silicon — investment on top of it.

A fixed driver contract changes that calculation. If the interface is published and stable — what a payload looks like going in, what's expected coming back out, how versioning and audit trail work — a domain expert or hardware vendor can build against a stable target with the same confidence a peripheral manufacturer has building a driver for an operating system: they aren't betting on one company's product roadmap, they're building against a published interface. That's what justifies real capital investment — a certified legal-reasoning engine, a clinical-decision-support system, an ASIC tuned for medical image analysis — sold as pluggable, independently audited add-ons rather than another prompt-engineered wrapper.

This is also the sharpest form of the strategic argument for building this first: the advantage isn't just a faster or cheaper system, it's **defining the interface everyone else builds against.** That's a more durable position than winning on model quality alone, because it compounds as third parties commit their own capital to the ecosystem — an advantage a competitor can't erase just by shipping a marginally better model next quarter.

---

## Part IV — Open Questions and Risks

This is an architectural research agenda, not a completed implementation. Key open questions, both empirical and engineering:

- Does compiled execution context reduce inference cost in practice, and by how much relative to the overhead of maintaining the state graph itself?
- Does structured, versioned state measurably improve long-horizon coherence relative to transcript replay?
- **Confidence calibration drift** — narrow extractors' confidence scores need periodic recalibration against ground truth, or the commit gate quietly degrades.
- **Traversal calibration** — bounded graph traversal reduces but doesn't eliminate incomplete context compilation; the miss-detection signal (Tier Two referencing an unfetched but connected entity, or a user correcting a fact that was already in state but not retrieved) needs to actually close the loop into adjusted traversal depth/budget, or misses will recur silently.
- **Merge resolution policy** — auto-merging non-contradictory extensions is straightforward; genuine conflicts usually shouldn't resolve automatically and should escalate or branch rather than let the kernel guess.
- **Branch lifecycle management** — parallel branches can't accumulate indefinitely; the design needs a policy for when an unresolved branch gets forced to a decision (time-based, task-based, or explicit user resolution).
- **Schema evolution** — state schema should be extensible (typed/tagged properties) from the start, since new entity or relationship types will be needed and migrating live state is otherwise costly.
- What execution-dispatch strategies provide the best trade-off between latency and capability, and when (if ever) does a learned router outperform a deterministic lookup table?
- **Multi-resource dispatch order** — when a task needs more than one Tier Two resource (e.g. verification then generation, or several in parallel with merged results), what determines the sequencing — fixed per task type, conditional on intermediate results, or something else? Currently unspecified.
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

Note the human-productivity metrics in particular — corrections per task, downstream correction latency, time-to-recover from a bad assumption — since these are arguably better fits for this architecture's actual claims than throughput metrics like perplexity or raw token efficiency. The core argument of this proposal is about debugging cost, not just compute cost, and the evaluation methodology should measure what the proposal actually claims to fix.

---

## Conclusion

The history of AI has focused on building increasingly capable models. This proposal is about building the cognitive system around them — one where working state is an explicitly managed architectural resource with the discipline of an operating system, not an emergent byproduct of repeated neural inference, and not another ad hoc layer improvised per application.

Every component required — versioned graph state, deterministic services, small embedded classifiers, workload-aware scheduling — is buildable with technology that already exists. What's missing is the discipline to build it as one coherent system rather than another wrapper, and the recognition that this is infrastructure, not a feature.

The industry is racing on one axis: bigger models. The open ground is the other axis: the operating system underneath them, and the auditability that comes from doing it properly. Whoever builds it first gets a durable advantage that isn't easily copied by adding more GPUs — lower cost per task, less waste, and the trust that turns an impressive demo into a system a regulated enterprise can actually run.
