"""CP-SAT model construction from a :class:`ProblemSnapshot`.

Formulation (technical_specification 7, textile_scheduling_rules 5-13), integer minutes:

Variables
  x[i,m]  Boolean: operation i runs on eligible machine m   (exactly one per operation)
  S_i,E_i start / end of operation i  (E_i = S_i + D_{i,m} when x[i,m])
  s[i,m]  start of the optional interval of (i,m); its *domain* is the union of
          [window_start, window_end - D_{i,m}] over the machine's effective windows, which makes
          the operation non-preemptive and keeps it inside availability and the horizon
  C_o, T_o  completion (max end of terminal operations) and tardiness max(0, C_o - Q_o)
  Cmax    makespan (max over all E_i)

Constraints
  S_i >= release of its order;  S_j >= E_i for every predecessor i of j
  NoOverlap over the optional intervals of each machine (single-capacity machines)
  Changeovers (optional): for two operations a,b on the same machine,
      a before b  =>  E_a + setup(a,b) <= S_b,   pairs with a non-zero setup only
  Optional hard due dates: C_o <= Q_o

Objective (exactly one per run): min Cmax | min sum T_o | min sum w_o * T_o

Changeover semantics: the setup is a minimum gap between *consecutive* operations on a machine;
it occupies the machine (nothing else can be scheduled in it) but does not have to lie inside an
availability window, and the first operation on a machine needs no setup. Enforcing the setup
between every ordered pair equals enforcing it between consecutive operations because input
validation requires the triangle inequality for transitions.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from ..domain.snapshot import ProblemSnapshot
from ..errors import ModelConstructionError


@dataclass
class BuiltModel:
    model: cp_model.CpModel
    snapshot: ProblemSnapshot
    presence: dict[tuple[str, str], cp_model.IntVar] = field(default_factory=dict)
    option_start: dict[tuple[str, str], cp_model.IntVar] = field(default_factory=dict)
    start: dict[str, cp_model.IntVar] = field(default_factory=dict)
    end: dict[str, cp_model.IntVar] = field(default_factory=dict)
    completion: dict[str, cp_model.IntVar] = field(default_factory=dict)
    tardiness: dict[str, cp_model.IntVar] = field(default_factory=dict)
    makespan: cp_model.IntVar | None = None
    stats: dict[str, int] = field(default_factory=dict)


def build_model(snapshot: ProblemSnapshot) -> BuiltModel:
    """Translate the snapshot into a CP-SAT model. Raises ModelConstructionError on bad input."""
    horizon = snapshot.horizon_end
    if horizon <= 0:
        raise ModelConstructionError("Planning horizon must be positive.")
    model = cp_model.CpModel()
    built = BuiltModel(model=model, snapshot=snapshot)
    orders = snapshot.order_map()
    machines = snapshot.machine_map()
    machine_intervals: dict[str, list] = {m.machine_id: [] for m in snapshot.machines}
    machine_options: dict[str, list[tuple[str, int]]] = {m.machine_id: [] for m in snapshot.machines}
    n_options = 0

    for op in snapshot.operations:
        order = orders.get(op.order_id)
        if order is None:
            raise ModelConstructionError(
                f"Operation {op.operation_id} references unknown order {op.order_id}."
            )
        lo = order.release_time
        s_var = model.new_int_var(lo, horizon, f"S_{op.operation_id}")
        e_var = model.new_int_var(lo, horizon, f"E_{op.operation_id}")
        built.start[op.operation_id] = s_var
        built.end[op.operation_id] = e_var

        literals = []
        for machine_id, duration in op.options:
            machine = machines.get(machine_id)
            if machine is None:
                raise ModelConstructionError(
                    f"Operation {op.operation_id} lists unknown machine {machine_id}."
                )
            if duration <= 0:
                raise ModelConstructionError(
                    f"Operation {op.operation_id} has a non-positive duration on {machine_id}."
                )
            starts = []
            for w_start, w_end in machine.windows:
                a, b = max(w_start, lo), min(w_end, horizon) - duration
                if a <= b:
                    starts.append([a, b])
            if not starts:
                continue  # the operation cannot fit this machine's calendar: option impossible
            lit = model.new_bool_var(f"x_{op.operation_id}_{machine_id}")
            domain = cp_model.Domain.from_intervals(starts)
            s_opt = model.new_int_var_from_domain(domain, f"s_{op.operation_id}_{machine_id}")
            interval = model.new_optional_fixed_size_interval_var(
                s_opt, duration, lit, f"iv_{op.operation_id}_{machine_id}"
            )
            model.add(s_var == s_opt).only_enforce_if(lit)
            model.add(e_var == s_opt + duration).only_enforce_if(lit)
            machine_intervals[machine_id].append(interval)
            machine_options[machine_id].append((op.operation_id, duration))
            built.presence[(op.operation_id, machine_id)] = lit
            built.option_start[(op.operation_id, machine_id)] = s_opt
            literals.append(lit)
            n_options += 1
        if literals:
            model.add_exactly_one(literals)
        else:
            model.add_bool_or([])  # no feasible machine option: the model is infeasible

    # precedence: S_j >= E_i
    n_prec = 0
    for op in snapshot.operations:
        for pred in op.predecessors:
            if pred not in built.end:
                raise ModelConstructionError(f"Operation {op.operation_id} has unknown predecessor {pred}.")
            model.add(built.start[op.operation_id] >= built.end[pred])
            n_prec += 1

    # machine non-overlap
    for intervals in machine_intervals.values():
        if len(intervals) > 1:
            model.add_no_overlap(intervals)

    # sequence-dependent changeovers
    n_setup_pairs = 0
    if snapshot.changeover_enabled:
        ops = snapshot.operation_map()
        for machine_id, options in machine_options.items():
            for i, (op_a, _) in enumerate(options):
                for op_b, _ in options[i + 1 :]:
                    if op_a == op_b:
                        continue
                    s_ab = snapshot.setup_minutes(ops[op_a], ops[op_b])
                    s_ba = snapshot.setup_minutes(ops[op_b], ops[op_a])
                    if s_ab == 0 and s_ba == 0:
                        continue
                    la, lb = built.presence[(op_a, machine_id)], built.presence[(op_b, machine_id)]
                    a_first = model.new_bool_var(f"before_{op_a}_{op_b}_{machine_id}")
                    b_first = model.new_bool_var(f"before_{op_b}_{op_a}_{machine_id}")
                    model.add_bool_or([la.negated(), lb.negated(), a_first, b_first])
                    for lit in (a_first, b_first):
                        model.add_implication(lit, la)
                        model.add_implication(lit, lb)
                    model.add(built.end[op_a] + s_ab <= built.start[op_b]).only_enforce_if(a_first)
                    model.add(built.end[op_b] + s_ba <= built.start[op_a]).only_enforce_if(b_first)
                    n_setup_pairs += 1

    # completion / tardiness per order, makespan
    zero = model.new_constant(0)
    for order in snapshot.orders:
        terminals = snapshot.terminal_operations(order.order_id)
        if not terminals:
            raise ModelConstructionError(f"Order {order.order_id} has no operations.")
        c = model.new_int_var(0, horizon, f"C_{order.order_id}")
        model.add_max_equality(c, [built.end[t.operation_id] for t in terminals])
        t = model.new_int_var(0, horizon, f"T_{order.order_id}")
        model.add_max_equality(t, [zero, c - order.due_time])
        built.completion[order.order_id] = c
        built.tardiness[order.order_id] = t
        if snapshot.enforce_due_dates:
            model.add(c <= order.due_time)

    cmax = model.new_int_var(0, horizon, "Cmax")
    if built.end:
        model.add_max_equality(cmax, list(built.end.values()))
    built.makespan = cmax

    # objective (one per run)
    if snapshot.objective == "makespan":
        model.minimize(cmax)
    elif snapshot.objective == "total_tardiness":
        model.minimize(sum(built.tardiness.values()))
    elif snapshot.objective == "weighted_tardiness":
        weights = {o.order_id: o.weight for o in snapshot.orders}
        if any(w is None for w in weights.values()):
            raise ModelConstructionError("Weighted tardiness requires a weight for every order.")
        model.minimize(sum(weights[oid] * var for oid, var in built.tardiness.items()))
    else:
        raise ModelConstructionError(f"Unsupported objective '{snapshot.objective}'.")

    built.stats = {
        "operations": len(snapshot.operations),
        "orders": len(snapshot.orders),
        "machines": len(snapshot.machines),
        "machine_options": n_options,
        "precedence_relations": n_prec,
        "changeover_pairs": n_setup_pairs,
    }
    return built
