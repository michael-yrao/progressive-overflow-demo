# DSA Progress

<!--
Notes for the coach / future agents:
- Columns: Difficulty, Problem, Comfort, Streak, Next Review Date, Latest Rep Date, Rep Dates.
- ⚠️ Renamed "Attempt" -> "Rep" (header stat + both date columns). update_review_dates.py still
  RECOGNIZES the older spellings and upgrades whichever it finds, so an un-migrated tracker parses
  fine. The in-file `# ── Attempt · <date> ──` banners in solution files were deliberately NOT renamed.
- `Streak` = consecutive Clean results. Increments on Clean; resets to 0 on Shaky or Blank.
- `Next Review Date` is COMPUTED from Comfort + Streak by scripts/update_review_dates.py
  (intervals come from cse.config.yml; defaults: Clean s1 +30, s2 +60, Retired +180,
  Shaky +10, Blank +2). Do not hand-edit it — edit Comfort/Streak and re-run the script.
- At Streak == graduate_at_streak (default 3), change Comfort to 🎓 to graduate the problem.
  Retired problems return for a spot check every 180 days.
- 🏆 GRADUATION — the tier above 🎓. A 🎓 problem passing TWO consecutive 180-day spot checks
  leaves this table for a plain-list `## 🏆 Retired` section: no interval, no ongoing cost.
  Why: even at +180 a row bills ~0.039 slots/week FOREVER, so without a release valve the
  library caps out around 500–600 problems. Re-enters at 🟡 if it resurfaces and fails.
- DISPOSABLE REPS — not every solved problem earns a row. A consolidation rep or an
  application pull is a probe testing whether a TECHNIQUE transfers, not an asset to maintain:
  log the outcome to the technique's ledger (mastery/recognition_gotchas.md,
  mastery/complexity_gotchas.md) and create NO row if it came back 🟢. Only 🟡/🔴 earns a row.
- ⚠️ BOTH of the above need a `discovery_skip` entry (or, for probes, a root outside
  solutions.roots). Discovery re-adds any problem it finds without a row, so deleting a row
  alone silently resurrects it on the next commit. Keep the Graduated list a PLAIN BULLET
  LIST — never this 7-column table — or the parser picks it back up.
- WHAT THIS FILE MEANS: "everything still unproven" — a work queue, not a trophy case. A
  shrinking row count is the healthy direction; don't report row count as progress. The
  accomplishment record is the 🏆 list plus the technique ledgers.
- The script also auto-discovers solution files under the configured roots
  (cse.config.yml → solutions.roots/globs) and adds missing rows.
- Titles should include the method when relevant, e.g. `(BFS)` / `(DFS)`; a same-number
  problem solved by a different method gets a NEW row, not an overwrite.
- The pre-commit hook runs the script when this file or a solution file is staged.
  Manual run: `python scripts/update_review_dates.py`.
- Replace the example row below with your own once you log your first problem.
-->

> **56+3** problems &nbsp;·&nbsp; **56+3** solutions &nbsp;·&nbsp; **216+3** reps

| | 🏆 Retired | 🎓 Graduated | 🟢 Clean | 🟡 Shaky | 🔴 Blank |
|:---|:---:|:---:|:---:|:---:|:---:|
| **Solutions** | 2 | 12 | 38 | 6 | 0 |

| Difficulty | Problem | Comfort | Streak | Next Review Date | Latest Rep Date | Rep Dates |
|---|---|---|---|---|---|---|
| Hard | [124. Binary Tree Maximum Path Sum](https://leetcode.com/problems/binary-tree-maximum-path-sum/) | 🟢 | 1 | 2026-11-21 | 2026-10-22 | 2026-06-23, 2026-07-05, 2026-07-17, 2026-08-16, 2026-10-16, 2026-10-22 |
| Medium | [238. Product of Array Except Self](https://leetcode.com/problems/product-of-array-except-self/) | 🟢 | 1 | 2026-11-20 | 2026-10-21 | 2026-06-09, 2026-07-11, 2026-07-14, 2026-08-15, 2026-10-14, 2026-10-21 |
| Hard | [42. Trapping Rain Water](https://leetcode.com/problems/trapping-rain-water/) | 🟡 | 0 | 2026-10-30 | 2026-10-20 | 2026-10-14, 2026-10-20 |
| Easy | [125. Valid Palindrome](https://leetcode.com/problems/valid-palindrome/) | 🟡 | 0 | 2026-10-30 | 2026-10-20 | 2026-07-22, 2026-08-21, 2026-08-31, 2026-09-10, 2026-09-26, 2026-10-06, 2026-10-18, 2026-10-20 |
| Medium | [323. Number of Connected Components in an Undirected Graph](https://leetcode.com/problems/number-of-connected-components-in-an-undirected-graph/) | 🟢 | 1 | 2026-11-18 | 2026-10-19 | 2026-08-25, 2026-09-04, 2026-10-07, 2026-10-13, 2026-10-19 |
| Hard | [269. Alien Dictionary](https://leetcode.com/problems/alien-dictionary/) | 🟡 | 0 | 2026-10-28 | 2026-10-18 | 2026-08-05, 2026-08-15, 2026-08-25, 2026-09-25, 2026-10-08, 2026-10-18 |
| Medium | [648. Replace Words](https://leetcode.com/problems/replace-words/) | 🎓 | 3 | 2027-04-15 | 2026-10-17 | 2026-06-26, 2026-07-07, 2026-07-17, 2026-08-16, 2026-10-17 |
| Medium | [435. Non-overlapping Intervals](https://leetcode.com/problems/non-overlapping-intervals/) | 🟢 | 1 | 2026-11-14 | 2026-10-15 | 2026-06-25, 2026-07-02, 2026-08-01, 2026-10-04, 2026-10-15 |
| Easy | [104. Maximum Depth of Binary Tree](https://leetcode.com/problems/maximum-depth-of-binary-tree/) | 🟡 | 0 | 2026-10-23 | 2026-10-13 | 2026-10-13 |
| Easy | [100. Same Tree](https://leetcode.com/problems/same-tree/) | 🟢 | 1 | 2026-11-11 | 2026-10-12 | 2026-07-01, 2026-07-31, 2026-09-30, 2026-10-05, 2026-10-12 |
| Medium | [36. Valid Sudoku](https://leetcode.com/problems/valid-sudoku/) | 🟢 | 1 | 2026-11-10 | 2026-10-11 | 2026-09-01, 2026-09-15, 2026-09-26, 2026-10-11 |
| Easy | [121. Best Time to Buy and Sell Stock](https://leetcode.com/problems/best-time-to-buy-and-sell-stock/) | 🟢 | 2 | 2026-12-10 | 2026-10-11 | 2026-09-06, 2026-09-11, 2026-10-11 |
| Medium | [19. Remove Nth Node From End of List](https://leetcode.com/problems/remove-nth-node-from-end-of-list/) | 🟡 | 0 | 2026-10-20 | 2026-10-10 | 2026-10-10 |
| Medium | [33. Search in Rotated Sorted Array](https://leetcode.com/problems/search-in-rotated-sorted-array/) | 🟡 | 0 | 2026-10-20 | 2026-10-10 | 2026-08-18, 2026-08-29, 2026-09-10, 2026-10-10 |
| Medium | [143. Reorder List](https://leetcode.com/problems/reorder-list/) | 🟢 | 1 | 2026-11-09 | 2026-10-10 | 2026-10-10 |
| Medium | [787. Cheapest Flights Within K Stops](https://leetcode.com/problems/cheapest-flights-within-k-stops/) | 🟢 | 2 | 2026-12-09 | 2026-10-10 | 2026-08-26, 2026-09-05, 2026-10-10 |
| Medium | [49. Group Anagrams](https://leetcode.com/problems/group-anagrams/) | 🟢 | 1 | 2026-11-08 | 2026-10-09 | 2026-10-09 |
| Easy | [703. Kth Largest Element in a Stream](https://leetcode.com/problems/kth-largest-element-in-a-stream/) | 🟢 | 1 | 2026-11-08 | 2026-10-09 | 2026-09-19, 2026-10-03, 2026-10-09 |
| Medium | [739. Daily Temperatures](https://leetcode.com/problems/daily-temperatures/) | 🟢 | 1 | 2026-11-06 | 2026-10-07 | 2026-06-22, 2026-07-22, 2026-09-27, 2026-10-07 |
| Easy | [1046. Last Stone Weight](https://leetcode.com/problems/last-stone-weight/) | 🟢 | 2 | 2026-12-05 | 2026-10-06 | 2026-09-03, 2026-10-06 |
| Medium | [199. Binary Tree Right Side View](https://leetcode.com/problems/binary-tree-right-side-view/) | 🟢 | 2 | 2026-12-01 | 2026-10-02 | 2026-07-31, 2026-08-30, 2026-09-02, 2026-10-02 |
| Medium | [200. Number of Islands](https://leetcode.com/problems/number-of-islands/) | 🟢 | 2 | 2026-12-01 | 2026-10-02 | 2026-06-30, 2026-07-06, 2026-07-16, 2026-07-20, 2026-08-19, 2026-08-30, 2026-10-02 |
| Medium | [207. Course Schedule](https://leetcode.com/problems/course-schedule/) | 🟢 | 2 | 2026-12-01 | 2026-10-02 | 2026-09-02, 2026-10-02 |
| Medium | [22. Generate Parentheses](https://leetcode.com/problems/generate-parentheses/) | 🎓 | 3 | 2027-03-30 | 2026-10-01 | 2026-06-24, 2026-07-01, 2026-08-02, 2026-10-01 |
| Medium | [134. Gas Station](https://leetcode.com/problems/gas-station/) | 🎓 | 3 | 2027-03-30 | 2026-10-01 | 2026-06-29, 2026-07-31, 2026-10-01 |
| Medium | [417. Pacific Atlantic Water Flow](https://leetcode.com/problems/pacific-atlantic-water-flow/) | 🎓 | 3 | 2027-03-30 | 2026-10-01 | 2026-06-20, 2026-07-03, 2026-08-02, 2026-10-01 |
| Easy | [704. Binary Search](https://leetcode.com/problems/binary-search/) | 🟢 | 1 | 2026-10-30 | 2026-09-30 | 2026-06-14, 2026-07-15, 2026-09-20, 2026-09-30 |
| Medium | [973. K Closest Points to Origin](https://leetcode.com/problems/k-closest-points-to-origin/) | 🟢 | 1 | 2026-10-29 | 2026-09-29 | 2026-08-09, 2026-08-14, 2026-09-14, 2026-09-21, 2026-09-29 |
| Medium | [128. Longest Consecutive Sequence](https://leetcode.com/problems/longest-consecutive-sequence/) | 🟢 | 1 | 2026-10-28 | 2026-09-28 | 2026-06-19, 2026-07-22, 2026-08-01, 2026-08-04, 2026-08-12, 2026-08-22, 2026-09-21, 2026-09-28 |
| Medium | [261. Graph Valid Tree](https://leetcode.com/problems/graph-valid-tree/) | 🟢 | 2 | 2026-11-26 | 2026-09-27 | 2026-06-21, 2026-07-04, 2026-08-05, 2026-08-16, 2026-08-27, 2026-09-27 |
| Medium | [155. Min Stack](https://leetcode.com/problems/min-stack/) | 🟢 | 1 | 2026-10-25 | 2026-09-25 | 2026-06-11, 2026-07-11, 2026-09-09, 2026-09-25 |
| Medium | [167. Two Sum II](https://leetcode.com/problems/two-sum-ii/) | 🟢 | 1 | 2026-10-24 | 2026-09-24 | 2026-06-16, 2026-07-19, 2026-08-01, 2026-09-01, 2026-09-16, 2026-09-24 |
| Medium | [994. Rotting Oranges](https://leetcode.com/problems/rotting-oranges/) | 🟢 | 1 | 2026-10-24 | 2026-09-24 | 2026-06-28, 2026-07-30, 2026-08-09, 2026-09-12, 2026-09-24 |
| Medium | [55. Jump Game](https://leetcode.com/problems/jump-game/) | 🟢 | 2 | 2026-11-22 | 2026-09-23 | 2026-08-19, 2026-09-23 |
| Medium | [424. Longest Repeating Character Replacement](https://leetcode.com/problems/longest-repeating-character-replacement/) | 🟢 | 2 | 2026-11-22 | 2026-09-23 | 2026-08-23, 2026-09-23 |
| Hard | [332. Reconstruct Itinerary](https://leetcode.com/problems/reconstruct-itinerary/) | 🟢 | 2 | 2026-11-21 | 2026-09-22 | 2026-08-07, 2026-08-18, 2026-09-22 |
| Medium | [98. Validate Binary Search Tree](https://leetcode.com/problems/validate-binary-search-tree/) | 🎓 | 3 | 2027-03-21 | 2026-09-22 | 2026-06-10, 2026-06-20, 2026-07-24, 2026-09-22 |
| Medium | [74. Search a 2D Matrix](https://leetcode.com/problems/search-a-2d-matrix/) | 🟢 | 2 | 2026-11-18 | 2026-09-19 | 2026-08-14, 2026-09-19 |
| Medium | [1011. Capacity To Ship Packages Within D Days](https://leetcode.com/problems/capacity-to-ship-packages-within-d-days/) | 🟢 | 2 | 2026-11-18 | 2026-09-19 | 2026-08-17, 2026-09-19 |
| Medium | [146. LRU Cache](https://leetcode.com/problems/lru-cache/) | 🟢 | 2 | 2026-11-17 | 2026-09-18 | 2026-06-18, 2026-07-18, 2026-07-29, 2026-08-08, 2026-08-13, 2026-09-18 |
| Medium | [153. Find Minimum in Rotated Sorted Array](https://leetcode.com/problems/find-minimum-in-rotated-sorted-array/) | 🎓 | 3 | 2027-03-17 | 2026-09-18 | 2026-06-08, 2026-06-15, 2026-07-18, 2026-09-18 |
| Medium | [133. Clone Graph](https://leetcode.com/problems/clone-graph/) | 🟢 | 2 | 2026-11-16 | 2026-09-17 | 2026-08-13, 2026-08-17, 2026-09-17 |
| Easy | [206. Reverse Linked List](https://leetcode.com/problems/reverse-linked-list/) | 🎓 | 3 | 2027-03-16 | 2026-09-17 | 2026-06-13, 2026-07-13, 2026-09-17 |
| Medium | [853. Car Fleet](https://leetcode.com/problems/car-fleet/) | 🎓 | 3 | 2027-03-15 | 2026-09-16 | 2026-06-17, 2026-07-17, 2026-09-16 |
| Hard | [84. Largest Rectangle in Histogram](https://leetcode.com/problems/largest-rectangle-in-histogram/) | 🎓 | 3 | 2027-03-14 | 2026-09-15 | 2026-06-15, 2026-07-16, 2026-09-15 |
| Easy | [242. Valid Anagram](https://leetcode.com/problems/valid-anagram/) | 🟢 | 2 | 2026-11-13 | 2026-09-14 | 2026-08-03, 2026-08-11, 2026-09-14 |
| Medium | [235. Lowest Common Ancestor of BST](https://leetcode.com/problems/lowest-common-ancestor-of-bst/) | 🎓 | 3 | 2027-03-09 | 2026-09-10 | 2026-06-12, 2026-07-12, 2026-09-10 |
| Medium | [53. Maximum Subarray](https://leetcode.com/problems/maximum-subarray/) | 🟢 | 2 | 2026-11-08 | 2026-09-09 | 2026-06-24, 2026-07-24, 2026-07-28, 2026-08-03, 2026-08-10, 2026-09-09 |
| Medium | [2. Add Two Numbers](https://leetcode.com/problems/add-two-numbers/) | 🎓 | 3 | 2027-03-08 | 2026-09-09 | 2026-06-09, 2026-07-10, 2026-09-09 |
| Easy | [1. Two Sum](https://leetcode.com/problems/two-sum/) | 🎓 | 3 | 2027-03-07 | 2026-09-08 | 2026-06-10, 2026-07-10, 2026-09-08 |
| Medium | [75. Sort Colors](https://leetcode.com/problems/sort-colors/) | 🟢 | 2 | 2026-11-06 | 2026-09-07 | 2026-08-08, 2026-09-07 |
| Easy | [21. Merge Two Sorted Lists](https://leetcode.com/problems/merge-two-sorted-lists/) | 🟢 | 2 | 2026-11-04 | 2026-09-05 | 2026-08-06, 2026-09-05 |
| Medium | [743. Network Delay Time](https://leetcode.com/problems/network-delay-time/) | 🟢 | 2 | 2026-10-27 | 2026-08-28 | 2026-06-08, 2026-07-09, 2026-07-23, 2026-07-27, 2026-08-28 |
| Medium | [560. Subarray Sum Equals K](https://leetcode.com/problems/subarray-sum-equals-k/) | 🟢 | 2 | 2026-10-25 | 2026-08-26 | 2026-06-17, 2026-06-22, 2026-06-29, 2026-07-12, 2026-07-26, 2026-08-26 |
| Medium | [875. Koko Eating Bananas](https://leetcode.com/problems/koko-eating-bananas/) | 🟢 | 2 | 2026-10-23 | 2026-08-24 | 2026-06-23, 2026-06-30, 2026-07-10, 2026-07-25, 2026-08-24 |
| Easy | [283. Move Zeroes](https://leetcode.com/problems/move-zeroes/) | 🟢 | 2 | 2026-10-19 | 2026-08-20 | 2026-06-27, 2026-07-08, 2026-07-21, 2026-08-20 |

## Knowledge Expansion Queue

Problems for algorithmic depth — not part of the spaced-repetition stats. These enter the schedule when the relevant topic arrives. (Populated as you cross into the expansion tiers; see `../study_guide.md` and `../../../curriculum/`.)

## 🏆 Retired

- 56. Merge Intervals — retired 2026-04-19
- 347. Top K Frequent Elements — retired 2026-05-23
