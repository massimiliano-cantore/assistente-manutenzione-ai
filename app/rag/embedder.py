"""Embedder intercambiabili.

- FastEmbedEmbedder: modello denso multilingue (ONNX, gira su CPU). È quello usato in produzione.
- TfidfEmbedder: n-grammi di caratteri + SVD, nessun download. Serve per i test e per la CI veloce,
  e come ripiego se il modello non è scaricabile.
"""
from __future__ import annotations

from typing import Protocol

import numpy as np


class Embedder(Protocol):
    nome: str
    dim: int

    def adatta(self, testi: list[str]) -> None: ...
    def documenti(self, testi: list[str]) -> list[list[float]]: ...
    def query(self, testo: str) -> list[float]: ...


class FastEmbedEmbedder:
    def __init__(self, modello: str, cache_dir: str | None = None):
        import os

        from fastembed import TextEmbedding

        self.nome = f"fastembed:{modello}"
        # nell'immagine Docker il modello è scaricato durante la build in FASTEMBED_CACHE_PATH
        self._m = TextEmbedding(model_name=modello, cache_dir=cache_dir or os.getenv("FASTEMBED_CACHE_PATH"))
        self.dim = len(next(iter(self._m.embed(["prova"]))))

    def adatta(self, testi: list[str]) -> None:  # modello pre-addestrato: niente da adattare
        pass

    def documenti(self, testi: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._m.embed(testi)]

    def query(self, testo: str) -> list[float]:
        return next(iter(self._m.query_embed([testo]))).tolist()


class TfidfEmbedder:
    def __init__(self, dim: int = 128):
        from sklearn.feature_extraction.text import TfidfVectorizer

        self.nome = "tfidf-char"
        self._dim_richiesta = dim
        self._vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), lowercase=True, sublinear_tf=True)
        self._svd = None
        self.dim = dim

    def adatta(self, testi: list[str]) -> None:
        from sklearn.decomposition import TruncatedSVD

        x = self._vec.fit_transform(testi)
        n = max(2, min(self._dim_richiesta, x.shape[0] - 1, x.shape[1] - 1))
        self._svd = TruncatedSVD(n_components=n, random_state=0).fit(x)
        self.dim = n

    def _proietta(self, testi: list[str]) -> np.ndarray:
        if self._svd is None:
            raise RuntimeError("TfidfEmbedder: chiamare adatta() prima di usarlo")
        v = self._svd.transform(self._vec.transform(testi))
        return v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-9)

    def documenti(self, testi: list[str]) -> list[list[float]]:
        return self._proietta(testi).tolist()

    def query(self, testo: str) -> list[float]:
        return self._proietta([testo])[0].tolist()


def crea_embedder(tipo: str, modello: str) -> Embedder:
    if tipo == "tfidf":
        return TfidfEmbedder()
    if tipo == "fastembed":
        return FastEmbedEmbedder(modello)
    raise ValueError(f"embedder sconosciuto: {tipo}")
