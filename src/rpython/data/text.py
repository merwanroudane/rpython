"""Text / NLP structures (section 24): corpora, tokens, document-term and
TF-IDF matrices, vocabularies, embeddings.

Envelopes:

* ``kind: "dtm"`` -- a ``sparse`` payload plus ``docs``, ``terms``,
  ``weighting`` (``count`` / ``tfidf`` / ``binary``), ``orientation``
  (``dtm`` = docs x terms, ``tdm`` = terms x docs) and ``vocabulary``.
  R: ``quanteda::as.dfm`` (if installed) else a ``Matrix`` with dimnames.
* ``kind: "corpus"`` -- a ``table`` + ``semantics.text`` (``text_column``,
  ``doc_id``, ``language``).  R: ``quanteda::corpus`` else data.frame.
* Tokens travel as list columns / nested lists; embeddings as arrays with
  row labels.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .context import Context
from .registry import Adapter, REGISTRY
from .semantic import Confidence, ConversionPath, Detection, Fidelity, SemanticRole
from .sparse import SparseAdapter, _scipy
from .tabular import encode_frame, decode_frame


@dataclass
class DocumentTermMatrix:
    """``rp.dtm(matrix, docs=[...], terms=[...], weighting="count")``."""

    matrix: Any                   # scipy sparse or dense ndarray, docs x terms
    docs: list[str]
    terms: list[str]
    weighting: str = "count"      # count | tfidf | binary | custom
    orientation: str = "dtm"      # dtm (docs x terms) | tdm (terms x docs)
    vocabulary: dict[str, int] | None = None
    language: str | None = None

    @classmethod
    def from_sklearn(cls, matrix: Any, vectorizer: Any, docs: list[str] | None = None) -> "DocumentTermMatrix":
        terms = list(vectorizer.get_feature_names_out())
        w = "tfidf" if type(vectorizer).__name__.lower().startswith("tfidf") else "binary" if getattr(vectorizer, "binary", False) else "count"
        return cls(matrix, docs or [f"text{i + 1}" for i in range(matrix.shape[0])], terms, weighting=w,
                   vocabulary={k: int(v) for k, v in vectorizer.vocabulary_.items()})

    def describe_structure(self) -> str:
        nnz = self.matrix.nnz if hasattr(self.matrix, "nnz") else int(np.count_nonzero(self.matrix))
        return "\n".join([f"Type: Document-Term Matrix ({self.orientation})", f"Documents: {len(self.docs)}",
                          f"Terms: {len(self.terms)}", f"Weighting: {self.weighting}",
                          f"Non-zero: {nnz:,} ({100 * nnz / max(1, len(self.docs) * len(self.terms)):.2f}% dense)",
                          f"Sparse storage: {'yes' if hasattr(self.matrix, 'nnz') else 'no'}"])


@dataclass
class Corpus:
    """``rp.corpus(df, text="text", doc_id="id", language="fr")``."""

    data: pd.DataFrame
    text: str = "text"
    doc_id: str | None = None
    language: str | None = None
    tokens: str | None = None      # column holding token lists, if any

    def describe_structure(self) -> str:
        return "\n".join(["Type: Corpus", f"Documents: {len(self.data)}", f"Text column: {self.text}",
                          f"Document id: {self.doc_id or '(row order)'}", f"Language: {self.language or 'unknown'}",
                          f"Docvars: {[c for c in self.data.columns if c not in (self.text, self.doc_id, self.tokens)]}"])


def dtm(matrix: Any, docs: list[str], terms: list[str], **kw: Any) -> DocumentTermMatrix:
    return DocumentTermMatrix(matrix, list(docs), list(terms), **kw)


def corpus(data: pd.DataFrame, text: str = "text", **kw: Any) -> Corpus:
    return Corpus(data, text, **kw)


class TextAdapter(Adapter):
    family = "text"
    kinds = ("dtm", "corpus")
    tier = ConversionPath.ADAPTER
    priority = 13

    def detect(self, obj: Any) -> Detection | None:
        if isinstance(obj, DocumentTermMatrix):
            return Detection("document-term matrix", Confidence.CONFIRMED, obj.weighting)
        if isinstance(obj, Corpus):
            return Detection("corpus", Confidence.CONFIRMED, f"{len(obj.data)} documents")
        return None

    def encode(self, obj: Any, ctx: Context) -> dict[str, Any]:
        if isinstance(obj, DocumentTermMatrix):
            sp = _scipy()
            m = obj.matrix
            if sp is not None and not sp.issparse(m):
                m = sp.csr_matrix(np.asarray(m))
                ctx.plan.note("dense document-term matrix stored sparse for transfer")
            sparse_env = SparseAdapter().encode(m, ctx) if sp is not None else None
            if sparse_env is None:
                from .arrays import ArrayAdapter
                sparse_env = ArrayAdapter().encode(np.asarray(m), ctx)
            sparse_env["dimnames"] = [list(map(str, obj.docs)), list(map(str, obj.terms))] if obj.orientation == "dtm" \
                else [list(map(str, obj.terms)), list(map(str, obj.docs))]
            env = {"rpx": 1, "kind": "dtm", "matrix": sparse_env, "docs": list(map(str, obj.docs)), "terms": list(map(str, obj.terms)),
                   "weighting": obj.weighting, "orientation": obj.orientation, "vocabulary": obj.vocabulary,
                   "language": obj.language, "meta": {"source_class": "rpython.DocumentTermMatrix"}}
            ctx.record("dtm", ConversionPath.ADAPTER, "json+sparse",
                       f"{len(obj.docs):,} docs x {len(obj.terms):,} terms ({obj.weighting}) -> quanteda dfm / Matrix")
            ctx.plan.fidelity.set("values", Fidelity.LOSSLESS)
            ctx.plan.fidelity.set("names", Fidelity.LOSSLESS, "document ids and vocabulary kept")
            ctx.plan.fidelity.set("storage", Fidelity.LOSSLESS, "sparse")
            return env
        c: Corpus = obj
        sem = {"text_column": c.text, "doc_id": c.doc_id, "language": c.language, "tokens": c.tokens,
               "docvars": [x for x in c.data.columns if x not in (c.text, c.doc_id, c.tokens)]}
        env = encode_frame(c.data, ctx, semantics={"text": sem, "roles": {c.text: SemanticRole.TEXT.value,
                                                                            **({c.doc_id: SemanticRole.ID.value} if c.doc_id else {})}})
        env["kind"] = "corpus"
        ctx.record("corpus", ConversionPath.ADAPTER, ctx.plan.backend, f"{len(c.data):,} documents -> quanteda corpus / data.frame")
        ctx.plan.fidelity.set("semantics", Fidelity.LOSSLESS)
        return env

    def decode(self, env: dict[str, Any], ctx: Context) -> Any:
        if env["kind"] == "dtm":
            m_env = env["matrix"]
            if m_env.get("kind") == "sparse":
                m = SparseAdapter().decode({**m_env, "dimnames": None}, ctx)
            else:
                from .arrays import ArrayAdapter
                m = ArrayAdapter().decode({**m_env, "dimnames": None}, ctx)
            ctx.record("dtm", ConversionPath.ADAPTER, "json+sparse", "dfm / Matrix -> DocumentTermMatrix")
            return DocumentTermMatrix(m, env.get("docs") or [], env.get("terms") or [], weighting=env.get("weighting", "count"),
                                      orientation=env.get("orientation", "dtm"), vocabulary=env.get("vocabulary"),
                                      language=env.get("language"))
        sem = (env.get("semantics") or {}).get("text") or {}
        df = decode_frame(env, ctx)
        ctx.record("corpus", ConversionPath.ADAPTER, ctx.plan.backend, "corpus -> Corpus")
        return Corpus(df, sem.get("text_column", "text"), doc_id=sem.get("doc_id"), language=sem.get("language"), tokens=sem.get("tokens"))


REGISTRY.register(TextAdapter(), tested=True)
