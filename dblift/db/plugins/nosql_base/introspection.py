"""Schema inferred by sampling documents."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List


class SamplingIntrospector(ABC):
    """Infers a schema model from documents, since none is declared.

    A document store has no catalogue to read: the "schema" is whatever
    shape the stored documents happen to have. Every NoSQL introspector
    therefore runs the same three steps — list the collections, sample
    documents from each, fold the observed fields into a model — and only
    the SDK calls differ. Naming the steps here keeps that shared shape
    from being re-invented per plugin, and keeps the sampling limit an
    explicit, reportable choice rather than a hidden constant.

    Inference is lossy by nature: a field absent from the sample is absent
    from the model. Implementations should surface the sample size they
    used so a caller can say how much of the collection was examined.
    """

    #: Documents read per collection when inferring fields. Sampling is a
    #: trade-off between fidelity and request cost; implementations may
    #: override, and should report the value they used.
    SAMPLE_SIZE: int = 100

    @abstractmethod
    def list_collections(self) -> List[str]:
        """Return the names of user-visible collections/containers."""

    @abstractmethod
    def sample_documents(self, collection: str, limit: int) -> List[Dict[str, Any]]:
        """Return at most *limit* documents from *collection*."""

    @abstractmethod
    def infer_fields(self, documents: List[Dict[str, Any]]) -> Dict[str, str]:
        """Fold sampled *documents* into a ``{field_name: type_name}`` map.

        Implementations decide how to reconcile a field seen with more
        than one type across the sample; whatever the rule, it should be
        stated rather than left implicit.
        """
