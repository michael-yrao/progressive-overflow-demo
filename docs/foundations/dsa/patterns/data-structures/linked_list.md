# Linked List — Technique Hub

A linked list is nodes joined by `next` pointers: no random access, head can change, everything is pointer rewiring. This page is a **map** — it doesn't teach the techniques, it tells you *which* techniques to reach for and links to them.

## Structure facts

- No indexing — traverse via `next` only.
- The **head can change** on insert/delete → use a dummy node.
- Track a **predecessor** (`prev`) to splice; **save `next`** before you rewire.
- Most operations are O(n) time, O(1) space (O(n) stack if recursive).

## Techniques used on linked lists

| Technique | Reach for it when | Doc |
|---|---|---|
| **Dummy node** | Head may change; building/merging a list | [techniques/dummy_node](../techniques/dummy_node.md) |
| **Fast & slow pointers** | Cycle detection, middle, nth-from-end | [techniques/fast_slow_pointer](../techniques/fast_slow_pointer.md) |
| **In-place reversal** | Reverse list/sublist, reorder, palindrome | [techniques/in_place_reversal](../techniques/in_place_reversal.md) |
| **Recursion** | Process on the unwind; clean reversal/removal | [techniques/recursion](../techniques/recursion.md) |

## Deciding fast

| Question | Technique |
|---|---|
| Remove/insert at head cleanly? | dummy node |
| Nth-from-end or middle? | fast & slow (gap / two-speed) |
| Reverse, or compare back-to-front? | in-place reversal |
| Merge two sorted lists / partition? | dummy + tail (see dummy_node) |

## Representative problems

21 Merge Two Lists, 19 Remove Nth From End, 206 Reverse List, 141/142 Cycle, 234 Palindrome, 143 Reorder, 2 Add Two Numbers, 138 Copy with Random Pointer, 146 LRU Cache.
