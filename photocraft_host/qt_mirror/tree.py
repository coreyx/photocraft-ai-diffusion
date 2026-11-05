"""Widget-tree nodes as the protocol sends them, and the diff that turns one tree into another
as ``panel.patch`` operations.

A node is a plain dict ``{"id", "kind", "props", "children"}``. Ids are unique within a tree.
"""

from __future__ import annotations

from typing import Any

Node = dict[str, Any]


def node(
    node_id: str, kind: str, props: dict[str, Any] | None = None, children: list[Node] | None = None
) -> Node:
    """A node; props whose value is ``None`` are left out."""
    return {
        "id": node_id,
        "kind": kind,
        "props": {k: v for k, v in (props or {}).items() if v is not None},
        "children": children or [],
    }


def wire(n: Node) -> Node:
    """The node as it goes on the wire: empty props and children left out."""
    out: Node = {"id": n["id"], "kind": n["kind"]}
    if n["props"]:
        out["props"] = n["props"]
    if n["children"]:
        out["children"] = [wire(c) for c in n["children"]]
    return out


def _parents(root: Node) -> dict[str, str | None]:
    parents: dict[str, str | None] = {root["id"]: None}
    stack = [root]
    while stack:
        n = stack.pop()
        for c in n["children"]:
            parents[c["id"]] = n["id"]
            stack.append(c)
    return parents


def diff(old: Node, new: Node, force: set[str] | None = None) -> list[dict[str, Any]]:
    """The patch operations that turn ``old`` into ``new`` (both rooted at the same id).

    Removals come first, so a node that moved to another parent is never in the tree twice. A
    node whose kind changed is replaced (removed and inserted). Nodes in ``force`` have all their
    props sent even when unchanged, to confirm a value the user just set in the host.
    """
    if old["id"] != new["id"] or old["kind"] != new["kind"]:
        return [{"op": "replace", "node": wire(new)}]
    force = force or set()
    new_parents = _parents(new)
    kinds = {}
    stack = [new]
    while stack:
        n = stack.pop()
        kinds[n["id"]] = n["kind"]
        stack.extend(n["children"])

    def kept(n: Node, parent: str | None) -> bool:
        nid = n["id"]
        return nid in new_parents and new_parents[nid] == parent and kinds.get(nid) == n["kind"]

    ops: list[dict[str, Any]] = []

    def removals(n: Node):
        for c in n["children"]:
            if kept(c, n["id"]):
                removals(c)
            else:
                ops.append({"op": "remove", "id": c["id"]})

    def changes(o: Node, n: Node):
        props = {k: v for k, v in n["props"].items() if o["props"].get(k) != v or n["id"] in force}
        props.update({k: None for k in o["props"] if k not in n["props"]})
        if props:
            ops.append({"op": "set", "id": n["id"], "props": props})
        before = {c["id"]: c for c in o["children"] if kept(c, o["id"])}
        current = [c["id"] for c in o["children"] if c["id"] in before]
        for index, child in enumerate(n["children"]):
            cid = child["id"]
            if cid in before:
                if current[index] != cid:
                    ops.append({"op": "move", "id": cid, "parent": n["id"], "index": index})
                    current.remove(cid)
                    current.insert(index, cid)
                changes(before[cid], child)
            else:
                ops.append({"op": "insert", "parent": n["id"], "index": index, "node": wire(child)})
                current.insert(index, cid)

    removals(old)
    changes(old, new)
    return ops
