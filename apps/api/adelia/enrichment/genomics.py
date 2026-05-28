"""23andMe / Ancestry raw genome parser + ClinVar/PharmGKB variant lookup.

23andMe raw data is a TSV-like text file:
    # rsid  chromosome  position  genotype
    rs4477212  1  82154  AA
    rs3094315  1  752566  AG
    ...

This module parses that format + matches against a curated starter set of
~20 clinically-actionable variants (pharmacogenomics + disease risk + carrier
status), all sourced from public ClinVar/PharmGKB/CPIC databases.

v0.1 covers: CYP2C19/CYP2C9/CYP2D6/SLCO1B1 (PGx essentials), APOE (Alzheimer),
F5/F2 (thrombophilia), HFE (hemochromatosis), TCF7L2 (T2D), MTHFR, CFTR carrier,
and ~10 more.

v0.2.1: full ClinVar XML import (~3M variants) + clinically significant filter.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import IO, Iterator, Literal

logger = logging.getLogger(__name__)


_VARIANTS_FILE = Path(__file__).parent / "data" / "clinvar_pgx_starter.json"

VariantCategory = Literal["pharmacogenomics", "disease_risk", "carrier_status"]


@dataclass(frozen=True)
class RawGenotype:
    rsid: str
    chromosome: str
    position: int
    genotype: str  # e.g. 'AA', 'AG', 'TT', '--' for no-call


@dataclass(frozen=True)
class VariantHit:
    rsid: str
    gene: str
    user_genotype: str
    risk_alleles: tuple[str, ...]
    risk_alleles_count: int  # how many of user's alleles match the risk
    zygosity: Literal["homozygous", "heterozygous", "absent"]
    category: VariantCategory
    phenotype: str
    actionability: str
    evidence_level: str
    url: str


def parse_23andme_raw(stream: IO[str]) -> Iterator[RawGenotype]:
    """Stream-parse 23andMe raw data. Skips comment lines (#) and 'no-call' (--)."""
    for line_no, line in enumerate(stream, start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        rsid, chrom, pos_str, genotype = parts[0], parts[1], parts[2], parts[3]
        if not rsid.startswith("rs"):
            continue
        try:
            pos = int(pos_str)
        except ValueError:
            continue
        if "-" in genotype:  # no-call
            continue
        yield RawGenotype(
            rsid=rsid,
            chromosome=chrom,
            position=pos,
            genotype=genotype.upper(),
        )


@lru_cache(maxsize=1)
def _load_variant_catalog() -> dict[str, dict]:
    """Map rsid → variant entry (only clinically actionable variants)."""
    with _VARIANTS_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return {entry["rsid"]: entry for entry in data.get("variants", [])}


def evaluate_genotype(genotype: str, risk_alleles: list[str]) -> tuple[int, str]:
    """Count how many risk alleles user has + return zygosity label.

    23andMe genotype is two alleles concatenated (e.g. 'AT', 'AA').
    """
    if not genotype or len(genotype) < 1:
        return 0, "absent"
    alleles = list(genotype.upper())
    risk_set = {a.upper() for a in risk_alleles}
    matches = sum(1 for a in alleles if a in risk_set)
    if matches == 2:
        return 2, "homozygous"
    if matches == 1:
        return 1, "heterozygous"
    return 0, "absent"


def match_variants(genotypes: list[RawGenotype]) -> list[VariantHit]:
    """Match user genotypes against the curated catalog. Returns hits sorted
    by actionability (PGx + homozygous first)."""
    catalog = _load_variant_catalog()
    by_rsid = {g.rsid: g for g in genotypes}

    hits: list[VariantHit] = []
    for rsid, entry in catalog.items():
        gt = by_rsid.get(rsid)
        if gt is None:
            continue
        risk_alleles = entry.get("alleles_risk", [])
        # Special-case for INDEL representations like 'DEL' — skip alele math
        if any(a in {"DEL", "INS"} for a in risk_alleles):
            # Just record presence; needs more sophisticated parsing for true match
            count = 0
            zygosity = "absent"
        else:
            count, zygosity = evaluate_genotype(gt.genotype, risk_alleles)

        if count == 0:
            continue  # absent — skip

        hits.append(
            VariantHit(
                rsid=rsid,
                gene=entry["gene"],
                user_genotype=gt.genotype,
                risk_alleles=tuple(risk_alleles),
                risk_alleles_count=count,
                zygosity=zygosity,
                category=entry["category"],
                phenotype=entry["phenotype"],
                actionability=entry["actionability"],
                evidence_level=entry.get("evidence_level", ""),
                url=entry.get("url", ""),
            )
        )

    # Sort: PGx > carrier > disease_risk; within category homozygous > heterozygous
    _cat_rank = {"pharmacogenomics": 0, "carrier_status": 1, "disease_risk": 2}
    _zyg_rank = {"homozygous": 0, "heterozygous": 1}
    hits.sort(
        key=lambda h: (
            _cat_rank.get(h.category, 99),
            _zyg_rank.get(h.zygosity, 99),
            h.gene,
        )
    )
    return hits


def catalog_stats() -> dict[str, int]:
    """Stats for /health and admin."""
    cat = _load_variant_catalog()
    by_category: dict[str, int] = {}
    for entry in cat.values():
        c = entry.get("category", "unknown")
        by_category[c] = by_category.get(c, 0) + 1
    return {
        "variants_total": len(cat),
        "by_category": by_category,
    }
