from dataclasses import dataclass


@dataclass(frozen=True)
class ContextItem:
    kind: str
    key: str


def move_before(items, source, target):
    items = list(items)
    if source == target or source not in items or target not in items:
        return items
    item = items.pop(items.index(source))
    items.insert(items.index(target), item)
    return items


def move_to_index(items, source, index):
    items = list(items)
    if source not in items:
        return items
    item = items.pop(items.index(source))
    index = max(0, min(int(index), len(items)))
    items.insert(index, item)
    return items


def gap_count(items):
    return len(list(items)) + 1
