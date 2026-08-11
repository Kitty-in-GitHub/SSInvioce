from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from ..models import MaterialType
from .features import FileFeatures


@dataclass
class ProposedCluster:
    cluster_id: str
    title: str
    amount: float | None
    temp_ids: list[str] = field(default_factory=list)
    types: dict[str, str] = field(default_factory=dict)  # temp_id -> type
    complete: bool = False
    missing: list[str] = field(default_factory=list)
    merchant: str | None = None

    def to_public(self) -> dict:
        return {
            "cluster_id": self.cluster_id,
            "title": self.title,
            "amount": self.amount,
            "temp_ids": self.temp_ids,
            "types": self.types,
            "complete": self.complete,
            "missing": self.missing,
            "merchant": self.merchant,
        }


NEEDED = ("invoice", "order", "payment")


def _amount_key(amount: float | None) -> str | None:
    if amount is None:
        return None
    return f"{round(float(amount) + 1e-9, 2):.2f}"


def _title_for(feats: list[FileFeatures], amount: float | None) -> str:
    for f in feats:
        if f.merchant:
            base = f.merchant
            if amount is not None:
                return f"{base} ¥{amount:.2f}"
            return base
    for f in feats:
        if f.suggested_type == "invoice":
            stem = f.original_name.rsplit(".", 1)[0]
            if amount is not None:
                return f"{stem} ¥{amount:.2f}"
            return stem
    if amount is not None:
        return f"报销 ¥{amount:.2f}"
    return "未命名报销"


def _split_by_signals(group: list[FileFeatures]) -> list[list[FileFeatures]]:
    """Split same-amount files when merchant/date/order_no disagree."""
    if len(group) <= 3:
        return [group]

    buckets: dict[str, list[FileFeatures]] = defaultdict(list)
    for f in group:
        key_parts = [
            (f.merchant or "").strip()[:16],
            f.date or "",
            f.order_no or "",
        ]
        key = "|".join(key_parts)
        if key == "||":
            key = f"_loose_{id(f)}"
        buckets[key].append(f)

    # Merge tiny loose singles back if only one real bucket
    real = [v for k, v in buckets.items() if not k.startswith("_loose_")]
    loose = [v for k, v in buckets.items() if k.startswith("_loose_")]
    if not real:
        return [group]
    if len(real) == 1 and loose:
        real[0].extend(sum(loose, []))
        return real
    out = list(real)
    for lump in loose:
        out.append(lump)
    return out


def _pack_trio(group: list[FileFeatures], cluster_idx: int) -> tuple[list[ProposedCluster], list[FileFeatures]]:
    """Greedily form clusters with at most one of each type."""
    by_type: dict[MaterialType, list[FileFeatures]] = defaultdict(list)
    unknown: list[FileFeatures] = []
    for f in group:
        if f.suggested_type in NEEDED:
            by_type[f.suggested_type].append(f)
        else:
            unknown.append(f)

    clusters: list[ProposedCluster] = []
    while any(by_type[t] for t in NEEDED):
        picked: list[FileFeatures] = []
        for t in NEEDED:
            if by_type[t]:
                picked.append(by_type[t].pop(0))
        if not picked:
            break
        amount = next((p.amount for p in picked if p.amount is not None), None)
        merchant = next((p.merchant for p in picked if p.merchant), None)
        missing = [t for t in NEEDED if not any(p.suggested_type == t for p in picked)]
        cid = f"c{cluster_idx:04d}"
        cluster_idx += 1
        clusters.append(
            ProposedCluster(
                cluster_id=cid,
                title=_title_for(picked, amount),
                amount=amount,
                temp_ids=[p.temp_id for p in picked],
                types={p.temp_id: p.suggested_type for p in picked},
                complete=not missing,
                missing=list(missing),
                merchant=merchant,
            )
        )

    leftovers = unknown + [f for t in NEEDED for f in by_type[t]]
    return clusters, leftovers


def cluster_features(features: list[FileFeatures]) -> tuple[list[ProposedCluster], list[str]]:
    """
    Cluster files into proposed reimbursement entries.
    Returns (clusters, unmatched_temp_ids).
    """
    with_amount: dict[str, list[FileFeatures]] = defaultdict(list)
    no_amount: list[FileFeatures] = []
    for f in features:
        key = _amount_key(f.amount)
        if key is None:
            no_amount.append(f)
        else:
            with_amount[key].append(f)

    clusters: list[ProposedCluster] = []
    unmatched: list[FileFeatures] = list(no_amount)
    idx = 1
    for _key, group in sorted(with_amount.items(), key=lambda kv: kv[0]):
        for subgroup in _split_by_signals(group):
            built, left = _pack_trio(subgroup, idx)
            idx += len(built)
            clusters.extend(built)
            unmatched.extend(left)

    # Try attach unmatched unknowns into incomplete clusters of same amount
    still: list[FileFeatures] = []
    for f in unmatched:
        placed = False
        if f.amount is not None and f.suggested_type in NEEDED:
            key = _amount_key(f.amount)
            for c in clusters:
                if _amount_key(c.amount) != key:
                    continue
                if f.suggested_type in c.missing:
                    c.temp_ids.append(f.temp_id)
                    c.types[f.temp_id] = f.suggested_type
                    c.missing = [m for m in c.missing if m != f.suggested_type]
                    c.complete = not c.missing
                    if not c.merchant and f.merchant:
                        c.merchant = f.merchant
                        c.title = _title_for(
                            [x for x in features if x.temp_id in c.temp_ids],
                            c.amount,
                        )
                    placed = True
                    break
        if not placed:
            still.append(f)

    return clusters, [f.temp_id for f in still]
