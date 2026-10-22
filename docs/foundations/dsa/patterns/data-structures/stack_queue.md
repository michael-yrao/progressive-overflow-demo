# Stack / Queue — Technique Hub

LIFO stack and FIFO queue — often the *supporting* structure inside a bigger technique rather than the whole problem. This page maps stack/queue-flavored problems to techniques.

## Structure facts

- **Stack** (LIFO): Python `list` with `append` / `pop`; peek is `stack[-1]` (guard for empty).
- **Queue** (FIFO): `collections.deque` with `append` / `popleft` (never `list.pop(0)` — O(n)).
- **Deque**: both ends — needed for monotonic-deque (moving-window max/min).

## Techniques used on stacks/queues

| Technique | Reach for it when | Doc |
|---|---|---|
| **Monotonic stack** | Nearest greater/smaller to one side; histogram/spans | [techniques/monotonic_stack](../techniques/monotonic_stack.md) |
| **Monotonic deque** | Max/min over a **moving window** | see the deque section in [monotonic_stack](../techniques/monotonic_stack.md) |
| **Plain stack (matching/eval)** | Balanced brackets, expression evaluation, "undo last" | — (direct use; see problems below) |
| **BFS queue** | Level-order / shortest-path traversal | [techniques/tree_bfs](../techniques/tree_bfs.md) |

## Deciding fast

| Question | Technique |
|---|---|
| Nearest greater/smaller element? | monotonic stack |
| Max in every window of size k? | monotonic deque |
| Valid parentheses / evaluate expression? | plain stack (match/pop) |
| Nested structure, "most recent unmatched"? | plain stack |

## Representative problems

20 Valid Parentheses, 155 Min Stack, 150 Eval RPN, 739 Daily Temperatures, 84 Largest Rectangle, 853 Car Fleet, 239 Sliding Window Maximum (deque), 496/503/901 Next Greater / Stock Span.
