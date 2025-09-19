import os
import io
import re
import pickle
from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Any, Optional
import numpy as np
import cohere
from sklearn.neighbors import NearestNeighbors
from pypdf import PdfReader

def _normalize_whitespace(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()

def chunk_text(text: str, max_chars: int = 800, overlap: int = 120) -> List[str]:
    text = _normalize_whitespace(text)
    chunks, i, n = [], 0, len(text)
    while i < n:
        j = min(i + max_chars, n)
        chunks.append(text[i:j])
        i = j - overlap if j - overlap > i else j
    return chunks

def read_any(file_bytes: bytes, filename: str) -> str:
    fn = filename.lower()
    if fn.endswith((".txt", ".md")):
        return file_bytes.decode("utf-8", errors="ignore")
    if fn.endswith(".pdf"):
        reader = PdfReader(io.BytesIO(file_bytes))
        return "\n".join([p.extract_text() or "" for p in reader.pages])
    return file_bytes.decode("utf-8", errors="ignore")

@dataclass
class RagIndex:
    model_embed: str = "embed-multilingual-v3.0"
    model_generate: str = "command-a-03-2025"
    top_k: int = 5
    chunk_chars: int = 800
    chunk_overlap: int = 120
    metadata: Dict[str, Any] = field(default_factory=dict)

    chunks: List[str] = field(default_factory=list)
    sources: List[Tuple[str, int]] = field(default_factory=list)
    vectors: Optional[np.ndarray] = None
    nn: Optional[NearestNeighbors] = None

    def _client(self):
        api_key = os.getenv("COHERE_API_KEY")
        if not api_key:
            raise RuntimeError("COHERE_API_KEY not set.")
        return cohere.Client(api_key)

    def add_document(self, file_bytes: bytes, filename: str):
        text = read_any(file_bytes, filename)
        if not text.strip():
            return
        doc_chunks = chunk_text(text, self.chunk_chars, self.chunk_overlap)
        self.chunks.extend(doc_chunks)
        self.sources.extend([(filename, i) for i in range(len(doc_chunks))])
        self.metadata.setdefault("files", []).append({"name": filename, "chunks": len(doc_chunks)})

    def build(self):
        if not self.chunks:
            raise ValueError("No chunks to build.")
        client = self._client()
        embs, B = [], 96
        for i in range(0, len(self.chunks), B):
            batch = self.chunks[i:i+B]
            resp = client.embed(texts=batch, model=self.model_embed, input_type="search_document")
            embs.append(np.array(resp.embeddings, dtype=np.float32))
        self.vectors = np.vstack(embs)
        self.nn = NearestNeighbors(metric="cosine", algorithm="brute").fit(self.vectors)

    def retrieve(self, query: str, k: Optional[int] = None):
        if self.nn is None or self.vectors is None:
            raise ValueError("Index not built.")
        client = self._client()
        resp = client.embed(texts=[query], model=self.model_embed, input_type="search_query")
        q_emb = np.array(resp.embeddings[0], dtype=np.float32).reshape(1, -1)
        distances, indices = self.nn.kneighbors(q_emb, n_neighbors=min(k or self.top_k, len(self.chunks)))
        return [(1.0 - float(d), self.chunks[idx], *self.sources[idx]) for d, idx in zip(distances[0], indices[0])]

    def answer(self, query: str, k: Optional[int] = None, max_context_chars: int = 2400):
        top = self.retrieve(query, k)
        blocks, total = [], 0
        for score, chunk, fn, i in top:
            snippet = chunk[:600]
            block = f"[{fn}#{i}] {snippet}"
            if total + len(block) > max_context_chars:
                break
            blocks.append(block)
            total += len(block)
        context = "\n\n".join(blocks)
        sys_prompt = "You are a helpful assistant. Answer using ONLY the provided context. If unknown, say you don't know. Cite sources like [file#chunk]."
        user_prompt = f"Question: {query}\n\nContext:\n{context}\n\nAnswer:"

        client = self._client()
        resp = client.chat(model=self.model_generate, message=f"{sys_prompt}\n\n{user_prompt}", temperature=0.3, max_tokens=300)
        return {
            "answer": resp.text.strip(),
            "contexts": [{"score": s, "source": f"{fn}#{i}", "text": tx} for (s, tx, fn, i) in top],
        }

    def save(self, path: str):
        blob = {
            "model_embed": self.model_embed,
            "model_generate": self.model_generate,
            "top_k": self.top_k,
            "chunk_chars": self.chunk_chars,
            "chunk_overlap": self.chunk_overlap,
            "metadata": self.metadata,
            "chunks": self.chunks,
            "sources": self.sources,
            "vectors": self.vectors.astype(np.float32) if self.vectors is not None else None,
        }
        with open(path, "wb") as f:
            pickle.dump(blob, f)

    @classmethod
    def load(cls, path: str):
        with open(path, "rb") as f:
            blob = pickle.load(f)
        inst = cls(
            model_embed=blob["model_embed"],
            model_generate=blob["model_generate"],
            top_k=blob["top_k"],
            chunk_chars=blob["chunk_chars"],
            chunk_overlap=blob["chunk_overlap"],
            metadata=blob["metadata"],
        )
        inst.chunks, inst.sources, inst.vectors = blob["chunks"], blob["sources"], blob["vectors"]
        if inst.vectors is not None:
            inst.nn = NearestNeighbors(metric="cosine", algorithm="brute").fit(inst.vectors)
        return inst
