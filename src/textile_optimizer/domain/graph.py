"""Small directed-graph helpers for operation precedence."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping


def find_cycle(nodes: Iterable[str], predecessors: Mapping[str, Iterable[str]]) -> list[str] | None:
    """Return one cycle as a list of node ids (first == last), or ``None`` if acyclic.

    ``predecessors[n]`` lists the nodes that must finish before ``n``. Unknown nodes in the
    predecessor lists are ignored here (missing references are reported separately).
    """
    node_set = set(nodes)
    WHITE, GREY, BLACK = 0, 1, 2
    colour = dict.fromkeys(node_set, WHITE)
    for root in sorted(node_set):
        if colour[root] != WHITE:
            continue
        stack: list[tuple[str, Iterator[str]]] = [
            (root, iter(sorted(p for p in predecessors.get(root, ()) if p in node_set)))
        ]
        path = [root]
        colour[root] = GREY
        while stack:
            node, children = stack[-1]
            advanced = False
            for child in children:
                if colour[child] == GREY:
                    return [*path[path.index(child) :], child]
                if colour[child] == WHITE:
                    colour[child] = GREY
                    path.append(child)
                    stack.append(
                        (child, iter(sorted(p for p in predecessors.get(child, ()) if p in node_set)))
                    )
                    advanced = True
                    break
            if not advanced:
                colour[node] = BLACK
                stack.pop()
                path.pop()
    return None


def topological_order(nodes: Iterable[str], predecessors: Mapping[str, Iterable[str]]) -> list[str]:
    """Deterministic topological order (predecessors first). Raises ValueError on a cycle."""
    node_list = sorted(set(nodes))
    node_set = set(node_list)
    indegree = {n: 0 for n in node_list}
    successors: dict[str, list[str]] = {n: [] for n in node_list}
    for n in node_list:
        for p in predecessors.get(n, ()):
            if p in node_set:
                indegree[n] += 1
                successors[p].append(n)
    ready = sorted(n for n, d in indegree.items() if d == 0)
    order: list[str] = []
    while ready:
        n = ready.pop(0)
        order.append(n)
        for s in sorted(successors[n]):
            indegree[s] -= 1
            if indegree[s] == 0:
                ready.append(s)
        ready.sort()
    if len(order) != len(node_list):
        raise ValueError("Precedence graph contains a cycle.")
    return order
