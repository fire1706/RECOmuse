"""Conducteurs : une partition où chaque système réunit tous les instruments.

- instrument_groups : les instruments d'un conducteur, chacun avec ses portées (le piano
  en a deux, réunies par le même nom) ;
- extract_parts : une partie séparée par instrument, tirée d'un conducteur lu (avec les
  corrections déjà faites sur le conducteur) ;
- assemble : un conducteur fait de parties séparées d'un même morceau (une partie par
  instrument), pour l'exporter vers MuseScore ou l'imprimer.

Le conducteur assemblé n'a pas de pages d'origine (ses parties viennent de fichiers
différents) : la vue côte à côte n'en montre que le rendu.
"""

from copy import deepcopy

from recomuse.instruments.table import InstrumentTable, load_table
from recomuse.model.score import Part, ScoreModel


def instrument_groups(model: ScoreModel) -> list[list[Part]]:
    """Portées de chaque instrument, dans l'ordre : des portées voisines de même nom (le
    piano) forment un seul instrument ; une portée sans nom est un instrument à elle."""
    groups: list[list[Part]] = []
    for part in model.parts:
        if not part.measures:
            continue
        if groups and part.name and groups[-1][0].name == part.name:
            groups[-1].append(part)
        else:
            groups.append([part])
    return groups


def is_conductor(model: ScoreModel) -> bool:
    """Vrai si la partition réunit plusieurs instruments."""
    return len(instrument_groups(model)) > 1


def extract_parts(model: ScoreModel) -> list[ScoreModel]:
    """Une partition par instrument du conducteur (copies : le conducteur ne change pas)."""
    result = []
    for group in instrument_groups(model):
        name = group[0].name
        parts = [Part(id=f"P{k + 1}", name=name, measures=deepcopy(part.measures),
                      instrument_id=part.instrument_id, variant_id=part.variant_id)
                 for k, part in enumerate(group)]
        result.append(ScoreModel(
            title=model.title, composers=list(model.composers), instrument=name,
            tempo=model.tempo, source_path=model.source_path, parts=parts,
            pages=deepcopy(model.pages), instrument_id=group[0].instrument_id,
            variant_id=group[0].variant_id, derived="extracted"))
    return result


def assemble(scores: list[tuple[int, ScoreModel]],
             table: InstrumentTable | None = None) -> ScoreModel:
    """Conducteur fait des parties `scores` ((numéro, modèle) de chaque partie), dans
    l'ordre habituel d'un conducteur (celui de la table des instruments : bois, cuivres,
    accompagnement, percussions), puis par nom (Trompette 1 avant Trompette 2).

    Les identifiants des mesures et des symboles reçoivent le numéro de leur partie
    (« s12-v3.0.0.0 ») : deux fichiers lus séparément peuvent avoir les mêmes."""
    table = table or load_table()
    order = {instrument.id: rank for rank, instrument in enumerate(table.instruments)}

    def rank(item: tuple[int, ScoreModel]) -> tuple:
        score_id, model = item
        name = model.instrument or (model.parts[0].name if model.parts else None)
        instrument = table.get(model.instrument_id) or table.find(name)
        return (order.get(instrument.id, len(order)) if instrument else len(order),
                name or "", score_id)

    parts: list[Part] = []
    # Titre, compositeurs et tempo : ceux de la première partie qui en a un.
    first = next((model for _, model in scores if model.title),
                 scores[0][1] if scores else ScoreModel())
    for score_id, model in sorted(scores, key=rank):
        name = model.instrument or (model.parts[0].name if model.parts else None)
        for part in instrument_groups(model):
            for staff in part:
                measures = deepcopy(staff.measures)
                for measure in measures:
                    measure.id = f"s{score_id}-{measure.id}"
                    measure.page, measure.bbox = None, None
                    for symbol in measure.symbols():
                        symbol.id = f"s{score_id}-{symbol.id}"
                        symbol.page, symbol.bbox = None, None
                parts.append(Part(id=f"P{len(parts) + 1}", name=staff.name or name,
                                  measures=measures,
                                  instrument_id=staff.instrument_id or model.instrument_id,
                                  variant_id=staff.variant_id or model.variant_id))
    result = ScoreModel(title=first.title, composers=list(first.composers),
                        tempo=first.tempo, parts=parts, pages=[], derived="assembled",
                        derived_from=[score_id for score_id, _ in scores])
    result.refresh()
    return result
