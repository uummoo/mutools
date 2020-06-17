import abjad
import bisect
import functools
import itertools
import operator

try:
    import quicktions as fractions
except ImportError:
    import fractions

import crosstrainer

from mu.mel import ji
from mu.sco import old
from mu.utils import tools

from . import attachments

"""This module contains small functions that may help to generate scores with abjad.

The main focus are functions that may help to convert algorithmically generated abstract
musical data to a form thats closer to notation (where suddenly questions about
time signature, beams, ties and accidentals are occuring).
"""


class NOvent(old.Ovent):
    _available_attachments = {at.name: at for at in attachments.ALL_ATTACHMENTS}

    def __init__(self, *args, **kwargs) -> None:
        new_kwargs = {}

        obj_attachments = {name: None for name in self._available_attachments}
        for kwarg in kwargs:
            if kwarg in obj_attachments:
                obj_attachments.update({kwarg: kwargs[kwarg]})
            else:
                new_kwargs.update({kwarg: kwargs[kwarg]})

        for attachment in obj_attachments:
            setattr(self, attachment, obj_attachments[attachment])

        super().__init__(*args, **new_kwargs)

    @property
    def attachments(self) -> tuple:
        return tuple(
            filter(
                lambda x: bool(x),
                (getattr(self, name) for name in self._available_attachments),
            )
        )


class NOventLine(old.AbstractLine):
    """A NOventLine contains sequentially played NOvents."""

    _object = NOvent()


def mk_no_time_signature():
    return abjad.LilyPondLiteral("override Score.TimeSignature.stencil = ##f", "before")


def mk_numeric_ts() -> abjad.LilyPondLiteral:
    return abjad.LilyPondLiteral("numericTimeSignature", "before")


def mk_staff(voices, clef="percussion") -> abjad.Staff:
    staff = abjad.Staff([])
    for v in voices:
        staff.append(v)
    clef = abjad.Clef(clef)
    abjad.attach(clef, staff)
    abjad.attach(mk_numeric_ts(), staff[0][0])
    return staff


def mk_cadenza():
    return abjad.LilyPondLiteral("\\cadenzaOn", "before")


def mk_bar_line() -> abjad.LilyPondLiteral:
    return abjad.LilyPondLiteral('bar "|"', "after")


def seperate_by_grid(
    start: fractions.Fraction,
    stop: fractions.Fraction,
    grid: tuple,
    hard_cut: bool = False,
) -> tuple:
    def detect_data(i: int, group: int) -> tuple:
        if i == 0:
            diff = start - absolute_grid[group]
            new_delay = grid[group] - diff
            is_connectable = any((start in absolute_grid, new_delay.denominator <= 4))
        elif i == len(passed_groups) - 1:
            new_delay = stop - absolute_grid[group]
            is_connectable = any((stop in absolute_grid, new_delay.denominator <= 4))
        else:
            new_delay = grid[group]
            is_connectable = True

        return is_connectable, new_delay

    absolute_grid = tools.accumulate_from_zero(grid)
    grid_start = bisect.bisect_right(absolute_grid, start) - 1
    grid_stop = bisect.bisect_right(absolute_grid, stop)
    passed_groups = tuple(range(grid_start, grid_stop, 1))

    if len(passed_groups) == 1:
        return (stop - start,)

    else:
        if hard_cut:
            # TODO(make this less ugly)

            for position, item in enumerate(absolute_grid):
                if item > start:
                    break
                else:
                    start_position = position

            positions = [start] + list(
                absolute_grid[
                    start_position + 1 : start_position + len(passed_groups) + 1
                ]
            )
            if stop == positions[-2]:
                positions = positions[:-1]
            else:
                positions[-1] = stop
            return tuple(b - a for a, b in zip(positions, positions[1:]))

        else:
            delays = []
            is_connectable_per_delay = []
            for i, group in enumerate(passed_groups):
                is_connectable, new_delay = detect_data(i, group)
                if new_delay > 0:
                    delays.append(new_delay)
                    is_connectable_per_delay.append(is_connectable)

            length_delays = len(delays)
            if length_delays == 1:
                return tuple(delays)

            connectable_range = [int(not is_connectable_per_delay[0]), length_delays]

            if not is_connectable_per_delay[-1]:
                connectable_range[-1] -= 1

            solutions = [((n,), m) for n, m in enumerate(delays)]
            for item0 in range(*connectable_range):
                for item1 in range(item0 + 1, connectable_range[-1] + 1):
                    connected = sum(delays[item0:item1])
                    if abjad.Duration(connected).is_assignable:
                        sol = (tuple(range(item0, item1)), connected)
                        if sol not in solutions:
                            solutions.append(sol)

            possibilites = crosstrainer.Stack(fitness="min")
            amount_connectable_items = len(delays)
            has_found = False
            lsolrange = tuple(range(len(solutions)))

            for combsize in range(1, amount_connectable_items + 1):

                for comb in itertools.combinations(lsolrange, combsize):

                    pos = tuple(solutions[idx] for idx in comb)
                    items = functools.reduce(operator.add, tuple(p[0] for p in pos))
                    litems = len(items)
                    is_unique = litems == len(set(items))

                    if is_unique and litems == amount_connectable_items:
                        sorted_pos = tuple(
                            item[1] for item in sorted(pos, key=lambda x: x[0][0])
                        )
                        fitness = len(sorted_pos)
                        possibilites.append(sorted_pos, fitness)
                        has_found = True

                if has_found:
                    break

            result = possibilites.best[0]
            return tuple(result)


def seperate_by_assignability(
    duration: fractions.Fraction,
    max_duration: fractions.Fraction = fractions.Fraction(1, 1),
) -> tuple:
    def find_sum_in_numbers(numbers, solution) -> tuple:
        result = []
        # from smallest biggest to smallest
        nums = reversed(sorted(numbers))
        current_num = next(nums)
        while sum(result) != solution:
            if sum(result) + current_num <= solution:
                result.append(current_num)
            else:
                current_num = next(nums)
        return tuple(result)

    # easy claim for standard note duration
    if abjad.Duration(duration).is_assignable and duration <= max_duration:
        return (abjad.Duration(duration),)

    # top and bottom
    numerator = duration.numerator
    denominator = duration.denominator

    # we only need note durations > 1 / denominator
    possible_durations = [
        fractions.Fraction(i, denominator)
        for i in range(1, numerator + 1)
        # only standard note durations
        if abjad.Duration(i, denominator).is_assignable
        and (i / denominator) <= max_duration
    ]

    # find the right combination
    solution = find_sum_in_numbers(possible_durations, duration)
    return solution


def apply_beams(notes, durations, absolute_grid) -> tuple:
    duration_positions = []
    absolute_durations = tuple(itertools.accumulate([0] + list(durations)))
    for dur in absolute_durations:
        pos = bisect.bisect_right(absolute_grid, dur) - 1
        duration_positions.append(pos)
    beam_indices = []
    current = None
    for idx, pos in enumerate(duration_positions):
        if pos != current:
            beam_indices.append(idx)
            current = pos
    for idx0, idx1 in zip(beam_indices, beam_indices[1:]):
        if idx1 == beam_indices[-1]:
            subnotes = notes[idx0:]
        else:
            subnotes = notes[idx0:idx1]
        add_beams = False
        for n in subnotes:
            if type(n) != abjad.Rest:
                add_beams = True
                break
        if len(subnotes) < 2:
            add_beams = False
        if add_beams is True:
            abjad.attach(abjad.Beam(), subnotes)
    return notes


def convert_abjad_pitches_and_mu_rhythms2abjad_notes(
    harmonies: list, delays: list, grid
) -> list:
    leading_pulses = grid.leading_pulses
    absolute_leading_pulses = tuple(itertools.accumulate([0] + list(leading_pulses)))
    converted_delays = grid.apply_delay(delays)
    absolute_delays = tuple(itertools.accumulate([0] + list(converted_delays)))
    # 1. generate notes
    notes = abjad.Measure(abjad.TimeSignature(grid.absolute_meter), [])
    resulting_durations = []
    for harmony, delay, start, end in zip(
        harmonies, converted_delays, absolute_delays, absolute_delays[1:]
    ):
        subnotes = abjad.Voice()
        seperated_by_grid = seperate_by_grid(
            delay, start, end, absolute_leading_pulses, leading_pulses, grid
        )
        assert sum(seperated_by_grid) == delay
        for d in seperated_by_grid:
            seperated_by_assignable = seperate_by_assignability(d, grid)
            assert sum(seperated_by_assignable) == d
            for assignable in seperated_by_assignable:
                resulting_durations.append(assignable)
                if harmony:
                    chord = abjad.Chord(harmony, abjad.Duration(assignable))
                else:
                    chord = abjad.Rest(abjad.Duration(assignable))
                subnotes.append(chord)
        if len(subnotes) > 1 and len(harmony) > 0:
            abjad.attach(abjad.Tie(), subnotes[:])
        notes.extend(subnotes)
    assert sum(resulting_durations) == sum(converted_delays)
    # 2. apply beams
    return apply_beams(notes, resulting_durations, absolute_leading_pulses)


def round_cents_to_12th_tone(cents: float) -> float:
    ct = cents / 100
    # round to 12th tone
    ct = round(ct * 6) / 6
    return ct


def convert2abjad_pitch(
    pitch: ji.JIPitch, ratio2pitchclass_dict: dict
) -> abjad.NamedPitch:
    octave = pitch.octave + 4
    pitch_class = ratio2pitchclass_dict[pitch.register(0)]
    confused_octave_tests = (pitch_class[0] == "c", pitch.register(0).cents > 1000)
    if all(confused_octave_tests):
        octave += 1
    return abjad.NamedPitch(pitch_class, octave=octave)


EKMELILY_PREAMBLE = """
\\include "ekmel.ily"
\\language "english"
\\ekmelicStyle "gost"

\\ekmelicUserStyle pfeifer #'(
  (1/12 #xE2C7)
  (1/6 #xE2D1)
  (1/3 #xE2CD)
  (5/12 #xE2C3)
  (7/12 #xE2C8)
  (2/3 #xE2D2)
  (5/6 #xE2CE)
  (11/12 #xE2C4)
  (-1/12 #xE2C2)
  (-1/6 #xE2CC)
  (-1/3 #xE2D0)
  (-5/12 #xE2C6)
  (-7/12 #xE2C1)
  (-2/3 #xE2CB)
  (-5/6 #xE2CF)
  (-11/12 #xE2C5))

"""
