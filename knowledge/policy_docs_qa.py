"""
Retrieval over the governance policy documents in documentation/08-12
(Governance & Autonomy, RBAC & Approval, Integration & Security, Incident
Escalation & Maintenance, and the Copilot demo Q&A script) — powers the
Novus Studio Copilot tab's policy questions (backend/app/routers/copilot.py).

No vector DB: five short markdown files don't warrant one. Chunks are
markdown sections (split on "## " headings), scored against the question by
plain lowercased word overlap. This is a relevance ranker, not a semantic
search — good enough for a five-document corpus where the vocabulary in the
question ("RBAC", "Tier 2", "auditor") usually appears verbatim in the
relevant section.

generate_policy_answer() (knowledge/local_llm_client.py) synthesizes a
prose answer from the top chunks when an LLM provider is configured;
answer_question() below falls back to returning the top-matching chunk's
raw text — labeled honestly as an extractive match, never as a fabricated
"live" LLM answer — when no provider is configured.
"""

import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .local_llm_client import local_llm_client

_DOCS_DIR = Path(__file__).resolve().parents[1] / "documentation"

# Ordered so the enforced-policy documents rank first if the corpus ever
# needs a tie-break; the demo Q&A script is included last since it's
# presenter notes about the other four, not policy itself.
_POLICY_DOC_FILENAMES = (
    "08_Governance_Autonomy_Policy.md",
    "09_RBAC_Approval_Policy.md",
    "10_Integration_Security_Policy.md",
    "11_Incident_Escalation_Maintenance_Policy.md",
    "12_Novus_Studio_Copilot_Demo_QA.md",
)

_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "of", "to", "in", "on", "for", "and", "or", "at", "by", "with", "this",
    "that", "it", "its", "as", "does", "do", "did", "what", "whats",
    "what's", "who", "whos", "who's", "how", "why", "when", "where",
    "can", "could", "should", "would", "will", "i", "you", "we", "our",
    "any", "if", "not", "into", "than", "then", "so", "about",
}

_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> List[str]:
    return [w for w in _WORD_RE.findall(text.lower()) if w not in _STOPWORDS]


_HEADING_NUMBER_RE = re.compile(r"^\d+\.\s*")


class _Chunk:
    __slots__ = ("doc", "heading", "text", "heading_tokens", "body_tokens")

    def __init__(self, doc: str, heading: str, text: str):
        self.doc = doc
        self.heading = heading
        self.text = text
        # Every section heading in these docs is numbered ("2. Roles",
        # "3. Tier Assignment Rule", ...) - left in, a question mentioning
        # "Tier 2" would spuriously score every "2."-numbered heading in
        # the whole corpus, which has nothing to do with tier 2. Stripped
        # here (tokenization only) while the numbered heading is kept
        # as-is for display/citation.
        self.heading_tokens = set(_tokenize(_HEADING_NUMBER_RE.sub("", heading)))
        self.body_tokens = set(_tokenize(text))


_chunks_cache: Optional[List[_Chunk]] = None
_idf_cache: Optional[Dict[str, float]] = None


def _load_chunks() -> List[_Chunk]:
    """Lazily parsed once per process and cached — the docs don't change
    while the server is running; a restart picks up edits, same tradeoff
    knowledge/decision_memory_index.py's seed data makes."""
    global _chunks_cache
    if _chunks_cache is not None:
        return _chunks_cache

    chunks: List[_Chunk] = []
    for filename in _POLICY_DOC_FILENAMES:
        path = _DOCS_DIR / filename
        if not path.exists():
            continue
        raw = path.read_text(encoding="utf-8")
        # Split on level-2 headings ("## ...") - level-1 is just the doc
        # title, and finer headings (###) stay grouped with their parent
        # section so a chunk carries enough surrounding context to answer
        # from on its own.
        sections = re.split(r"\n(?=## )", raw)
        # sections[0] (title + Platform/Version/Status/Owner/Enforcing-code
        # metadata block, before the first "## ") is bookkeeping, not
        # policy content - never worth returning as an "answer". Every doc
        # here follows that same header shape, but fall back to keeping it
        # rather than indexing nothing for a doc that doesn't.
        if len(sections) > 1:
            sections = sections[1:]
        for section in sections:
            section = section.strip()
            if not section:
                continue
            heading_match = re.match(r"^(#{1,2})\s+(.+)", section)
            heading = heading_match.group(2).strip() if heading_match else filename
            if len(section) > 2000:
                section = section[:2000]
            chunks.append(_Chunk(doc=filename, heading=heading, text=section))

    _chunks_cache = chunks
    return chunks


def _build_idf(chunks: List[_Chunk]) -> Dict[str, float]:
    """Inverse document frequency across chunks, corpus-wide cached like
    the chunks themselves. This corpus is small and every section talks
    about tiers/decisions/approval, so a plain word-overlap score alone
    lets those ubiquitous words swamp whatever term actually distinguishes
    the relevant section (e.g. "auditor", "RBAC", "escalate") - IDF down-
    weights a token in proportion to how many chunks it already appears
    in, so a question repeating "tier"/"decision" doesn't just match
    everything equally."""
    n = len(chunks)
    doc_freq: Dict[str, int] = {}
    for c in chunks:
        for tok in c.heading_tokens | c.body_tokens:
            doc_freq[tok] = doc_freq.get(tok, 0) + 1
    return {tok: math.log((n + 1) / (df + 1)) + 1.0 for tok, df in doc_freq.items()}


def _score_chunk(q_tokens: set, chunk: _Chunk, idf: Dict[str, float]) -> float:
    """Heading matches count for more than body matches - a question whose
    words land in a section's own title is a much stronger topical signal
    than the same words appearing somewhere in a long section body. Divided
    by sqrt(body size) so a long chunk doesn't out-rank a short, precise
    one purely by containing more distinct words overall."""
    heading_hits = q_tokens & chunk.heading_tokens
    body_hits = q_tokens & chunk.body_tokens
    raw = 3 * sum(idf.get(t, 1.0) for t in heading_hits) + sum(idf.get(t, 1.0) for t in body_hits)
    # Floor of 20 keeps a short chunk from being over-rewarded just for
    # being short (a couple of incidental hits in a 10-token chunk would
    # otherwise outscore a genuinely on-topic 80-token section).
    return raw / (max(len(chunk.body_tokens), 20) ** 0.5)


def _rank_chunks(question: str, chunks: List[_Chunk], top_k: int = 3) -> List[_Chunk]:
    global _idf_cache
    q_tokens = set(_tokenize(question))
    if not q_tokens:
        return []
    if _idf_cache is None:
        _idf_cache = _build_idf(chunks)
    scored = [(_score_chunk(q_tokens, c, _idf_cache), c) for c in chunks]
    scored = [(score, c) for score, c in scored if score > 0]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [c for _, c in scored[:top_k]]


def answer_question(question: str) -> Dict[str, Any]:
    """Answers a governance/policy question grounded in documentation/08-12.
    Always returns a real, honestly-labeled status — never claims a live
    LLM answer when generation didn't actually happen."""
    question = (question or "").strip()
    if not question:
        return {"status": "empty_question", "model_used": None, "answer": None, "sources": []}

    top_chunks = _rank_chunks(question, _load_chunks())
    if not top_chunks:
        return {
            "status": "no_match",
            "model_used": None,
            "answer": "I couldn't find anything in the governance policy documents about that.",
            "sources": [],
        }

    sources = [{"doc": c.doc, "heading": c.heading} for c in top_chunks]

    llm_result = local_llm_client.generate_policy_answer(
        question, [{"doc": c.doc, "heading": c.heading, "text": c.text} for c in top_chunks]
    )
    if llm_result["status"] == "live_llm_generated":
        return {
            "status": "live_llm_generated",
            "model_used": llm_result["model_used"],
            "answer": llm_result["answer"],
            "sources": sources,
        }

    # No LLM provider configured (or generation failed) - fall back to the
    # best-matching chunk's actual policy text rather than a dead end.
    return {
        "status": "extractive_fallback",
        "model_used": None,
        "answer": top_chunks[0].text,
        "sources": sources,
        "llm_error": llm_result.get("error"),
    }
