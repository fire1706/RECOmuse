"""Tests des rythmes de la lecture vectorielle (pages fabriquées, voir vector_builder).

Durées en noires : 1 = noire, 1/2 = croche, 3/2 = noire pointée, 4 = ronde.
"""

from fractions import Fraction

from recomuse.vector.reader import interpret_page, new_part_state
from recomuse.vector.score import VectorScore

from vector_builder import (
    BLACK,
    HALF,
    HALF_REST,
    PERCUSSION,
    QUARTER_REST,
    SHARP,
    TREBLE,
    WHOLE,
    WHOLE_REST,
    PageBuilder,
)

F = Fraction


def page_with_staff(time=("4", "4"), barlines=(300, 550), clef=TREBLE):
    """Une portée en clé de sol avec chiffrage ; 1re mesure de 85 à 300, 2e de 300 à 550."""
    page = PageBuilder()
    page.staff(100, barlines=list(barlines))
    page.glyph(0, clef, 55, 2 if clef == TREBLE else 4)
    if time:
        page.time(0, 70, *time)
    return page


def read(page, states=None):
    return interpret_page(page.build(), 1, states)


def first_measures(page, states=None):
    return read(page, states).systems[0][0].measures


def durations(measure):
    return [e.duration for e in measure.events()]


# --- Valeurs de base ------------------------------------------------------------------------


def test_heads_flags_and_rests():
    page = page_with_staff()
    page.note(0, 90, 4, code=WHOLE)                          # ronde
    page.note(0, 310, 4, code=HALF)                          # blanche
    page.note(0, 360, 4)                                     # noire
    page.note(0, 400, 4, flags=1)                            # croche
    page.note(0, 430, 4, flags=2)                            # double croche
    page.glyph(0, 0xC5, 480, 4)                              # quart de soupir
    bars = first_measures(page)
    assert durations(bars[0]) == [4]
    assert durations(bars[1]) == [2, 1, F(1, 2), F(1, 4), F(1, 4)]
    assert bars[0].duration_ok is True
    assert bars[1].duration_ok is True


def test_beamed_eighths_and_sixteenths():
    page = page_with_staff()
    stems = [page.note(0, x, 4) for x in (90, 110, 130, 150)]
    page.beam(0, stems[0], stems[3], count=1)                 # 4 croches
    stems = [page.note(0, x, 4) for x in (170, 185, 200, 215)]
    page.beam(0, stems[0], stems[3], count=2)                 # 4 doubles croches
    page.note(0, 240, 4)
    bars = first_measures(page)
    assert durations(bars[0]) == [F(1, 2)] * 4 + [F(1, 4)] * 4 + [1]
    assert bars[0].duration_ok is True


def test_stems_down_are_found():
    page = page_with_staff()
    stems = [page.note(0, x, 7, stem="down") for x in (90, 110)]
    page.beam(0, stems[0], stems[1], up=False)
    page.note(0, 140, 7, stem="down", code=HALF)
    page.note(0, 200, 7, stem="down")
    bars = first_measures(page)
    assert durations(bars[0]) == [F(1, 2), F(1, 2), 2, 1]
    assert {n.stem for n in bars[0].notes} == {"down"}


# --- Points, accords, nolets ----------------------------------------------------------------


def test_dotted_notes_and_rests():
    page = page_with_staff()
    page.note(0, 90, 4)
    page.dot(0, 98, 5)                                       # noire pointée (point dans l'interligne)
    page.note(0, 120, 4, flags=1)                            # croche
    page.glyph(0, HALF_REST, 160, 4)
    page.dot(0, 168, 5)                                      # demi-pause pointée... trop long !
    bars = first_measures(page)
    assert durations(bars[0]) == [F(3, 2), F(1, 2), 3]
    assert bars[0].events()[0].dots == 1
    assert bars[0].duration_ok is False


def test_double_dot():
    page = page_with_staff(time=("2", "4"))
    page.note(0, 90, 4)
    page.dot(0, 98, 5)
    page.dot(0, 101, 5)
    page.note(0, 140, 4, flags=2)
    bars = first_measures(page)
    assert durations(bars[0]) == [F(7, 4), F(1, 4)]


def test_chord_shares_one_stem_and_one_column_of_dots():
    """Accord pointé : chaque tête a son point, mais il n'y a qu'un point de prolongation."""
    page = page_with_staff(time=("3", "4"))
    page.note(0, 90, 2, code=HALF)                           # la plus basse porte la hampe
    page.glyph(0, HALF, 90, 4)
    page.glyph(0, HALF, 90, 6)
    for position in (3, 5, 7):                               # un point par tête, même colonne
        page.dot(0, 98, position)
    bars = first_measures(page)
    notes = bars[0].notes
    assert len(notes) == 3
    assert [n.chord for n in sorted(notes, key=lambda n: n.position)] == [False, True, True]
    assert {n.duration for n in notes} == {3}
    assert durations(bars[0]) == [3]                         # un seul événement
    assert bars[0].duration_ok is True


def test_triplet_with_digit_glyph():
    page = page_with_staff(time=("2", "4"))
    stems = [page.note(0, x, 4) for x in (90, 110, 130)]
    page.beam(0, stems[0], stems[2])
    page.glyph(0, 0x33, 112, 13)                             # « 3 » au-dessus
    page.note(0, 200, 4)
    bars = first_measures(page)
    assert durations(bars[0]) == [F(1, 3)] * 3 + [1]
    assert bars[0].notes[0].tuplet == (3, 2)
    assert bars[0].duration_ok is True


def test_triplet_written_with_a_text_font():
    page = page_with_staff(time=("2", "4"))
    for x in (90, 115, 140):
        page.note(0, x, 4)                                   # triolet de noires, sans ligature
    page.text("3", 113, 76, 118, 84)
    bars = first_measures(page)
    assert durations(bars[0]) == [F(2, 3)] * 3
    assert bars[0].duration_ok is True


def test_digit_is_ignored_when_the_measure_is_already_complete():
    """Un « 3 » isolé (doigté, numéro) n'est pas un triolet si la mesure est déjà juste."""
    page = page_with_staff(time=("2", "4"))
    page.note(0, 90, 4)
    page.note(0, 140, 4)
    page.text("3", 140, 76, 145, 84)
    bars = first_measures(page)
    assert durations(bars[0]) == [1, 1]


# --- Liaisons ---------------------------------------------------------------------------------


def test_tie_across_barline_keeps_the_accidental():
    page = page_with_staff()
    page.glyph(0, SHARP, 255, 1)
    page.note(0, 260, 1, code=HALF)                          # fa♯4, fin de mesure
    page.note(0, 310, 1, code=HALF)                          # fa4 lié : reste fa♯4
    page.note(0, 360, 1, code=HALF)                          # fa4 non lié : fa naturel
    head_y = page.y(0, 1)
    page.tie(260 + 7, head_y + 2, 308, head_y + 2)
    bars = first_measures(page)
    assert bars[0].notes[-1].tie_start
    tied, free = bars[1].notes
    assert tied.tie_stop and tied.name == "F#4"
    assert free.name == "F4"


def test_slur_between_different_pitches_is_not_a_tie():
    page = page_with_staff()
    page.note(0, 90, 1)
    page.note(0, 120, 3)
    page.tie(97, page.y(0, 1) + 2, 118, page.y(0, 3) + 2)
    bars = first_measures(page)
    assert not any(n.tie_start or n.tie_stop for n in bars[0].notes)


def test_tie_to_the_next_system_keeps_the_accidental():
    page = page_with_staff()
    page.glyph(0, SHARP, 495, 1)
    page.note(0, 500, 1, code=HALF)                          # fa♯4 en fin de ligne
    page.tie(507, page.y(0, 1) + 2, 549, page.y(0, 1) + 2)   # liaison qui sort de la ligne
    page.staff(200, barlines=[550])
    page.glyph(1, TREBLE, 55, 2)
    page.note(1, 100, 1, code=HALF)                          # fa4 en début de ligne suivante
    page.tie(85, page.y(1, 1) + 2, 98, page.y(1, 1) + 2)     # liaison qui entre
    vector = read(page)
    first_note = vector.systems[1][0].measures[0].notes[0]
    assert first_note.tie_stop
    assert first_note.name == "F#4"


# --- Mesures, voix, petites notes ------------------------------------------------------------


def test_time_signature_continues_on_the_next_page():
    states = {}
    page1 = page_with_staff(time=("3", "4"))
    page1.note(0, 90, 4, code=HALF)
    page1.note(0, 200, 4)
    read(page1, states)
    page2 = page_with_staff(time=None)                       # pas de chiffrage réécrit
    page2.note(0, 90, 4, code=HALF)
    page2.note(0, 200, 4)
    bars = first_measures(page2, states)
    assert bars[0].expected_duration == 3
    assert bars[0].duration_ok is True


def test_whole_rest_fills_any_measure():
    page = page_with_staff(time=("3", "4"))
    page.glyph(0, WHOLE_REST, 150, 4)
    bars = first_measures(page)
    assert bars[0].full_rest and bars[0].duration == 3


def test_two_voices_on_one_staff():
    """Voix du dessus en noires (hampes en haut), voix du dessous en blanches (en bas)."""
    page = page_with_staff()
    for x in (90, 140, 190, 240):
        page.note(0, x, 7)
    page.note(0, 90, 1, code=HALF, stem="down")
    page.note(0, 190, 1, code=HALF, stem="down")
    bars = first_measures(page)
    assert bars[0].voices == 2
    assert bars[0].duration_ok is True
    assert {n.voice for n in bars[0].notes if n.position == 1} == {2}


def test_whole_note_below_a_voice_with_stems_up():
    page = page_with_staff()
    page.note(0, 90, 0, code=WHOLE)
    page.glyph(0, QUARTER_REST, 92, 8)                       # silence décalé vers le haut
    page.note(0, 140, 6, code=HALF)
    page.note(0, 200, 6)
    bars = first_measures(page)
    assert bars[0].voices == 2
    assert bars[0].duration_ok is True


def test_grace_note_does_not_count():
    page = page_with_staff(time=("1", "4"))
    page.note(0, 90, 5, size=12, flags=1)                    # appoggiature
    page.note(0, 100, 4)
    bars = first_measures(page)
    assert bars[0].notes[0].grace
    assert bars[0].duration == 1


def test_cue_notes_fill_the_measure():
    """Notes de réplique (petites) qui remplissent la mesure : elles comptent."""
    page = page_with_staff(time=("2", "4"))
    page.note(0, 90, 4, size=15)
    page.note(0, 140, 4, size=15)
    bars = first_measures(page)
    assert all(n.cue and not n.grace for n in bars[0].notes)
    assert bars[0].duration_ok is True


def test_courtesy_key_at_the_end_of_a_line_is_not_a_measure():
    page = page_with_staff(barlines=(300, 500))              # portée jusqu'à 550, sans barre finale
    page.note(0, 90, 4, code=WHOLE)
    page.note(0, 320, 4, code=WHOLE)
    page.key(0, 510, [8, 5])                                 # armure de rappel
    bars = first_measures(page)
    assert len(bars) == 2


def test_percussion_measures_are_not_checked():
    page = page_with_staff(clef=PERCUSSION)
    page.note(0, 90, 4)
    bars = first_measures(page)
    assert bars[0].duration_ok is None


def test_stem_missing_is_reported():
    page = page_with_staff()
    page.note(0, 90, 4, stem=None)
    vector = read(page)
    assert "stem_missing" in vector.warnings


# --- Résumé par partie ----------------------------------------------------------------------


def test_pickup_measure_is_not_a_mismatch():
    page = page_with_staff()
    page.note(0, 90, 4)                                      # levée d'un temps
    page.note(0, 310, 4, code=WHOLE)
    page.staff(200, barlines=[300, 550])
    page.glyph(1, TREBLE, 55, 2)
    page.note(1, 100, 4, code=HALF)                          # mesure trop courte : erreur
    page.note(1, 320, 4, code=WHOLE)
    score = VectorScore(source_path=None, pages=[read(page)])
    assert score.duration_mismatches() == [3]
    assert score.to_dict()["duration_mismatches"] == [3]


def test_new_part_state():
    assert new_part_state() == {"clef": None, "clef_position": None, "key": 0, "time": None,
                                "pending_ties": {}}
    assert BLACK == 0xCF
