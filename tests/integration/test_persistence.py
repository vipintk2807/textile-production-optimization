import sqlite3

import pytest

from helpers import machine, op, order
from textile_optimizer.domain.models import ChangeoverRule, PlanningSettings
from textile_optimizer.errors import IntegrityConflictError, PersistenceError
from textile_optimizer.persistence.db import backup_database
from textile_optimizer.persistence.repository import Repository


def seed(service):
    service.save_machine(machine("M1"), is_new=True)
    service.save_order(order("O1"), is_new=True)
    service.save_operation(op("A", "O1", ("M1",)), is_new=True)


def test_crud_roundtrip_and_restart(tmp_path):
    from textile_optimizer.services.planning_service import PlanningService

    path = tmp_path / "x.db"
    svc = PlanningService(Repository(path))
    seed(svc)
    svc.save_order(order("O1", description="edited", due_time=700), is_new=False)
    # "application restart": brand-new repository object on the same file
    again = Repository(path)
    o = again.get_order("O1")
    assert o.description == "edited" and o.due_time == 700
    assert again.get_machine("M1").availability[0].end == 1000
    assert again.get_operation("A").eligible_machines[0].machine_id == "M1"


def test_duplicate_ids_rejected(service):
    seed(service)
    with pytest.raises(IntegrityConflictError):
        service.save_order(order("O1"), is_new=True)
    with pytest.raises(IntegrityConflictError):
        service.save_machine(machine("M1"), is_new=True)
    with pytest.raises(IntegrityConflictError):
        service.save_operation(op("A", "O1", ("M1",)), is_new=True)


def test_referential_integrity(service):
    from textile_optimizer.errors import InputValidationError

    seed(service)
    with pytest.raises(InputValidationError):  # nonexistent order
        service.save_operation(op("B", "NOPE", ("M1",)), is_new=True)
    with pytest.raises(InputValidationError):  # nonexistent machine
        service.save_operation(op("B", "O1", ("GHOST",)), is_new=True)
    with pytest.raises(InputValidationError):  # nonexistent predecessor
        service.save_operation(op("B", "O1", ("M1",), preds=("ZZ",)), is_new=True)


def test_cycle_rejected_at_save(service):
    from textile_optimizer.errors import InputValidationError

    seed(service)
    service.save_operation(op("B", "O1", ("M1",), preds=("A",)), is_new=True)
    with pytest.raises(InputValidationError, match="cycle"):
        service.save_operation(op("A", "O1", ("M1",), preds=("B",)), is_new=False)


def test_delete_policies(service):
    seed(service)
    service.save_operation(op("B", "O1", ("M1",), preds=("A",)), is_new=True)
    with pytest.raises(IntegrityConflictError):  # machine referenced by operations
        service.delete_machine("M1")
    with pytest.raises(IntegrityConflictError):  # operation is a predecessor of B
        service.delete_operation("A")
    assert service.delete_order("O1") == 2  # cascades, reports how many operations were removed
    assert service.repo.list_operations() == []
    service.delete_machine("M1")  # now unreferenced
    assert service.repo.list_machines() == []


def test_overlapping_calendar_rejected_on_save(service):
    from textile_optimizer.errors import InputValidationError

    with pytest.raises(InputValidationError):
        service.save_machine(machine("M9", windows=((0, 100), (50, 200))), is_new=True)


def test_transaction_rollback_leaves_no_partial_machine(repo, monkeypatch):
    """A failure while writing the children of a machine must roll back the whole machine."""

    def boom(self, conn, m):
        conn.execute("DELETE FROM machine_capabilities WHERE machine_id = ?", (m.machine_id,))
        raise sqlite3.OperationalError("simulated disk failure")

    monkeypatch.setattr(Repository, "_write_machine_children", boom)
    with pytest.raises(PersistenceError):
        repo.insert_machine(machine("M7"))
    monkeypatch.undo()
    assert repo.get_machine("M7") is None


def test_changeover_rules_and_settings_persist(repo):
    repo.replace_changeover_rules([ChangeoverRule(from_category="X", to_category="Y", minutes=5)])
    assert repo.list_changeover_rules()[0].minutes == 5
    s = PlanningSettings(horizon_end=777, objective="makespan", workers=2)
    repo.save_settings(s)
    got = Repository(repo.path).get_settings()
    assert got.horizon_end == 777 and got.workers == 2 and got.objective.value == "makespan"


def test_foreign_keys_enforced_by_database(repo):
    from textile_optimizer.persistence.db import transaction

    with pytest.raises(sqlite3.IntegrityError), transaction(repo.path) as conn:
        conn.execute(
            "INSERT INTO operations (operation_id, order_id, operation_name, processing_duration, status, updated_at)"
            " VALUES ('X','MISSING','n',10,'active','now')"
        )


def test_unusable_database_path_gives_persistence_error(tmp_path):
    with pytest.raises(PersistenceError):
        Repository(tmp_path / "no_such_dir" / "sub" / "x.db")


def test_backup_and_restore(service, tmp_path):
    seed(service)
    target = backup_database(service.repo.path, tmp_path / "bk" / "copy.db")
    restored = Repository(target)
    assert restored.get_operation("A") is not None and restored.get_machine("M1") is not None
    with pytest.raises(PersistenceError):  # never overwrites an existing backup
        backup_database(service.repo.path, target)


def test_init_does_not_wipe_existing_data(tmp_path):
    from textile_optimizer.services.planning_service import PlanningService

    path = tmp_path / "keep.db"
    seed(PlanningService(Repository(path)))
    Repository(path)  # re-initialising must keep data
    assert len(Repository(path).list_orders()) == 1
