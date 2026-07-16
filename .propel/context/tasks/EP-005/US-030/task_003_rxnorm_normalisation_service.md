# TASK-003: RxNorm Normalisation Service via RxNav API

> **Story:** US-030 | **Effort:** 6 hours | **Layer:** Backend — External Integration  
> **Status:** Draft | **Date:** 2026-07-16

---

## Objective

Implement an async `RxNormNormaliser` service that maps free-text drug names to canonical RxNorm CUIs via the NIH RxNav REST API, with in-process caching to avoid redundant lookups during a single reconciliation run.

---

## Context

Drug name comparison across three FHIR lists is unreliable on display text alone (e.g. "Metformin 500mg oral" vs "metFORMIN 500 MG Oral Tablet"). Mapping to RxNorm CUIs provides a stable, system-independent identifier for the same drug. This task isolates all RxNav API interaction so the reconciliation agent (TASK-004) only works with normalised CUIs.

**Upstream Dependencies:**
- TASK-002: `RawMedicationEntry.name` is the input to normalisation
- Network access to `https://rxnav.nlm.nih.gov` (public, no auth required)

---

## Scope

### In Scope

1. **`RxNormNormaliser` class** — `backend/app/agents/medication_reconciliation/rxnorm.py`:
   - `async normalise(drug_name: str) -> str | None` — returns CUI or `None` if not found
   - `async normalise_batch(names: list[str]) -> dict[str, str | None]` — concurrent batch lookup
   - In-process `dict` cache keyed on lowercased drug name (session lifetime only)
   - HTTP timeout: 5 seconds; on timeout/error return `None` and log warning (non-fatal)

2. **`DoseParser` utility** — `backend/app/agents/medication_reconciliation/dose_parser.py`:
   - `parse_dose(dose_string: str | None) -> tuple[float | None, str | None]` — returns `(value, unit)` from strings like `"500 mg"`, `"2.5mg"`, `"1000 MG"`

3. **Settings additions** — `backend/app/core/config.py`:
   - `RXNAV_BASE_URL: str = "https://rxnav.nlm.nih.gov/REST"`
   - `RXNAV_TIMEOUT_SECONDS: int = 5`

### Out of Scope

- Drug interaction detection (US-031/US-032, separate stories)
- Persisting CUI to database (TASK-004 responsibility)
- Three-way comparison (TASK-004)

---

## Acceptance Criteria

### AC1: CUI Returned for Known Drug
**Given** the drug name `"Metformin"`  
**When** `normalise("Metformin")` is called  
**Then** returns the CUI `"6809"` (or equivalent current RxNorm CUI for metformin base ingredient)

### AC2: `None` Returned for Unknown Drug
**Given** the drug name `"Fictionomycin 200mg"`  
**When** `normalise("Fictionomycin 200mg")` is called against RxNav  
**Then** returns `None` without raising an exception

### AC3: Cache Prevents Duplicate HTTP Calls
**Given** `normalise("Atorvastatin")` has been called once  
**When** `normalise("atorvastatin")` (different case) is called again  
**Then** only one HTTP request is made to RxNav (cache hit on lowercased key)

### AC4: Batch Lookup is Concurrent
**Given** a list of 5 drug names  
**When** `normalise_batch(names)` is called  
**Then** all RxNav calls execute concurrently (wall time ≈ single call, not 5×)

### AC5: `DoseParser` Extracts Value and Unit
**Given** the dose string `"500 mg"`  
**When** `parse_dose("500 mg")` is called  
**Then** returns `(500.0, "mg")`

### AC6: `parse_dose` Returns `(None, None)` for Unparseable String
**Given** the dose string `"as directed"`  
**When** `parse_dose("as directed")` is called  
**Then** returns `(None, None)` without raising an exception

---

## Implementation Details

### File: `backend/app/agents/medication_reconciliation/rxnorm.py`

```python
"""RxNorm CUI normalisation via NIH RxNav REST API."""

import asyncio
import logging
import httpx
from app.core.config import settings

logger = logging.getLogger(__name__)

RXNAV_CUI_ENDPOINT = "{base}/rxcui.json?name={name}&search=1"


class RxNormNormaliser:
    """
    Maps drug display names to RxNorm CUIs using the RxNav public API.

    Caches results in-memory for the lifetime of the agent run to avoid
    redundant API calls for the same drug appearing on multiple lists.
    """

    def __init__(self) -> None:
        self._cache: dict[str, str | None] = {}

    async def normalise(self, drug_name: str) -> str | None:
        """
        Look up RxNorm CUI for a single drug name.
        Returns CUI string or None if not found / API error.
        """
        cache_key = drug_name.lower().strip()
        if cache_key in self._cache:
            return self._cache[cache_key]

        cui = await self._fetch_cui(drug_name)
        self._cache[cache_key] = cui
        return cui

    async def normalise_batch(
        self, names: list[str]
    ) -> dict[str, str | None]:
        """Concurrently normalise a list of drug names."""
        results = await asyncio.gather(
            *[self.normalise(name) for name in names], return_exceptions=False
        )
        return dict(zip(names, results))

    async def _fetch_cui(self, drug_name: str) -> str | None:
        url = RXNAV_CUI_ENDPOINT.format(
            base=settings.RXNAV_BASE_URL,
            name=httpx.QueryParams({"name": drug_name})["name"],
        )
        try:
            async with httpx.AsyncClient(
                timeout=settings.RXNAV_TIMEOUT_SECONDS
            ) as client:
                response = await client.get(
                    f"{settings.RXNAV_BASE_URL}/rxcui.json",
                    params={"name": drug_name, "search": 1},
                )
                response.raise_for_status()
                data = response.json()
                id_group = data.get("idGroup", {})
                rxnorm_ids = id_group.get("rxnormId", [])
                if rxnorm_ids:
                    return rxnorm_ids[0]
                return None
        except httpx.TimeoutException:
            logger.warning("RxNav timeout for drug: %s", drug_name)
            return None
        except Exception as exc:
            logger.warning("RxNav error for drug '%s': %s", drug_name, exc)
            return None
```

### File: `backend/app/agents/medication_reconciliation/dose_parser.py`

```python
"""Utility for parsing dose strings into numeric value + unit."""

import re

_DOSE_PATTERN = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>mg|g|mcg|ml|units?|iu|meq)",
    re.IGNORECASE,
)


def parse_dose(dose_string: str | None) -> tuple[float | None, str | None]:
    """
    Parse a dose string into (value, unit).

    Examples:
        "500 mg"  → (500.0, "mg")
        "2.5mg"   → (2.5, "mg")
        "as directed" → (None, None)
    """
    if not dose_string:
        return None, None
    match = _DOSE_PATTERN.search(dose_string)
    if match:
        return float(match.group("value")), match.group("unit").lower()
    return None, None
```

### Settings additions in `backend/app/core/config.py`

```python
RXNAV_BASE_URL: str = Field(
    default="https://rxnav.nlm.nih.gov/REST",
    description="Base URL for NIH RxNav REST API",
)
RXNAV_TIMEOUT_SECONDS: int = Field(
    default=5,
    description="HTTP timeout for RxNav CUI lookup requests",
)
```

---

## Validation Steps

### Step 1: Live CUI Lookup (requires internet)
```bash
python -c "
import asyncio
from app.agents.medication_reconciliation.rxnorm import RxNormNormaliser

async def main():
    n = RxNormNormaliser()
    cui = await n.normalise('Metformin')
    print(f'Metformin CUI: {cui}')
    assert cui is not None, 'Expected a CUI for Metformin'

    none_cui = await n.normalise('Fictionomycin 200mg')
    assert none_cui is None, 'Expected None for unknown drug'
    print('✓ RxNormNormaliser validated')

asyncio.run(main())
"
```

### Step 2: Cache Hit Verification
```bash
python -c "
import asyncio
from unittest.mock import patch, AsyncMock
from app.agents.medication_reconciliation.rxnorm import RxNormNormaliser

async def main():
    n = RxNormNormaliser()
    with patch.object(n, '_fetch_cui', new_callable=AsyncMock, return_value='12345') as mock:
        await n.normalise('Atorvastatin')
        await n.normalise('atorvastatin')  # different case
        assert mock.call_count == 1, f'Expected 1 call, got {mock.call_count}'
    print('✓ Cache hit validated')

asyncio.run(main())
"
```

### Step 3: Dose Parser
```bash
python -c "
from app.agents.medication_reconciliation.dose_parser import parse_dose

assert parse_dose('500 mg') == (500.0, 'mg')
assert parse_dose('2.5mg') == (2.5, 'mg')
assert parse_dose('as directed') == (None, None)
assert parse_dose(None) == (None, None)
print('✓ DoseParser validated')
"
```

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| RxNav API rate limiting | Low | Medium | RxNav is unrestricted public API; add `asyncio.sleep(0)` yield between concurrent calls if throttled |
| RxNav returns multiple CUIs for ambiguous name | Medium | Low | Always take `rxnormId[0]` (most specific match); document this behaviour |
| Drug names with special characters fail URL encoding | Medium | Medium | Use `httpx` `params=` dict (auto-encodes); test with "Acetaminophen / Codeine" |
| RxNav offline in air-gapped environment | Low | High | Return `None` gracefully; reconciliation proceeds without CUI (falls back to name matching) |

---

## Definition of Done

- [ ] `RxNormNormaliser` class implemented with `normalise` and `normalise_batch`
- [ ] In-process cache working (lowercased key)
- [ ] Timeout and error paths return `None` without raising
- [ ] `DoseParser.parse_dose` implemented and validated for common formats
- [ ] `RXNAV_BASE_URL` and `RXNAV_TIMEOUT_SECONDS` settings added
- [ ] All validation steps pass
- [ ] Code reviewed and approved

---

## Related Tasks

- **TASK-002:** Provides `RawMedicationEntry.name` as input
- **TASK-004:** Reconciliation agent calls `normalise_batch` and `parse_dose`

---

## Notes for Implementer

1. **RxNav endpoint** — Use `GET /REST/rxcui.json?name={drug}&search=1`. The `search=1` flag enables approximate matching (handles "500mg" suffix in name).
2. **CUI stability** — RxNorm CUIs are stable identifiers but can be retired. For production, store the CUI at reconciliation time; do not re-query on every read.
3. **Batch size** — No documented rate limit on RxNav, but limit concurrent requests to 20 at a time using `asyncio.Semaphore(20)` if the patient has an unusually large medication list.
4. **Dose unit normalisation** — The regex covers common abbreviations. Extend `_DOSE_PATTERN` if clinical staff report missed dose units (e.g. `units` for insulin).

---

*Task created on 2026-07-16 for US-030 by plan-development-tasks workflow.*
