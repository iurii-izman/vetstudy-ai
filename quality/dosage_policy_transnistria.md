# Dosage Policy: Transnistria Private Beta

Scope: private educational beta for virtual veterinary cases. The assistant may help calculate and explain doses only when the answer is source-backed and explicitly framed as study support, not a prescription for a real animal.

## Regional Rule

For Transnistria, use a Moldova-first regulatory check:

1. Check the exact product or active substance in the ANSA Moldova State Register of Veterinary Medicinal Products.
2. If the ANSA item references EMA or the product is EU/EMA-authorised, verify the official product information/SPC in EU/EMA sources.
3. If the exact local product label/package leaflet is available from the owner/student, prefer that label for final route, dose, species, contraindications, interactions, withdrawal period, and storage details.
4. If only a generic active substance is known, treat the answer as incomplete and ask for the exact trade name, concentration, pharmaceutical form, target species, and indication.

## Required Inputs Before Numeric Dose

Do not calculate a numeric dose unless the prompt or case provides:

- species;
- body weight;
- age/life stage and pregnancy/lactation status when relevant;
- indication or suspected diagnosis;
- exact drug, trade name when available, formulation and concentration;
- route and dosing interval requested or supported by source;
- relevant comorbidities, especially renal/hepatic disease, dehydration, GI ulcer risk, seizures, cardiac disease;
- current medicines/supplements and recent NSAID/steroid/anticoagulant exposure.

## Source Requirements

For routine study cases, numeric doses require at least one authoritative dosing source:

- exact product label/SPC/package leaflet; or
- licensed veterinary formulary such as Plumb's Veterinary Drugs or BSAVA Small Animal Formulary; or
- official veterinary product information from EMA/EU UPD when it matches the product/species/route.

For high-risk categories, require stronger support or mark `needs_manual_check`:

- cats and NSAIDs;
- aminoglycosides, anticoagulants, sedatives/anesthetics, opioids;
- toxicology and antidotes;
- renal/hepatic impairment;
- food-producing animals and withdrawal periods;
- off-label/extralabel use;
- compounding or human medicines used in animals.

## Output Requirements

When a numeric dose is allowed, answer in this structure:

1. Short study-only caveat.
2. Source basis: product label/SPC/formulary and region relevance.
3. Dose in mg/kg or source unit.
4. Calculation for the provided body weight.
5. Conversion to formulation amount only if concentration is known.
6. Contraindications, interactions, monitoring, and stop/escalation criteria.
7. `needs_manual_check` if source match, patient data, or regional availability is incomplete.

Never present a dose as a real prescription, and never hide uncertainty behind confident wording.
