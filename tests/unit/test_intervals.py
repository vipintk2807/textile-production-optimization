from textile_optimizer.domain import intervals as iv


def test_adjacent_half_open_intervals_do_not_overlap():
    assert not iv.overlaps((0, 60), (60, 90))  # ends at 60, next begins at 60
    assert iv.overlaps((0, 61), (60, 90))
    assert iv.overlaps((10, 20), (0, 100))


def test_containment_and_length():
    assert iv.contained_in((10, 20), (10, 20))
    assert not iv.contained_in((10, 21), (10, 20))
    assert iv.length((5, 12)) == 7


def test_overlapping_pairs_detected():
    assert iv.find_overlapping_pairs([(0, 10), (10, 20)]) == []
    assert iv.find_overlapping_pairs([(0, 10), (5, 20)]) == [((0, 10), (5, 20))]


def test_subtract_downtime_from_windows():
    assert iv.subtract([(0, 100)], [(20, 30)]) == [(0, 20), (30, 100)]
    assert iv.subtract([(0, 100)], [(0, 100)]) == []
    assert iv.subtract([(0, 50), (60, 100)], [(40, 70)]) == [(0, 40), (70, 100)]


def test_clip():
    assert iv.clip((50, 150), 0, 100) == (50, 100)
    assert iv.clip((120, 150), 0, 100) is None
