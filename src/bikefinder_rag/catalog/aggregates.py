"""Catalogue extrema and arithmetic means over an explicit source population.

Select the whole SQL scope before calculating; never aggregate a display page.
Unknown, approximate, conflicting and differently labelled measures stay apart.
"""
from decimal import Decimal
import re

from bikefinder_rag.catalog.enriched import _rows, folded
from bikefinder_rag.catalog.measures import filtered, project

MEASURES = {
    "power_ch": (r"\bpuissance|\bchevaux|\bch\b|\bcv\b", "Puissance", "ch"),
    "displacement_ccm": (r"cylindree|\bcc\b|cm[3³]", "Cylindrée", "cc"),
    "seat_height_mm": (r"selle", "Hauteur de selle", "mm"),
    "weight_dry_kg": (r"poids.*\bsec\b", "Poids à sec", "kg"),
    "weight_wet_kg": (r"poids.*(?:pleins|ordre de marche)", "Poids tous pleins / en ordre de marche", "kg"),
    "price_eur": (r"prix|tarifs?|euros?", "Prix France de base", "€"),
    "torque_nm": (r"couple|\bnm\b", "Couple", "Nm"),
    "autonomy_km": (r"autonomie", "Autonomie documentée", "km"),
}


def requested_aggregate(question):
    text = folded(question)
    operation = "mean" if re.search(r"\bmoyen(?:ne)?s?\b", text) else None
    if not operation:
        # A threshold with a literal number is a filter, not an extremum.
        patterns = [("max", r"maxim(?:ale?s?|um)|plus (?:grosse?|grande?|haute?)"),
                    ("min", r"minim(?:ale?s?|um)|plus (?:petite?|basse?)")]
        for name, pattern in patterns:
            if re.search(pattern, text) and not re.search(
                    r"(?:maximum|minimum|max|min|maximale?|minimale?)\s*(?:(?:de|a|:)\s*)?\d", text):
                operation = name
                break
    if not operation:
        return None
    fields = [field for field, (pattern, _, _) in MEASURES.items() if re.search(pattern, text)]
    return {"operation": operation, "fields": fields} if fields else None


def _fmt(number):
    return format(number, ".3f").rstrip("0").rstrip(".").replace(".", ",")


def _name(row):
    return f"{row['brand']} {row['model']} ({row['year']})".replace("|", "\\|")


def aggregate_rows(conn, plan):
    models = plan.get("models", [])
    if not models:
        rows = filtered(conn, plan.get("conditions", []), identity=plan["identity"],
                        equipment=plan.get("equipment"), status=plan.get("status", "standard"),
                        equipment_filters=plan.get("equipment_filters"), secondary=plan.get("secondary"),
                        limit=100001)
        if len(rows) > 100000:
            raise ValueError("Aggregate population exceeds the bounded full-scope read")
        return rows, []
    if plan.get("conditions") or plan.get("equipment") or plan.get("equipment_filters") or plan.get("secondary"):
        raise ValueError("Named-fiche aggregate with additional filters is not supported")
    rows, missing = {}, []
    for model in models:
        clauses = ["lower(f.brand)=lower(%s)", "lower(f.model)=lower(%s)"]
        params = [model["brand"], model["model"]]
        year = model.get("year", plan["identity"].get("year"))
        if year is not None:
            clauses.append("f.year=%s"); params.append(year)
        else:
            for key, op in [("min_year", ">="), ("max_year", "<=")]:
                if key in plan["identity"]:
                    clauses.append(f"f.year{op}%s"); params.append(plan["identity"][key])
            if "min_year" not in plan["identity"] and not plan.get("all_years"):
                raise ValueError("Explicit aggregate population required")
        found = _rows(conn, "SELECT f.* FROM technical_fiches f WHERE " + " AND ".join(clauses)
                      + " ORDER BY f.year,f.model,f.id", params)
        if not found:
            missing.append(f"{model['brand']} {model['model']} ({year or 'période demandée'})")
        years = [r["year"] for r in found]
        if year is None and "min_year" in plan["identity"] and "max_year" in plan["identity"]:
            missing += [f"{model['brand']} {model['model']} ({y})" for y in range(
                plan['identity']['min_year'], plan['identity']['max_year'] + 1) if y not in years]
        if len(years) != len(set(years)):
            raise ValueError("More than one source fiche per model and year")
        rows.update({r["id"]: r for r in found})
    return list(rows.values()), missing


def render_aggregate(conn, plan):
    request = plan.get("aggregate")
    if not isinstance(request, dict) or request.get("operation") not in {"min", "max", "mean"} or not request.get("fields") or any(
            field not in MEASURES for field in request["fields"]):
        raise ValueError("Unsupported aggregate")
    rows, missing = aggregate_rows(conn, plan)
    output = [f"Calcul sur **{len(rows)} fiches du catalogue**, dans la population demandée."]
    if not rows:
        return "Aucune fiche exacte disponible dans la population demandée ; aucun calcul ni substitution de millésime."
    if missing:
        output.append("Population incomplète : fiche(s) absente(s) — " + "; ".join(missing) + ".")
    values = [(row, *project(row["record"])) for row in rows]
    for field in request["fields"]:
        _, label, unit = MEASURES[field]
        known = [(row, Decimal(str(v[field])), proof[field]) for row, v, proof in values if v[field] is not None]
        output += ["", f"**{label}** — {len(known)}/{len(rows)} valeurs numériques univoques documentées."]
        if len(known) < len(rows):
            output.append("Les valeurs manquantes, approximatives, sous forme d’intervalle ou contradictoires sont exclues du calcul ; elles ne valent pas zéro. Le résultat porte seulement sur les valeurs documentées.")
        if not known:
            output.append("Calcul non établi : aucune valeur exploitable pour cette mesure.")
            continue
        if request["operation"] == "mean":
            total = sum((n for _, n, _ in known), Decimal(0))
            number = total / len(known)
            output.append(f"**Moyenne arithmétique : {_fmt(number)} {unit}** ({_fmt(total)} / {len(known)} ; une fiche compte une fois).")
            selected = known
        else:
            number = (max if request["operation"] == "max" else min)(n for _, n, _ in known)
            selected = [item for item in known if item[1] == number]
            label_op = "Maximum" if request["operation"] == "max" else "Minimum"
            output.append(f"**{label_op} : {_fmt(number)} {unit}** — {len(selected)} fiche(s) ex æquo.")
        output += ["", "| Fiche | Valeur source | Source |", "|---|---|---|"]
        # All ties are shown. A long mean still uses every fiche, while its
        # audit table explicitly states the display limit.
        shown = selected[:50] if request["operation"] == "mean" else selected
        for row, _, proof in shown:
            raw = "; ".join(p["section"] + " — " + p["label"] + " " + p["value"] for p in proof).replace("|", "\\|")
            output.append(f"| {_name(row)} | {raw} | [Fiche]({row['source_url']}) |")
        if len(shown) < len(selected):
            output.append(f"Table limitée à {len(shown)} sources affichées ; les {len(selected)} valeurs ont toutes été incluses dans la moyenne.")
    output += ["", "Périmètre : fiches collectées du catalogue, sans exhaustivité du marché. Les types de poids et les unités restent séparés ; aucune conversion implicite."]
    return "\n".join(output)
