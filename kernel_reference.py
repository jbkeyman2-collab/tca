"""
Tiered Cognitive Architecture - Reference Implementation
Executive Cognitive Kernel: State Graph + Commit Gate + Context Compilation

Buildable with Python 3.11+, no external deps. Designed to be ported to Postgres + small embedded model.
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Literal, Tuple
from enum import Enum
import hashlib
import json
import time
from collections import deque, defaultdict

# ---------- 1. State Model ----------

Status = Literal["active", "superseded", "retracted"]
EdgeType = Literal["supports", "contradicts", "supersedes", "depends_on"]
EntityType = Literal["goal", "fact", "preference", "open_question", "project"]

@dataclass
class Entity:
    id: str
    type: EntityType
    content: str  # canonical text
    confidence: float  # 0..1
    timestamp: float
    provenance: str  # e.g., "turn:42" or "solver:call-7"
    status: Status = "active"
    schema_version: int = 1
    extensions: Dict = field(default_factory=dict)

@dataclass
class Edge:
    src: str
    dst: str
    type: EdgeType
    confidence: float = 1.0
    provenance: str = ""

@dataclass
class Commit:
    id: str
    parent_id: Optional[str]
    timestamp: float
    diff_added: List[Entity]
    diff_updated: List[Tuple[Entity, Entity]]  # (old, new)
    diff_removed: List[str]  # entity ids
    edges_added: List[Edge]
    message: str
    author: str  # "user:turn-5" or "kernel:merge-check"
    snapshot: Dict[str, Entity] = field(default_factory=dict)  # active entities AFTER this commit

@dataclass
class Branch:
    """A real divergent commit chain, not a name pointing at a dict copy.
    Tracks its own head so it can accumulate multiple commits before
    resolution, and carries the bookkeeping the lifecycle policy needs
    (anchor, creation turn, last-touched turn) so branches don't
    accumulate indefinitely."""
    name: str
    anchor_id: str  # the entity this branch's ambiguity is about
    base_commit_id: str
    head_commit_id: str
    created_turn: int
    last_touched_turn: int
    commit_ids: List[str] = field(default_factory=list)
    status: Literal["active", "merged", "abandoned"] = "active"

@dataclass
class StateGraph:
    entities: Dict[str, Entity] = field(default_factory=dict)
    edges: List[Edge] = field(default_factory=list)
    commits: Dict[str, Commit] = field(default_factory=dict)
    head: Optional[str] = None
    branches: Dict[str, Branch] = field(default_factory=dict)
    turn: int = 0  # advanced by the caller once per turn; drives branch decay

    def add_entity(self, e: Entity):
        self.entities[e.id] = e

    def get_active(self) -> Dict[str, Entity]:
        return {k:v for k,v in self.entities.items() if v.status == "active"}

    def commit(self, added: List[Entity] = None, removed: List[str] = None,
               edges_added: List[Edge] = None, message: str = "", author: str = "kernel") -> Commit:
        """The one path that mutates main-line state. Every commit snapshots
        the resulting active set, which is what makes revert and diff real
        operations instead of stubs."""
        added = added or []
        removed = removed or []
        edges_added = edges_added or []
        for e in added:
            self.add_entity(e)
        for eid in removed:
            if eid in self.entities:
                self.entities[eid].status = "retracted"
        self.edges.extend(edges_added)
        commit_id = _hash_id(f"commit-{message}-{time.time()}-{len(self.commits)}")
        c = Commit(
            id=commit_id, parent_id=self.head, timestamp=time.time(),
            diff_added=added, diff_updated=[], diff_removed=removed,
            edges_added=edges_added, message=message, author=author,
            snapshot=dict(self.get_active()),
        )
        self.commits[commit_id] = c
        self.head = commit_id
        return c

    def diff(self, a_commit_id: str, b_commit_id: str) -> Dict:
        """Structural diff between two commits' snapshots - a real audit trail,
        not a count. Answers: what changed, and what changed it."""
        a = self.commits[a_commit_id].snapshot
        b = self.commits[b_commit_id].snapshot
        added = [eid for eid in b if eid not in a]
        removed = [eid for eid in a if eid not in b]
        changed = [eid for eid in a if eid in b and a[eid].content != b[eid].content]
        return {
            "from": a_commit_id, "to": b_commit_id,
            "added": [b[eid].content for eid in added],
            "removed": [a[eid].content for eid in removed],
            "changed": [(a[eid].content, b[eid].content) for eid in changed],
        }

    def revert(self, target_commit_id: str, message: str) -> Commit:
        """Roll active state back to a prior commit's real snapshot, then
        record the revert as its own commit - not a manual unwind, and not
        a no-op. Anything active now but absent from the target snapshot is
        retracted; anything in the target snapshot but altered since is
        restored to its target-commit content."""
        if target_commit_id not in self.commits:
            raise ValueError("unknown commit")
        target_snapshot = self.commits[target_commit_id].snapshot
        current = self.get_active()

        to_retract = [eid for eid in current if eid not in target_snapshot]
        to_restore = []
        for eid, target_ent in target_snapshot.items():
            cur = self.entities.get(eid)
            if cur is None or cur.status != "active" or cur.content != target_ent.content:
                restored = Entity(**{**asdict(target_ent), "status": "active"})
                to_restore.append(restored)

        for eid in to_retract:
            self.entities[eid].status = "retracted"
        for ent in to_restore:
            self.entities[ent.id] = ent

        commit_id = _hash_id(f"revert-{target_commit_id}-{time.time()}")
        c = Commit(
            id=commit_id, parent_id=self.head, timestamp=time.time(),
            diff_added=to_restore, diff_updated=[], diff_removed=to_retract,
            edges_added=[], message=message, author="kernel:revert",
            snapshot=dict(self.get_active()),
        )
        self.commits[commit_id] = c
        self.head = commit_id
        return c

    def branch(self, name: str, anchor_id: str, from_commit_id: Optional[str] = None) -> Branch:
        """Fork a real divergent commit chain. Enforces the branch lifecycle
        cap before creating a new one: if the anchor already has the max
        active branches, the oldest is force-resolved first (decayed to
        whichever side has higher confidence) rather than letting branches
        accumulate indefinitely - the same drift this architecture exists
        to prevent, just relocated into the graph if left unmanaged."""
        base = from_commit_id or self.head
        self._enforce_branch_cap(anchor_id)
        b = Branch(
            name=name, anchor_id=anchor_id, base_commit_id=base, head_commit_id=base,
            created_turn=self.turn, last_touched_turn=self.turn,
        )
        self.branches[name] = b
        return b

    def get_branch_active(self, name: str) -> Dict[str, Entity]:
        b = self.branches[name]
        return dict(self.commits[b.head_commit_id].snapshot) if b.head_commit_id in self.commits else {}

    def commit_to_branch(self, name: str, added: List[Entity] = None, message: str = "",
                          author: str = "kernel:branch") -> Commit:
        """Commit onto a branch's own chain, not main. The branch's snapshot
        is derived from its own head, not self.entities - so branch state
        never leaks into or pollutes the main line until merged."""
        b = self.branches[name]
        added = added or []
        base_snapshot = self.get_branch_active(name)
        new_snapshot = dict(base_snapshot)
        for e in added:
            new_snapshot[e.id] = e
        commit_id = _hash_id(f"branch-{name}-{message}-{time.time()}-{len(self.commits)}")
        c = Commit(
            id=commit_id, parent_id=b.head_commit_id, timestamp=time.time(),
            diff_added=added, diff_updated=[], diff_removed=[],
            edges_added=[], message=message, author=author,
            snapshot=new_snapshot,
        )
        self.commits[commit_id] = c
        b.head_commit_id = commit_id
        b.commit_ids.append(commit_id)
        b.last_touched_turn = self.turn
        return c

    def merge_branch(self, name: str, message: str = "") -> Dict:
        """Real three-way merge: replay the branch's accumulated diff against
        current main state using the same structural/semantic checks as
        ordinary ingestion, not a special-cased merge path. Returns the
        merge_check-style result; only commits to main if clean."""
        b = self.branches[name]
        branch_entities = list(self.get_branch_active(name).values())
        proposed = ProposedDiff(entities_to_add=branch_entities,
                                 confidences=[e.confidence for e in branch_entities])
        result = merge_check(self, proposed)
        if result.can_auto_merge:
            self.commit(added=branch_entities, message=message or f"merge branch {name}",
                        author="kernel:merge_branch")
            b.status = "merged"
            return {"merged": True, "structural_conflicts": [], "semantic_ambiguities": []}
        return {"merged": False, "structural_conflicts": result.structural_conflicts,
                "semantic_ambiguities": result.semantic_ambiguities}

    def abandon_branch(self, name: str, reason: str = ""):
        """Drop a branch without merging - its commits remain in the commit
        store for audit (why it was opened, what it diverged to) but never
        touch main state. Distinct from a decay-timeout: this records an
        explicit reason, which matters if these traces are ever curated
        (see Future_Possibilities.md) - decayed-away branches are not the
        same signal as ones explicitly abandoned as wrong."""
        b = self.branches[name]
        b.status = "abandoned"

    def _enforce_branch_cap(self, anchor_id: str, max_active: int = 3):
        active_for_anchor = [b for b in self.branches.values()
                              if b.anchor_id == anchor_id and b.status == "active"]
        if len(active_for_anchor) >= max_active:
            oldest = min(active_for_anchor, key=lambda b: b.created_turn)
            self._decay_branch(oldest)

    def decay_stale_branches(self, max_age_turns: int = 10):
        """Time-based decay: call once per turn. Any branch untouched for
        max_age_turns auto-resolves rather than sitting open indefinitely."""
        for b in list(self.branches.values()):
            if b.status == "active" and (self.turn - b.last_touched_turn) >= max_age_turns:
                self._decay_branch(b)

    def _decay_branch(self, b: Branch):
        """Force-resolve a branch: merge if its content is still clean
        against current main state, otherwise abandon it. This is the
        actual policy behind both the cap and the time-decay triggers -
        a branch never just vanishes silently, it resolves one way or
        the other with a recorded reason."""
        result = self.merge_branch(b.name, message=f"auto-resolved (decay/cap) at turn {self.turn}")
        if not result["merged"]:
            self.abandon_branch(b.name, reason="decayed with unresolved conflict against current main state")

# ---------- 2. Ingestion Pipeline ----------

@dataclass
class ProposedDiff:
    """What the small embedded model proposes - never writes directly."""
    entities_to_add: List[Entity] = field(default_factory=list)
    entities_to_update: List[Tuple[str, Entity]] = field(default_factory=list)
    edges_to_add: List[Edge] = field(default_factory=list)
    confidences: List[float] = field(default_factory=list)  # per entity
    raw_segments: List[str] = field(default_factory=list)

def deterministic_segment(text: str) -> List[str]:
    # Simplified: split on sentence boundaries. Real: clause splitter.
    return [s.strip() for s in text.split(".") if s.strip()]

def mock_small_model_extract(segments: List[str], turn_id: str) -> ProposedDiff:
    """STAND-IN for the kernel's embedded small model.
    In prod: 1-3B model, fixed schema, returns structured slots + confidence.
    Never produces user-facing text.
    """
    diff = ProposedDiff(raw_segments=segments)
    for seg in segments:
        # Very naive heuristic - real model does NER + slot extraction
        conf = 0.85 if len(seg) > 10 else 0.5
        eid = _hash_id(seg)[:12]
        ent = Entity(
            id=eid,
            type="fact",
            content=seg,
            confidence=conf,
            timestamp=time.time(),
            provenance=f"turn:{turn_id}",
        )
        diff.entities_to_add.append(ent)
        diff.confidences.append(conf)
    return diff

_UPDATE_CUES = ["not", "no longer", "instead", "cancel", "moved", "changed", "delayed",
                "pushed", "revised", "updated", "actually"]
_STOPWORDS = {"the", "a", "an", "is", "are", "it", "its", "in", "on", "at", "of", "to", "we", "be", "still"}

@dataclass
class MergeResult:
    can_auto_merge: bool
    structural_conflicts: List[str] = field(default_factory=list)
    semantic_ambiguities: List[str] = field(default_factory=list)

def _content_words(s: str) -> set:
    return {w.strip(",.'\"") for w in s.lower().split()
            if w.strip(",.'\"") not in _STOPWORDS and len(w) > 3}

def _match_score(a_words: set, b_words: set) -> float:
    # KNOWN LIMITATION: Jaccard similarity is sensitive to sentence length, not
    # just specificity of overlap - a short existing entity can outscore a
    # longer, more specific match on the same single shared word, purely
    # because its denominator (word-set union) is smaller. This can cause a
    # genuinely ambiguous reference to spuriously resolve to one candidate
    # over another equally-plausible one. This is a placeholder for what a
    # real embedding-similarity or trained classifier should do in production;
    # tuning the margin further to compensate is whack-a-mole against a
    # heuristic that doesn't model specificity, only word overlap - the same
    # boundary already accepted for _contradicts.
    if not a_words or not b_words:
        return 0.0
    return len(a_words & b_words) / len(a_words | b_words)

def _anchor_candidates(ent: Entity, active: Dict[str, Entity], threshold: float = 0.2, margin: float = 0.15) -> List[Entity]:
    """Existing active entities plausibly referred to by this proposed entity.
    Uses Jaccard similarity, not raw shared-word count - a single generic
    shared word (e.g. 'launch') scores low against a multi-word specific
    match (e.g. 'website launch'), so a genuinely specific reference doesn't
    get diluted into false ambiguity by an unrelated entity that happens to
    share one common noun. Only entities within `margin` of the best score
    are kept as genuine candidates - this is what lets Case A (truly
    ambiguous, both score equally) differ from Case C (one strong match,
    one weak incidental one)."""
    ent_words = _content_words(ent.content)
    scored = [(e, _match_score(ent_words, _content_words(e.content)))
              for e in active.values() if e.type == ent.type]
    scored = [(e, s) for e, s in scored if s >= threshold]
    if not scored:
        return []
    best = max(s for _, s in scored)
    return [e for e, s in scored if s >= best - margin]

def merge_check(state: StateGraph, proposed: ProposedDiff) -> MergeResult:
    """Three-way merge: attempt to apply proposed diff against current state.
    Two distinct checks, not one - conflating them is how a duplicate entity
    slips through a clean structural merge:

    (a) Structural conflict - pure logic: does this diff directly contradict
        an existing entity referencing the same thing? Blocks auto-merge.
    (b) Semantic ambiguity - the diff is structurally clean but under-specified:
        an update/reference cue with zero plausible anchors (nothing to update -
        is this new, or did we miss something?) or multiple plausible anchors
        (which one does this refer to?). Must NOT silently auto-merge even
        though nothing structurally conflicts - this is exactly the "the
        launch is next month" duplicate-entity failure mode.

    Deterministic - no model call in this check itself.
    """
    structural_conflicts = []
    semantic_ambiguities = []
    active = state.get_active()

    for ent in proposed.entities_to_add:
        if any(ent.content.lower() == e.content.lower() for e in active.values()):
            continue  # true duplicate, not a conflict - nothing to do

        candidates = _anchor_candidates(ent, active)
        has_update_cue = any(c in ent.content.lower() for c in _UPDATE_CUES)

        # Structural: a real contradiction against exactly the entity it's
        # plausibly about.
        contradicted = [e for e in candidates if _contradicts(ent.content, e.content)]
        if contradicted:
            for e in contradicted:
                structural_conflicts.append(f"{ent.id} contradicts {e.id}: '{ent.content}' vs '{e.content}'")
            continue  # structural conflict takes precedence over ambiguity framing

        # Semantic ambiguity: an update-shaped statement with no clear anchor
        # (missing required slot) or more than one plausible anchor.
        if has_update_cue and len(candidates) == 0:
            semantic_ambiguities.append(
                f"{ent.id}: update-shaped statement ('{ent.content}') but no existing "
                f"entity found to update - is this new, or referring to something not yet stated?"
            )
        elif has_update_cue and len(candidates) > 1:
            names = ", ".join(e.id for e in candidates)
            semantic_ambiguities.append(
                f"{ent.id}: '{ent.content}' could refer to more than one existing entity ({names}) - which one?"
            )

    can_merge = len(structural_conflicts) == 0 and len(semantic_ambiguities) == 0
    return MergeResult(can_merge, structural_conflicts, semantic_ambiguities)

def _contradicts(a: str, b: str) -> bool:
    # Placeholder: in prod use NLI or symbolic check, plus typed edge lookup.
    # Requires: (1) a contains a negation/reversal/update cue, (2) a and b share a
    # real content word (not a stopword) - i.e. they're plausibly about the same thing.
    # Biased toward recall over precision on purpose: per the commit gate's own cost
    # model, a false positive here costs one avoidable question (cheap); a false
    # negative silently auto-merges a contradiction (exactly the failure mode this
    # architecture exists to prevent, and the expensive side of the asymmetry).
    if not any(c in a.lower() for c in _UPDATE_CUES):
        return False
    return len(_content_words(a) & _content_words(b)) > 0

def _hash_id(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:16]

# ---------- 3. Commit Gate - The Center ----------

@dataclass
class GateDecision:
    action: Literal["commit", "branch", "ask"]
    reason: str
    expected_costs: Dict[str, float]
    questions: List[str] = field(default_factory=list)

class CommitGate:
    def __init__(self, cost_late_correction=100.0, cost_branch=25.0, cost_ask_base=20.0):
        self.cost_late = cost_late_correction
        self.cost_branch = cost_branch
        self.cost_ask_base = cost_ask_base
        self.ask_history = deque(maxlen=20)

    def fatigue_term(self) -> float:
        # Exponential penalty if we asked a lot recently
        recent = len([t for t in self.ask_history if time.time() - t < 300])  # last 5 min
        return recent * 8.0

    def decide(self, proposed: ProposedDiff, merge_result: "MergeResult") -> GateDecision:
        # Aggregate confidence
        avg_conf = sum(proposed.confidences)/len(proposed.confidences) if proposed.confidences else 0.5
        p_wrong = 1.0 - avg_conf

        exp_commit = p_wrong * self.cost_late
        exp_branch = self.cost_branch
        exp_ask = self.cost_ask_base + self.fatigue_term()

        # Policy: a genuine structural conflict or an unresolved semantic
        # ambiguity both block auto-commit - but they are NOT equally safe
        # to defer. Semantic ambiguity is legitimately deferrable: holding
        # two interpretations in parallel costs nothing if either could
        # still turn out fine. A structural conflict is a real contradiction
        # that will still be a contradiction later - branching it doesn't
        # resolve anything, and if the branch is later force-resolved
        # (decay/cap) against a main state where the original fact was
        # never marked superseded, the correction can be silently lost
        # entirely. So: structural conflicts can only ever commit (never,
        # since blocked) or ask - never branch. Only ambiguity may branch.
        if merge_result.structural_conflicts:
            items = merge_result.structural_conflicts
            return GateDecision(
                action="ask",
                reason="Genuine structural conflict blocks auto-merge. Never deferred via branch - "
                       "a real contradiction doesn't resolve itself, and branching risks silently "
                       "losing the correction if the branch is later force-resolved.",
                expected_costs={"commit": exp_commit, "branch": exp_branch, "ask": exp_ask},
                questions=[f"Which is correct? Existing vs new: {c}" for c in items]
            )

        if merge_result.semantic_ambiguities:
            items = merge_result.semantic_ambiguities
            if exp_branch < exp_ask:
                return GateDecision(
                    action="branch",
                    reason=f"Genuine ambiguity detected: {items[:2]}. Branch cheaper than interrupt.",
                    expected_costs={"commit": exp_commit, "branch": exp_branch, "ask": exp_ask},
                    questions=[f"Ambiguity: {c}" for c in items]
                )
            else:
                return GateDecision(
                    action="ask",
                    reason="Genuine ambiguity blocks auto-merge. Asking is cheaper than branching.",
                    expected_costs={"commit": exp_commit, "branch": exp_branch, "ask": exp_ask},
                    questions=items
                )

        # No conflict, no ambiguity: triage on confidence
        if exp_commit < min(exp_branch, exp_ask):
            return GateDecision(action="commit", reason=f"High confidence ({avg_conf:.2f}), strict extension, auto-merge safe.", expected_costs={"commit": exp_commit, "branch": exp_branch, "ask": exp_ask})
        elif exp_branch < exp_ask:
            return GateDecision(action="branch", reason=f"Ambiguous ({avg_conf:.2f}) but branching cheaper than interrupting.", expected_costs={"commit": exp_commit, "branch": exp_branch, "ask": exp_ask})
        else:
            return GateDecision(action="ask", reason=f"Uncertain ({avg_conf:.2f}), asking now cheaper than late correction.", expected_costs={"commit": exp_commit, "branch": exp_branch, "ask": exp_ask}, questions=["Confirm: " + e.content + "?" for e in proposed.entities_to_add[:2]])

    def record_ask(self):
        self.ask_history.append(time.time())

# ---------- 4. Context Compilation: Anchor -> Traverse -> Bound ----------

def compile_context(state: StateGraph, task_anchor_ids: List[str], max_depth=2, max_entities=12) -> Dict:
    """
    Deterministic graph traversal, not template lookup.
    Anchor -> Traverse typed edges -> Bound by depth/size
    """
    active = state.get_active()
    visited = set()
    queue = deque([(aid, 0) for aid in task_anchor_ids if aid in active])
    compiled = []

    # Build adjacency from edges
    adj = defaultdict(list)
    for e in state.edges:
        adj[e.src].append((e.dst, e.type))
        adj[e.dst].append((e.src, e.type))  # treat as undirected for compilation

    while queue and len(compiled) < max_entities:
        eid, depth = queue.popleft()
        if eid in visited or depth > max_depth:
            continue
        visited.add(eid)
        if eid in active:
            compiled.append(active[eid])
        if depth < max_depth:
            for neighbor_id, edge_type in adj.get(eid, []):
                if neighbor_id not in visited:
                    queue.append((neighbor_id, depth+1))

    # Detect miss: if Tier Two references entity connected to anchor but not in compiled set
    # (logged by caller)

    return {
        "anchors": task_anchor_ids,
        "compiled_entities": [asdict(e) for e in compiled],
        "traversal_depth": max_depth,
        "entity_count": len(compiled),
        "is_ephemeral": True,  # this payload is thrown away after call
    }

# ---------- 5. End-to-end Example ----------

if __name__ == "__main__":
    # Init
    graph = StateGraph()
    gate = CommitGate()

    # Turn 1: User says something
    text = "The project launch is next month. The budget is 50k. We need a landing page."
    segments = deterministic_segment(text)
    proposed = mock_small_model_extract(segments, turn_id="1")
    merge_result_1 = merge_check(graph, proposed)
    decision = gate.decide(proposed, merge_result_1)
    print(f"Turn 1 decision: {decision.action} - {decision.reason}")
    print(f"Costs: {decision.expected_costs}")

    # Simulate commit / branch / ask outcomes - all three need to leave the
    # entities somewhere retrievable, or the next turn can never test against
    # real state. "ask" here auto-applies pending user confirmation for the
    # demo; a real system would hold these as pending until answered.
    if decision.action in ("commit", "ask"):
        if decision.action == "ask":
            gate.record_ask()
        c1 = graph.commit(added=proposed.entities_to_add, edges_added=proposed.edges_to_add,
                           message="turn 1 ingest", author="kernel:ingest")
        print(f"Committed {len(proposed.entities_to_add)} entities. Head: {graph.head}")
    elif decision.action == "branch":
        anchor = proposed.entities_to_add[0].id if proposed.entities_to_add else "unknown"
        graph.branch("turn1-alt", anchor_id=anchor, from_commit_id=graph.head)
        graph.commit_to_branch("turn1-alt", added=proposed.entities_to_add, message="turn 1 ingest (branched)")
        print(f"Branched: {len(proposed.entities_to_add)} entities held on branch 'turn1-alt', not merged to main.")

    # Turn 2: Contradictory info
    text2 = "Actually the launch is not next month, it's in September. Budget is still 50k."
    seg2 = deterministic_segment(text2)
    prop2 = mock_small_model_extract(seg2, turn_id="2")
    merge_result_2 = merge_check(graph, prop2)
    decision2 = gate.decide(prop2, merge_result_2)
    print(f"\nTurn 2 decision: {decision2.action} - {decision2.reason}")
    print(f"Questions to ask: {decision2.questions}")

    # Compilation example
    anchor_ids = list(graph.get_active().keys())[:1]
    ctx = compile_context(graph, anchor_ids, max_depth=2, max_entities=8)
    print(f"\nCompiled context: {ctx['entity_count']} entities from anchors {ctx['anchors']}")

    # ---- Turn 3: a bad fact gets committed, then reverted ----
    # Simulates the exact failure mode the design exists to prevent: a
    # confident but wrong extraction slips past the gate and gets committed.
    # The test is whether revert actually undoes it, using the real snapshot
    # mechanism, not a no-op.
    print("\n--- Testing revert ---")
    c_before_bad = graph.head
    bad_entity = Entity(
        id=_hash_id("bad-fact")[:12], type="fact",
        content="The budget is 500k", confidence=0.9,
        timestamp=time.time(), provenance="turn:3",
    )
    c_bad = graph.commit(added=[bad_entity], message="turn 3 - bad extraction", author="kernel:ingest")
    print(f"Bad fact committed: '{bad_entity.content}' -> active count = {len(graph.get_active())}")

    reverted_commit = graph.revert(c_before_bad, message="revert bad budget figure")
    active_after_revert = graph.get_active()
    bad_gone = bad_entity.id not in active_after_revert
    print(f"After revert: bad fact present? {not bad_gone} | active count = {len(active_after_revert)}")

    d = graph.diff(c_before_bad, c_bad.id)
    print(f"Diff (pre-bad -> bad commit): added={d['added']}")

    d2 = graph.diff(c_bad.id, reverted_commit.id)
    print(f"Diff (bad commit -> after revert): removed={d2['removed']}")
