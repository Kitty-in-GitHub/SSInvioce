from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from ..models import MaterialType
from .features import FileFeatures
from .settings_store import invoice_slot_id, required_slot_ids


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


def _needed() -> tuple[str, ...]:
    ids = required_slot_ids()
    return tuple(ids) if ids else NEEDED


def _amount_key(amount: float | None) -> str | None:
    if amount is None:
        return None
    return f"{round(float(amount) + 1e-9, 2):.2f}"


def _title_for(feats: list[FileFeatures], amount: float | None) -> str:
    """Compose title: product (or merchant/stem) + invoice date + amount."""
    product = next((f.product_name for f in feats if f.product_name), None)
    merchant = next((f.merchant for f in feats if f.merchant), None)
    date = next((f.date for f in feats if f.date), None)
    stem = None
    for f in feats:
        if f.suggested_type == invoice_slot_id():
            stem = f.original_name.rsplit(".", 1)[0]
            break

    base = product or merchant or stem
    parts: list[str] = []
    if base:
        parts.append(base)
    if date:
        parts.append(date)
    if amount is not None:
        parts.append(f"¥{amount:.2f}")
    if parts:
        return " ".join(parts)
    return "未命名报销"


def _feat_map(features: list[FileFeatures]) -> dict[str, FileFeatures]:
    return {f.temp_id: f for f in features}


def _refresh_title(c: ProposedCluster, by_id: dict[str, FileFeatures]) -> None:
    feats = [by_id[t] for t in c.temp_ids if t in by_id]
    c.title = _title_for(feats, c.amount)


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
    """Greedily form clusters with at most one of each required slot."""
    needed = _needed()
    by_type: dict[str, list[FileFeatures]] = defaultdict(list)
    unknown: list[FileFeatures] = []
    for f in group:
        if f.suggested_type in needed:
            by_type[f.suggested_type].append(f)
        else:
            unknown.append(f)

    clusters: list[ProposedCluster] = []
    while any(by_type[t] for t in needed):
        picked: list[FileFeatures] = []
        for t in needed:
            if by_type[t]:
                picked.append(by_type[t].pop(0))
        if not picked:
            break
        amount = next((p.amount for p in picked if p.amount is not None), None)
        merchant = next((p.merchant for p in picked if p.merchant), None)
        missing = [t for t in needed if not any(p.suggested_type == t for p in picked)]
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

    leftovers = unknown + [f for t in needed for f in by_type[t]]
    return clusters, leftovers


def _try_attach(f: FileFeatures, clusters: list[ProposedCluster], by_id: dict[str, FileFeatures]) -> bool:
    """Attach a typed file into an incomplete cluster when signals agree."""
    if f.suggested_type not in _needed():
        return False
    candidates = [c for c in clusters if f.suggested_type in c.missing]
    if not candidates:
        return False

    key = _amount_key(f.amount)
    scored: list[tuple[int, ProposedCluster]] = []
    for c in candidates:
        score = 0
        if key is not None and _amount_key(c.amount) == key:
            score += 5
        if key is not None and c.amount is None:
            score += 1
        if f.merchant and c.merchant and f.merchant[:12] == c.merchant[:12]:
            score += 4
        if f.order_no:
            for tid in c.temp_ids:
                other = by_id.get(tid)
                if other and other.order_no and other.order_no == f.order_no:
                    score += 6
                    break
        if f.date:
            for tid in c.temp_ids:
                other = by_id.get(tid)
                if other and other.date and other.date == f.date:
                    score += 2
                    break
        # Single incomplete cluster missing this slot — weak fallback
        if len(candidates) == 1 and score == 0:
            score = 1
        if score > 0:
            scored.append((score, c))

    if not scored:
        return False
    scored.sort(key=lambda x: -x[0])
    c = scored[0][1]
    c.temp_ids.append(f.temp_id)
    c.types[f.temp_id] = f.suggested_type
    c.missing = [m for m in c.missing if m != f.suggested_type]
    c.complete = not c.missing
    if c.amount is None and f.amount is not None:
        c.amount = f.amount
    if not c.merchant and f.merchant:
        c.merchant = f.merchant
    _refresh_title(c, by_id)
    return True


def cluster_features(features: list[FileFeatures]) -> tuple[list[ProposedCluster], list[str]]:
    """
    Cluster files into proposed reimbursement entries.
    Returns (clusters, unmatched_temp_ids).
    """
    by_id = _feat_map(features)
    with_amount: dict[str, list[FileFeatures]] = defaultdict(list)
    no_amount: list[FileFeatures] = []
    for f in features:
        key = _amount_key(f.amount)
        if key is None:
            no_amount.append(f)
        else:
            with_amount[key].append(f)

    clusters: list[ProposedCluster] = []
    unmatched: list[FileFeatures] = []
    idx = 1
    for _key, group in sorted(with_amount.items(), key=lambda kv: kv[0]):
        for subgroup in _split_by_signals(group):
            built, left = _pack_trio(subgroup, idx)
            idx += len(built)
            clusters.extend(built)
            unmatched.extend(left)

    unmatched.extend(no_amount)

    # Attach leftovers into incomplete clusters (amount / merchant / order_no)
    still: list[FileFeatures] = []
    for f in unmatched:
        if _try_attach(f, clusters, by_id):
            continue
        still.append(f)

    # Pack remaining typed files even without amount (so OCR-miss dumps still get 拟建条目)
    if still:
        built, left = _pack_trio(still, idx)
        idx += len(built)
        clusters.extend(built)
        still = left

    return clusters, [f.temp_id for f in still]
