"""Shared pollutant identities and release destinations. Legacy names remain readable."""
import json
import re
from pathlib import Path

CATALOGUE = json.loads((Path(__file__).resolve().parents[2] / 'shared/pollutants.json').read_text())
BY_ID = {p['id']: p for p in CATALOGUE}
MEDIA = ('air', 'soil', 'freshwater', 'marine', 'climate')


def normalise(name: str) -> str:
    name = name.lower().translate(str.maketrans('₀₁₂₃₄₅₆₇₈₉ₓ', '0123456789x'))
    return re.sub(r'[^a-z0-9]', '', name)


ALIASES = {normalise(a): p['id'] for p in CATALOGUE for a in [p['id'], p['label'], *p['aliases']]}


def pollutant_id(name: str) -> str:
    key = normalise(name)
    text = name.lower().translate(str.maketrans('₀₁₂₃₄₅₆₇₈₉', '0123456789'))
    if re.search(r'\bco2\s*(?:e(?:q(?:uivalent)?)?|equivalent)\b|carbon\s*dioxide\s*equivalent', text):
        return 'co2e'
    if re.search(r'scope2|scope12|scope1and2|scope1plus2', key):
        return key
    if key in ALIASES:
        return ALIASES[key]
    # Preserve "as NO2" etc. as different mass bases; ordinary descriptive annotations can be ignored.
    if re.search(r'\bas\b', name.lower()):
        return key
    return ALIASES.get(normalise(name.split('(')[0]), key)


def release_medium(name: str, medium: str = 'air') -> str:
    return 'climate' if pollutant_id(name) == 'co2e' else medium
