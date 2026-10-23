"""Tests de l'interprétation d'une page vectorielle (pages fabriquées, voir vector_builder)."""

from recomuse.vector.reader import interpret_page

from vector_builder import (
    BASS,
    COMMON_TIME,
    FLAT,
    HALF,
    HBAR,
    NATURAL,
    PERCUSSION,
    QUARTER_REST,
    SHARP,
    TREBLE,
    TREBLE_FLATS,
    TREBLE_SHARPS,
    WHOLE,
    WHOLE_REST,
    PageBuilder,
)


def part_page(key_positions=None, key_code=SHARP, time=("3", "4"), barlines=(200, 350, 550)):
    """Une portée de partie : clé de sol, armure, chiffrage, 3 mesures (à remplir)."""
    page = PageBuilder()
    page.staff(100, barlines=list(barlines))
    page.glyph(0, TREBLE, 55, 2)
    x = 75
    if key_positions:
        page.key(0, x, key_positions, key_code)
        x += 5 * len(key_positions) + 5
    if time:
        page.time(0, x, *time)
    return page


def measures(page, staff=0):
    vector = interpret_page(page.build(), 1)
    return vector, vector.systems[staff][0].measures


def names(measure):
    return [n.name for n in measure.notes]


def test_structure_of_a_part():
    page = part_page(key_positions=TREBLE_SHARPS[:2])
    page.note(0, 130, 0)                     # mi4
    vector, bars = measures(page)
    assert len(bars) == 3
    assert bars[0].clef == "treble"
    assert bars[0].key_fifths == 2
    assert bars[0].time_signature == "3/4"
    assert vector.warnings == []


def test_pitches_with_key_and_accidentals():
    """Ré majeur (fa♯, do♯) : les notes prennent l'armure ; une altération écrite vaut
    jusqu'à la fin de la mesure, et pas au-delà."""
    page = part_page(key_positions=TREBLE_SHARPS[:2])
    page.note(0, 130, 1)                     # fa4 → fa♯4 par l'armure
    page.glyph(0, NATURAL, 146, 5)           # bécarre devant do5
    page.note(0, 150, 5)                     # do♮5
    page.note(0, 170, 5)                     # do5 : le bécarre vaut encore
    page.glyph(0, SHARP, 186, 4)
    page.note(0, 190, 4)                     # si♯4
    page.note(0, 220, 5)                     # mesure suivante : do♯5 (armure)
    page.note(0, 240, 4)                     # si4 (le dièse ne vaut plus)
    _, bars = measures(page)
    assert names(bars[0]) == ["F#4", "C5", "C5", "B#4"]
    assert bars[0].notes[1].accidental == "natural"
    assert names(bars[1]) == ["C#5", "B4"]


def test_ledger_lines_and_bass_clef():
    page = PageBuilder()
    page.staff(100)
    page.glyph(0, BASS, 55, 6)
    page.note(0, 100, -2)                    # 1re ligne supplémentaire sous la clé de fa : mi2
    page.note(0, 130, 10)                    # 1re au-dessus : do4
    _, bars = measures(page)
    assert names(bars[0]) == ["E2", "C4"]


def test_heads_and_small_notes():
    page = part_page()
    page.note(0, 130, 4, code=HALF)
    page.note(0, 150, 4, code=WHOLE)
    page.note(0, 175, 5, size=12)            # appoggiature (petite tête)
    _, bars = measures(page)
    assert [n.head for n in bars[0].notes] == ["half", "whole", "black"]
    assert [n.small for n in bars[0].notes] == [False, False, True]


def test_key_signature_followed_by_the_same_note():
    """4 dièses puis un ré : le 4e dièse (ré) appartient à l'armure, pas à la note."""
    page = part_page(key_positions=TREBLE_SHARPS[:4], time=None)
    page.note(0, 99, 6)                      # ré5, tout près du dernier dièse
    _, bars = measures(page)
    assert bars[0].key_fifths == 4
    assert names(bars[0]) == ["D#5"]
    assert bars[0].notes[0].accidental is None


def test_single_accidental_before_first_note_is_the_note_s():
    """Pas d'armure ; un fa♯ en tête de 2e mesure est l'altération de la note."""
    page = part_page()
    page.glyph(0, SHARP, 207, 8)
    page.note(0, 213, 8)
    _, bars = measures(page)
    assert bars[1].key_fifths is None
    assert names(bars[1]) == ["F#5"]


def test_key_change_with_cancellation():
    """2 bémols, puis en 2e mesure : 2 bécarres et 3 dièses."""
    page = part_page(key_positions=TREBLE_FLATS[:2], key_code=FLAT)
    page.note(0, 130, 4)                     # si♭4
    page.key(0, 205, TREBLE_FLATS[:2], NATURAL)
    page.key(0, 215, TREBLE_SHARPS[:3], SHARP)
    page.note(0, 240, 9)                     # sol5 → sol♯5
    _, bars = measures(page)
    assert bars[0].key_fifths == -2
    assert names(bars[0]) == ["Bb4"]
    assert bars[1].key_fifths == 3
    assert names(bars[1]) == ["G#5"]


def test_time_signatures():
    page = part_page(time=("6", "8"))
    page.time(0, 210, "12", "8")             # changement en 2e mesure, nombre à 2 chiffres
    page.glyph(0, COMMON_TIME, 360, 4)       # « C » en 3e mesure
    _, bars = measures(page)
    assert [b.time_signature for b in bars] == ["6/8", "12/8", "4/4"]


def test_time_signature_digits_placed_by_another_font():
    """Police Jazz : les chiffres ne sont pas aux positions 6 et 2, mais toujours superposés."""
    page = part_page(time=None)
    page.time(0, 80, "4", "4", positions=(7.2, 3.9))
    _, bars = measures(page)
    assert bars[0].time_signature == "4/4"


def test_single_row_of_digits_is_not_a_time_signature():
    page = part_page(time=None)
    page.glyph(0, 0x33, 140, 4)              # un « 3 » isolé dans la portée
    _, bars = measures(page)
    assert bars[0].time_signature is None


def test_multirest_with_glyph_and_digits():
    page = part_page()
    page.glyph(0, HBAR, 260, 4)
    page.glyph(0, 0x31, 270, 11)             # « 12 » au-dessus de la portée
    page.glyph(0, 0x32, 274, 11)
    _, bars = measures(page)
    assert bars[1].is_multirest and bars[1].multirest == 12
    assert bars[1].length == 12


def test_multirest_drawn_with_number_in_text():
    page = part_page()
    page.shape(220, 108, 330, 112)           # barre épaisse sur la ligne du milieu
    page.text("8", 270, 85, 276, 95)         # nombre en police de texte, au-dessus
    _, bars = measures(page)
    assert bars[1].is_multirest and bars[1].multirest == 8
    assert bars[1].texts == []


def test_multirest_without_number_is_reported():
    page = part_page()
    page.shape(220, 108, 330, 112)
    vector, bars = measures(page)
    assert bars[1].is_multirest and bars[1].multirest is None
    assert "multirest_count_missing" in vector.warnings


def test_beam_in_a_measure_with_notes_is_not_a_multirest():
    page = part_page()
    page.note(0, 230, 4)
    page.note(0, 260, 4)
    page.shape(236, 108, 266, 111)           # ligature à la hauteur de la ligne du milieu
    _, bars = measures(page)
    assert not bars[1].is_multirest


def test_rests():
    page = part_page()
    page.glyph(0, QUARTER_REST, 130, 4)
    page.note(0, 150, 4)
    page.glyph(0, WHOLE_REST, 270, 4)
    _, bars = measures(page)
    assert [r.value for r in bars[0].rests] == ["quarter"]
    assert not bars[0].full_rest
    assert bars[1].full_rest


def test_percussion_staff_has_no_pitch():
    page = PageBuilder()
    page.staff(100)
    page.glyph(0, PERCUSSION, 55, 4)
    page.note(0, 120, 3)
    vector, bars = measures(page)
    assert bars[0].clef == "percussion"
    assert bars[0].notes[0].step is None
    assert bars[0].notes[0].position == 3
    assert "no_clef" not in vector.warnings


def test_missing_clef_is_reported_and_treble_assumed():
    page = PageBuilder()
    page.staff(100)
    page.note(0, 120, 0)
    vector, bars = measures(page)
    assert "no_clef" in vector.warnings
    assert names(bars[0]) == ["E4"]


def test_doubled_system_line_does_not_create_a_measure():
    page = part_page(barlines=(53, 200, 550))  # trait 3 points après le début de la portée
    _, bars = measures(page)
    assert len(bars) == 2
    assert bars[0].clef == "treble"


def test_texts_header_and_measure_numbers():
    page = part_page()
    page.text("MARCHE D'ACOZ", 200, 20, 400, 40, size=20)  # au-dessus de tout : en-tête
    page.text("Flûte 1", 50, 60, 90, 70)
    page.text("5", 202, 88, 206, 96)                       # n° de mesure, début de mesure
    page.text("Allegro", 60, 88, 90, 96)                   # tempo au-dessus de la portée
    vector, bars = measures(page)
    # Tout ce qui est au-dessus de la 1re portée est dans l'en-tête, tempo compris.
    assert [t.text for t in vector.header_lines] == ["MARCHE D'ACOZ", "Flûte 1", "5", "Allegro"]
    assert bars[1].printed_number == 5
    assert bars[0].texts == ["Allegro"]


def test_glyphs_left_of_the_staff_are_ignored():
    """« B♭ Cl. » : le bémol du nom d'instrument est écrit avec la police de musique."""
    page = part_page()
    page.glyph(0, FLAT, 20, 4)
    _, bars = measures(page)
    assert bars[0].key_fifths is None


def test_clef_and_key_continue_on_the_next_system():
    page = part_page(key_positions=TREBLE_SHARPS[:1])
    page.staff(200)                          # 2e système, rien de réécrit (cas rare)
    page.note(1, 120, 1)                     # fa4 → fa♯4
    vector = interpret_page(page.build(), 1)
    second = vector.systems[1][0]
    assert second.measures[0].notes[0].name == "F#4"


def test_page_without_staff():
    page = PageBuilder()
    page.text("Instrumentation", 100, 100, 200, 110)
    vector = interpret_page(page.build(), 3)
    assert vector.systems == []
    assert vector.warnings == ["no_staff_found"]
    assert vector.page_number == 3


def test_unreadable_music_font():
    page = part_page()
    page.glyphs.clear()
    page.unknown_fonts.append("font00000000116482c8")
    vector = interpret_page(page.build(), 1)
    assert vector.systems == []
    assert vector.warnings == ["unreadable_music_font"]
