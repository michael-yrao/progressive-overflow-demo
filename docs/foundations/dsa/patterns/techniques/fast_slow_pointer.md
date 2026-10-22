# Fast & Slow Pointer Patterns

Two pointers moving at **different speeds** through a sequence (usually a linked list). The speed gap is what detects cycles, finds the middle, and locates positions relative to the end — all in one pass, O(1) space.

## When to reach for it

Two pointers moving at different speeds through a sequence (usually a linked list). The speed gap is what detects cycles, finds the middle, and locates positions relative to the end — all in one pass, O(1) space.

- does this linked list have a cycle?
- find the middle of the list
- find where the cycle begins
- "find the duplicate number" in an array of `1..n` (it's a cycle in disguise)
- palindrome linked list (find middle, reverse half)

## Picking feature

The question is about POSITION in a chain you cannot index — middle, cycle, cycle entry — and a 2:1 speed gap answers it in one pass with no extra memory.

- **not in-place-reversal** — you need to CHANGE the links, not locate a node — though reversal often follows a middle-find (palindrome, reorder)
- **not two-pointer** — the input is an indexable array — opposite-ends or separation pointers apply; fast/slow exists for chains you can only walk


## Template: Template — the two-speed walk

```python
slow = fast = head
while fast and fast.next:      # guard BOTH: fast.next.next needs both non-null
    slow = slow.next           # 1 step
    fast = fast.next.next      # 2 steps
    # if cycle: they will eventually meet (fast == slow)
# if no cycle: fast falls off the end; slow is at the MIDDLE
```
Complexity: O(n) time · O(1) space — fast reaches the end (or the meeting point) in at most n/2 iterations; two pointers only

Two facts fall out of the same loop:
- **Cycle** → fast laps slow and they collide. No cycle → fast reaches null.
- **Middle** → when fast hits the end (finite list), slow has gone exactly half as far.

## Template: Finding the cycle's start (Floyd, phase 2)

After slow and fast meet inside the cycle, reset one pointer to head and advance **both one step at a time** — they meet at the cycle entrance (a distance identity makes this exact):

```python
slow2 = head
while slow2 != slow:
    slow2 = slow2.next
    slow = slow.next
return slow                    # entrance of the cycle
```
Complexity: O(n) time · O(1) space — phase 2 walks at most n further steps before the pointers meet at the entrance; still two pointers

**287. Find the Duplicate** is this exact trick on an array: treat `i -> nums[i]` as "next," the duplicate forces a cycle, and phase 2 finds its entrance.

Both phases in one picture — meeting point first, then the walk to the entrance (drawn in the
array-index form used by 287):

![Floyd's cycle detection: phase 1 slow and fast meet inside the cycle, phase 2 resets one pointer to the head and both advance one step to meet at the cycle entrance](../../images/floyd_cycle_dection_algorithm.svg)

## Practice

- LC 141 — Linked List Cycle
- LC 142 — Linked List Cycle II
- LC 876 — Middle of the Linked List
- LC 287 — Find the Duplicate Number
- LC 234 — Palindrome Linked List

| Problem | NC150? | Wrinkle |
|---|---|---|
| 141. Linked List Cycle | ✅ | Bare cycle detection (done) |
| 142. Linked List Cycle II | No | + find the cycle start (phase 2) |
| 876. Middle of the Linked List | No | Slow = middle when fast ends |
| 287. Find the Duplicate Number | ✅ | Array-as-linked-list cycle |
| 234. Palindrome Linked List | No | Find middle, reverse second half, compare |

## Common pitfalls

- **Loop guard** — `while fast and fast.next` is mandatory; `fast = fast.next.next` dereferences two levels. (This is the exact 141 sticking point.)
- **Even vs odd length** — where `slow` lands as "middle" differs by one; decide if you want the first or second middle and adjust the guard (`while fast.next and fast.next.next` gives the first middle).
- **Comparing nodes, not values** — cycle detection compares node identity (`fast is slow`), not `.val`.
