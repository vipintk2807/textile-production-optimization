from conftest import make_snapshot
from textile_optimizer.domain.snapshot import MachineSpec


def base(**over):
    kw = dict(
        orders=[("O1", 0, 100), ("O2", 0, 200)],
        machines={"M1": [(0, 500)], "M2": [(0, 500)]},
        operations=[("A", "O1", [], {"M1": 30, "M2": 40}), ("B", "O2", [], {"M1": 20})],
        horizon=500,
    )
    kw.update(over)
    return make_snapshot(**kw)


def test_fingerprint_is_deterministic_and_order_independent():
    a = base()
    b = base(
        orders=[("O2", 0, 200), ("O1", 0, 100)],
        machines={"M2": [(0, 500)], "M1": [(0, 500)]},
        operations=[("B", "O2", [], {"M1": 20}), ("A", "O1", [], {"M2": 40, "M1": 30})],
    )
    assert a.fingerprint() == b.fingerprint() == base().fingerprint()


def test_semantic_changes_change_the_fingerprint():
    ref = base().fingerprint()
    assert base(orders=[("O1", 0, 101), ("O2", 0, 200)]).fingerprint() != ref  # due time
    assert base(orders=[("O1", 5, 100), ("O2", 0, 200)]).fingerprint() != ref  # release time
    assert base(machines={"M1": [(0, 400)], "M2": [(0, 500)]}).fingerprint() != ref  # availability
    assert (
        base(operations=[("A", "O1", [], {"M1": 31, "M2": 40}), ("B", "O2", [], {"M1": 20})]).fingerprint()
        != ref
    )
    assert (
        base(operations=[("A", "O1", [], {"M1": 30}), ("B", "O2", [], {"M1": 20})]).fingerprint() != ref
    )  # eligibility
    assert base(horizon=600).fingerprint() != ref
    assert (
        base(objective="total_tardiness").fingerprint() != ref
    )  # objective is part of the run configuration
    assert base(hard_due=True).fingerprint() != ref


def test_precedence_and_changeover_data_affect_fingerprint():
    ops_no = [("A", "O1", [], {"M1": 30}), ("B", "O1", [], {"M1": 20})]
    ops_yes = [("A", "O1", [], {"M1": 30}), ("B", "O1", ["A"], {"M1": 20})]
    common = dict(orders=[("O1", 0, 100)], machines={"M1": [(0, 500)]}, horizon=500)
    assert (
        make_snapshot(operations=ops_no, **common).fingerprint()
        != make_snapshot(operations=ops_yes, **common).fingerprint()
    )
    cats = [("A", "O1", [], {"M1": 30}, "X"), ("B", "O1", [], {"M1": 20}, "Y")]
    s1 = make_snapshot(
        operations=cats, setup={("X", "Y"): 5, ("Y", "X"): 5, ("X", "X"): 0, ("Y", "Y"): 0}, **common
    )
    s2 = make_snapshot(
        operations=cats, setup={("X", "Y"): 6, ("Y", "X"): 5, ("X", "X"): 0, ("Y", "Y"): 0}, **common
    )
    assert s1.fingerprint() != s2.fingerprint()


def test_roundtrip_serialisation_keeps_fingerprint():
    a = base()
    from textile_optimizer.domain.snapshot import ProblemSnapshot

    assert ProblemSnapshot.from_dict(a.to_dict()).fingerprint() == a.fingerprint()
    assert isinstance(a.machines[0], MachineSpec)
