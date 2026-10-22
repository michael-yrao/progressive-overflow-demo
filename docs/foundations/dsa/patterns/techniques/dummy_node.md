# Dummy Node (Sentinel)

A fake node placed **before the head** of a linked list so that operations on the head need no special-casing. Also the backbone of "build a new list" (merge/partition) via a `dummy` + `tail`.

## When to reach for it

A fake node placed before the head of a linked list so that operations on the head need no special-casing. Also the backbone of "build a new list" (merge/partition) via a dummy + tail.

- deleting or inserting at the **head** (head may change)
- **building** a new list (merge two lists, partition, add two numbers)
- you catch yourself writing `if node == head: ...` special cases

## Picking feature

The head itself might be removed, replaced, or not exist yet — a sentinel before it makes every splice the same `prev.next` rewrite, with no head special-case.

- **not in-place-reversal** — the head only MOVES (reversal returns `prev`); a sentinel adds nothing when no node is spliced in or out
- **not fast-slow-pointer** — you are only reading positions (middle, cycle), not rewiring links


## Template: Template

```python
dummy = ListNode(0)
dummy.next = head
prev = dummy
# ... walk prev/curr, splice via prev.next ...
return dummy.next          # NOT head — head may have changed
```
Complexity: O(n) time · O(1) space — one walk over the list; the sentinel is the single extra node

## Template: Build-a-list variant (merge / partition)

Keep a `tail` you append to; return `dummy.next`:

```python
def merge_two_lists(a, b):
    dummy = tail = ListNode(0)
    while a and b:
        if a.val < b.val:
            tail.next, a = a, a.next
        else:
            tail.next, b = b, b.next
        tail = tail.next
    tail.next = a or b       # attach the remainder
    return dummy.next
```
Complexity: O(n + m) time · O(1) space — each node of either input is attached exactly once; the sentinel and `tail` are the only extras — no new nodes

## Practice

- LC 21 — Merge Two Sorted Lists
- LC 19 — Remove Nth Node From End of List
- LC 2 — Add Two Numbers
- LC 83 — Remove Duplicates from Sorted List
- LC 82 — Remove Duplicates from Sorted List II
- LC 86 — Partition List

| Problem | NC150? | Wrinkle |
|---|---|---|
| 21. Merge Two Sorted Lists | ✅ | dummy + tail build |
| 19. Remove Nth Node From End | ✅ | dummy so removing the head is uniform |
| 2. Add Two Numbers | ✅ | dummy + tail, carry |
| 83 / 82. Remove Duplicates | No | dummy for 82 (head may be a dup) |
| 86. Partition List | No | two dummies (before / after), splice |

## Common pitfalls

- **Returning `head` instead of `dummy.next`** — if the head was removed/changed, `head` is stale.
- **Forgetting to advance `prev`/`tail`** — leaves the list mis-wired.
- **Not terminating the tail** (`tail.next = None`) in partition-style splits → accidental cycle.
