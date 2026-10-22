"""Tests for company_demand.py.

Stdlib unittest, same style as test_remaining.py / test_gamify.py: a fixture file on
disk, exercised through the module's public functions rather than internal state, so a
future rewrite only breaks this file if the observable output changes.

The tracker, techniques vocabulary and planning docs the report joins against are built
inline in a temp dir and patched over the module's path constants (setUpModule), so no test
reads the checkout's own learner data. The one exception is LiveVocabularyTests, which checks
the engine's family names against the SHIPPED techniques.yml on purpose.

    python scripts/test_company_demand.py
"""
from __future__ import annotations

import csv
import io
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import company_demand as cd  # noqa: E402
import pull_interview as pi  # noqa: E402
import technique_coverage as tc  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "company_demand_sample.csv"
SHIPPED_TECHNIQUES_YML = tc.TECHNIQUES_YML
REPORT_DATE = date(2027, 1, 4)

# Rows in the fixture whose classification the tests check by slug.
TRACKED_SLUG = "two-sum"            # 🎓 in the inline tracker below
SCHEDULED_CANDIDATE_SLUG = "basic-calculator"  # linked from the inline schedule, untracked
UNTRACKED_SLUG = "word-search-ii"
MULTI_TAG_SLIDING_WINDOW_SLUG = "longest-substring-without-repeating-characters"
DFS_TREE_SLUG = "balanced-binary-tree"
DFS_ONLY_SLUG = "number-of-islands"
EXCLUDED_SLUG = "combine-two-tables"           # Database tag -> dropped entirely
UNTAGGED_SLUG = "create-hello-world-function"  # empty Topics -> dropped, listed in footer
# Tracked (🟢) AND credited in the inline techniques.yml (Prefix/Suffix Max, family
# two_pointers) — its tags (incl. "Dynamic Programming", "Stack") would tag-priority to a
# DIFFERENT family than its actual techniques.yml credit; see resolve_family_by_number().
CREDITED_SLUG = "trapping-rain-water"
# Untracked, unscheduled, but its title sits in the inline study guide's phase table
# (Bit Manipulation + Math & Geometry) -> the 📋 in-phase-plan status.
PHASE_PLAN_SLUG = "reverse-integer"

INLINE_TRACKER = (
    "| Difficulty | Problem | Comfort | Streak | Next Review Date | Latest Rep Date | Rep Dates |\n"
    "|---|---|---|---|---|---|---|\n"
    "| Easy | [1. Two Sum](https://leetcode.com/problems/two-sum/) | 🎓 | 3 "
    "| 2027-06-01 | 2027-01-01 | 2027-01-01 |\n"
    "| Hard | [42. Trapping Rain Water](https://leetcode.com/problems/trapping-rain-water/) | 🟢 | 1 "
    "| 2027-02-01 | 2027-01-01 | 2027-01-01 |\n"
)
INLINE_TECHNIQUES = """
version: 1
techniques:
  - name: Prefix/Suffix Max
    family: two_pointers
    problems:
      - {number: 42}
"""
INLINE_STUDY_GUIDE = (
    "| Phase | Dates | Categories |\n"
    "|---|---|---|\n"
    "| 1 | Jan 4-10 | Bit Manipulation, Reverse Integer, Math & Geometry |\n"
)
INLINE_SCHEDULE = (
    "| Problem | Start | End | Next | Technique |\n"
    "|---|---|---|---|---|\n"
    "| [227 Basic Calculator](../x.py) · [LC](https://leetcode.com/problems/basic-calculator/) "
    "| 🆕 |  |  | Stack |\n"
)

_patches: list = []
_tmpdir: tempfile.TemporaryDirectory | None = None


def setUpModule() -> None:
    """Point the tracker, techniques, and planning-doc constants at inline temp fixtures."""
    global _tmpdir
    _tmpdir = tempfile.TemporaryDirectory()
    root = Path(_tmpdir.name)
    dsa = root / "docs" / "foundations" / "dsa"
    schedules = root / "docs" / "foundations" / "schedules"
    (dsa / "mastery").mkdir(parents=True)
    schedules.mkdir(parents=True)
    tracker = dsa / "mastery" / "dsa_progress.md"
    techniques = dsa / "mastery" / "techniques.yml"
    study_guide = dsa / "study_guide.md"
    tracker.write_text(INLINE_TRACKER, encoding="utf-8")
    techniques.write_text(INLINE_TECHNIQUES, encoding="utf-8")
    study_guide.write_text(INLINE_STUDY_GUIDE, encoding="utf-8")
    (schedules / "20270104_schedule.md").write_text(INLINE_SCHEDULE, encoding="utf-8")
    for patch in (
        mock.patch.object(tc, "TRACKER_MD", tracker),
        mock.patch.object(tc, "TECHNIQUES_YML", techniques),
        mock.patch.object(pi, "ROOT", root),
        mock.patch.object(pi, "PLANNING_DOCS", [study_guide, tracker]),
    ):
        patch.start()
        _patches.append(patch)


def tearDownModule() -> None:
    for patch in _patches:
        patch.stop()
    _patches.clear()
    if _tmpdir is not None:
        _tmpdir.cleanup()


class LiveVocabularyTests(unittest.TestCase):
    """(a) Every TOPIC_TO_FAMILY value and every FAMILY_PRIORITY entry must be a
    `family:` that exists in the SHIPPED techniques.yml, not a copy of it."""

    @classmethod
    def setUpClass(cls):
        config = tc._load_yaml().safe_load(SHIPPED_TECHNIQUES_YML.read_text(encoding="utf-8"))
        cls.live_families = {entry["family"] for entry in config["techniques"]}

    def test_topic_to_family_values_are_live_families(self):
        bad = set(cd.TOPIC_TO_FAMILY.values()) - self.live_families
        self.assertEqual(bad, set(), f"TOPIC_TO_FAMILY names families not in techniques.yml: {bad}")

    def test_family_priority_entries_are_live_families(self):
        bad = set(cd.FAMILY_PRIORITY) - self.live_families
        self.assertEqual(bad, set(), f"FAMILY_PRIORITY names families not in techniques.yml: {bad}")


class RenderReportTests(unittest.TestCase):
    """(b) Rendering from the fixture, via the same function the CLI uses in --local
    mode, produces the banner, one summary line, the three per-tier sections and the
    cross-tier heading. No network."""

    @classmethod
    def setUpClass(cls):
        stem = FIXTURE.stem
        texts = {stem: FIXTURE.read_text(encoding="utf-8")}
        tier_companies = {stem: [stem]}
        cls.report = cd.render_report(tier_companies, texts, [], "sample", 100, REPORT_DATE)
        cls.tier = stem

    def test_banner_present(self):
        self.assertIn("GENERATED by scripts/company_demand.py", self.report)

    def test_summary_line_present(self):
        self.assertIn(f"**{self.tier}**", self.report)
        self.assertIn("unique problems", self.report)

    def test_demand_table_section_present(self):
        self.assertIn(f"### {self.tier} — demand vs supply by family", self.report)

    def test_unmapped_topics_section_present(self):
        self.assertIn(f"### {self.tier} — unmapped topics", self.report)

    def test_top_problems_section_present(self):
        self.assertIn(f"### {self.tier} — top-", self.report)

    def test_cross_tier_heading_present(self):
        heading = f"## Asked by ≥{cd.MIN_COMPANIES_CROSS_TIER} target companies and untracked"
        self.assertIn(heading, self.report)

    def test_per_company_counts_line_present(self):
        """15 = 17 fixture rows minus the 1 EXCLUDED_TAGS row (Combine Two Tables)
        minus the 1 untagged row (Create Hello World Function)."""
        self.assertIn(f"{self.tier} 15", self.report)

    def test_excluded_row_is_dropped_and_banner_reports_it(self):
        """Combine Two Tables carries the Database tag (EXCLUDED_TAGS) and must not
        appear anywhere in the rendered report; the banner names both drop counts."""
        self.assertIn("Excluded 1 SQL/JS/shell rows · 1 untagged rows (listed at the foot).",
                       self.report)
        self.assertNotIn("Combine Two Tables", self.report)

    def test_untagged_row_is_dropped_from_every_table_and_listed_in_the_footer(self):
        """Create Hello World Function has an empty Topics field — EXCLUDED_TAGS can
        never match it (no tags to match against at all), so it needs its own bucket:
        absent from every top-N/cross-tier table, but named (not silently dropped) in
        the dedicated untagged footer."""
        before_footer, _, footer = self.report.partition(cd.UNTAGGED_FOOTER_HEADING)
        self.assertNotIn("Create Hello World Function", before_footer)
        self.assertIn("[Create Hello World Function]"
                       "(https://leetcode.com/problems/create-hello-world-function) | 1 |",
                       footer)

    def test_single_source_ok_marker_covers_the_summary_lines(self):
        """check_single_source.py's OPT_OUT scoping (a heading/comment carrying the
        marker opens a skip region until the next heading) — this asserts the marker
        heading actually sits directly before the summary-lines block, not somewhere
        that leaves them uncovered."""
        marker = "<!-- single-source-ok: generated status counts -->"
        before, _, after = self.report.partition(marker)
        self.assertIn(f"**{self.tier}**", after.split("###", 1)[0])
        self.assertNotIn(f"**{self.tier}**", before)


class StatusClassificationTests(unittest.TestCase):
    """(c) Tracked slugs read their comfort glyph; untracked slugs read '—'; the
    tracker takes priority over the roadmap (roadmap_slugs() also lists tracked
    problems, since it scans dsa_progress.md as one of its planning docs)."""

    @classmethod
    def setUpClass(cls):
        cls.comfort_by_slug = cd.tracker_comfort_by_slug()
        cls.roadmap = pi.roadmap_slugs()

    def test_tracked_slug_reads_its_comfort_glyph(self):
        self.assertEqual(
            cd.status_glyph(TRACKED_SLUG, self.comfort_by_slug, self.roadmap),
            self.comfort_by_slug[TRACKED_SLUG],
        )

    def test_untracked_slug_reads_dash(self):
        self.assertNotIn(UNTRACKED_SLUG, self.comfort_by_slug)
        self.assertNotIn(UNTRACKED_SLUG, self.roadmap)
        self.assertEqual(
            cd.status_glyph(UNTRACKED_SLUG, self.comfort_by_slug, self.roadmap),
            cd.UNTRACKED_GLYPH,
        )

    def test_scheduled_but_untracked_slug_reads_calendar(self):
        slug = SCHEDULED_CANDIDATE_SLUG
        self.assertNotIn(slug, self.comfort_by_slug)
        self.assertIn(slug, self.roadmap)
        self.assertEqual(
            cd.status_glyph(slug, self.comfort_by_slug, self.roadmap), cd.SCHEDULED_GLYPH)


class StatusGlyphSyntheticTests(unittest.TestCase):
    """Deterministic checks of status_glyph() against hand-built inputs, independent of
    the inline tracker/roadmap (which StatusClassificationTests exercises instead)."""

    COMFORT = {"trophy-slug": "\U0001f3c6", "yellow-slug": "\U0001f7e1",
               "both-slug": "\U0001f7e1"}
    ROADMAP = {"both-slug", "roadmap-only-slug"}

    def test_trophy_comfort_displays_as_graduated(self):
        self.assertEqual(cd.status_glyph("trophy-slug", self.COMFORT, self.ROADMAP),
                          cd.GRADUATED_GLYPH)

    def test_yellow_comfort_passes_through(self):
        self.assertEqual(cd.status_glyph("yellow-slug", self.COMFORT, self.ROADMAP),
                          "\U0001f7e1")

    def test_tracker_beats_roadmap_when_slug_is_in_both(self):
        self.assertEqual(cd.status_glyph("both-slug", self.COMFORT, self.ROADMAP),
                          self.COMFORT["both-slug"])

    def test_roadmap_only_slug_reads_calendar(self):
        self.assertEqual(cd.status_glyph("roadmap-only-slug", self.COMFORT, self.ROADMAP),
                          cd.SCHEDULED_GLYPH)

    def test_neither_tracked_nor_scheduled_reads_dash(self):
        self.assertEqual(cd.status_glyph("nowhere-slug", self.COMFORT, self.ROADMAP),
                          cd.UNTRACKED_GLYPH)


class UnmappedTopicsTests(unittest.TestCase):
    """(d) String, Math and Design are MAPPED and so do not appear in the unmapped-topics
    table; "Interactive" is the fixture's genuinely unmapped tag (DELIBERATELY_UNMAPPED —
    never in TOPIC_TO_FAMILY, never excluded)."""

    @classmethod
    def setUpClass(cls):
        stem = FIXTURE.stem
        texts = {stem: FIXTURE.read_text(encoding="utf-8")}
        tier_companies = {stem: [stem]}
        cls.report = cd.render_report(tier_companies, texts, [], "sample", 100, REPORT_DATE)

    def test_string_tag_is_now_mapped_to_strings(self):
        self.assertEqual(cd.TOPIC_TO_FAMILY["String"], "strings")
        self.assertNotIn("| String | ", self.report)

    def test_math_tag_is_now_mapped_to_math_sim(self):
        self.assertEqual(cd.TOPIC_TO_FAMILY["Math"], "math_sim")
        self.assertNotIn("| Math | ", self.report)

    def test_design_tag_is_now_mapped_to_design(self):
        self.assertEqual(cd.TOPIC_TO_FAMILY["Design"], "design")
        self.assertNotIn("| Design | ", self.report)

    def test_interactive_tag_is_deliberately_unmapped_and_listed(self):
        """DELIBERATELY_UNMAPPED only documents that this tag was considered and
        rejected as a family — the unmapped-topics table still reports it, same as any
        other tag with no TOPIC_TO_FAMILY entry ("reported, never silently dropped")."""
        self.assertIn("Interactive", cd.DELIBERATELY_UNMAPPED)
        self.assertNotIn("Interactive", cd.TOPIC_TO_FAMILY)
        self.assertNotIn("Interactive", cd.EXCLUDED_TAGS)
        self.assertIn("| Interactive | 1 |", self.report)

    def test_deliberately_unmapped_row_still_appears_untracked_not_dropped(self):
        """Unmapped is not the same as excluded: the row survives, just with no family."""
        self.assertIn("Guess Number Higher or Lower", self.report)


class VocabularyCoverageTests(unittest.TestCase):
    """(i) Every tag the fixture carries — including rows EXCLUDED_TAGS drops — is
    accounted for: mapped, excluded, or deliberately unmapped. An unaccounted tag
    would silently fall into the unmapped-topics table with no test ever catching it."""

    def test_every_fixture_tag_is_accounted_for(self):
        all_tags: set[str] = set()
        for row in csv.DictReader(io.StringIO(FIXTURE.read_text(encoding="utf-8"))):
            all_tags |= {t.strip() for t in (row.get("Topics") or "").split(",") if t.strip()}
        unaccounted = {
            t for t in all_tags
            if t not in cd.TOPIC_TO_FAMILY
            and t not in cd.EXCLUDED_TAGS
            and t not in cd.DELIBERATELY_UNMAPPED
        }
        self.assertEqual(unaccounted, set())


class FamilyPriorityTests(unittest.TestCase):
    """(e) A multi-tag problem's family is the first FAMILY_PRIORITY match."""

    def test_array_hash_sliding_window_is_sliding_window(self):
        topics = frozenset({"Array", "Hash Table", "Sliding Window"})
        self.assertEqual(cd._family_for_topics(topics), "sliding_window")

    def test_dfs_with_tree_tag_is_trees(self):
        topics = frozenset({"Tree", "Binary Tree", "Depth-First Search"})
        self.assertEqual(cd._family_for_topics(topics), "trees")

    def test_dfs_alone_is_graphs(self):
        topics = frozenset({"Array", "Depth-First Search", "Breadth-First Search",
                             "Union Find", "Matrix"})
        self.assertEqual(cd._family_for_topics(topics), "graphs")

    def test_bare_dfs_tag_with_no_other_mapped_tag_is_graphs(self):
        # Regression guard: test_dfs_alone_is_graphs above passes even with the
        # DFS->graphs branch deleted, since Union Find and Matrix already map to
        # graphs on their own. This isolates the DFS tag itself.
        self.assertEqual(cd._family_for_topics(frozenset({"Depth-First Search"})), "graphs")

    def test_bfs_with_tree_tag_and_no_other_mapped_tag_is_trees(self):
        topics = frozenset({"Breadth-First Search", "Binary Search Tree"})
        self.assertEqual(cd._family_for_topics(topics), "trees")

    def test_fixture_rows_match_expected_families(self):
        problems = cd.parse_problems(FIXTURE.read_text(encoding="utf-8"), "sample").problems
        by_slug = {p.slug: p for p in problems}
        self.assertEqual(by_slug[MULTI_TAG_SLIDING_WINDOW_SLUG].family, "sliding_window")
        self.assertEqual(by_slug[DFS_TREE_SLUG].family, "trees")
        self.assertEqual(by_slug[DFS_ONLY_SLUG].family, "graphs")

    def test_excluded_row_never_reaches_parse_problems_output(self):
        parsed = cd.parse_problems(FIXTURE.read_text(encoding="utf-8"), "sample")
        self.assertEqual(parsed.excluded, 1)
        self.assertNotIn(EXCLUDED_SLUG, {p.slug for p in parsed.problems})

    def test_untagged_row_is_bucketed_separately_from_excluded_and_problems(self):
        parsed = cd.parse_problems(FIXTURE.read_text(encoding="utf-8"), "sample")
        self.assertEqual(len(parsed.untagged), 1)
        self.assertEqual(parsed.untagged[0].slug, UNTAGGED_SLUG)
        self.assertNotIn(UNTAGGED_SLUG, {p.slug for p in parsed.problems})


class CreditedFamilyTests(unittest.TestCase):
    """(f) A tracked, CREDITED problem's family comes from techniques.yml, not tag
    priority — Trapping Rain Water tags into `stack` under the FAMILY_PRIORITY order
    (Stack ranks ahead of Two Pointers/Dynamic Programming), but the inline techniques.yml
    credits it to "Prefix/Suffix Max" (family `two_pointers`), and that must win."""

    @classmethod
    def setUpClass(cls):
        cls.problems = cd.parse_problems(FIXTURE.read_text(encoding="utf-8"), "sample").problems
        cls.by_slug = {p.slug: p for p in cls.problems}
        cls.ctx = cd.build_report_context()

    def test_tag_priority_alone_gives_the_wrong_family(self):
        self.assertEqual(self.by_slug[CREDITED_SLUG].family, "stack")

    def test_vocabulary_credit_overrides_tag_priority(self):
        self.assertEqual(self.ctx.family_of(self.by_slug[CREDITED_SLUG]), "two_pointers")

    def test_uncredited_problem_still_falls_back_to_tag_priority(self):
        untracked = self.by_slug[UNTRACKED_SLUG]
        self.assertEqual(self.ctx.family_of(untracked), untracked.family)


class PhasePlanStatusTests(unittest.TestCase):
    """(g) An untracked, unscheduled problem whose title sits in the phase-plan table
    reads 📋 instead of '—', and is excluded from the cross-tier untracked list."""

    @classmethod
    def setUpClass(cls):
        cls.phase_text = pi.roadmap_phase_text()
        cls.ctx = cd.build_report_context()
        stem = FIXTURE.stem
        texts = {stem: FIXTURE.read_text(encoding="utf-8")}
        tier_companies = {stem: [stem]}
        cls.report = cd.render_report(tier_companies, texts, [], "sample", 100, REPORT_DATE)

    def test_reverse_integer_title_is_in_the_phase_text(self):
        norm = pi._norm("Reverse Integer")
        self.assertGreater(len(norm), cd.MIN_PHASE_TITLE_LEN)
        self.assertIn(norm, self.phase_text)

    def test_status_glyph_reads_in_phase_plan_glyph(self):
        status = cd.status_glyph(PHASE_PLAN_SLUG, {}, set(), title="Reverse Integer",
                                  phase_text=self.phase_text)
        self.assertEqual(status, cd.IN_PHASE_PLAN_GLYPH)

    def test_status_glyph_without_phase_text_is_unchanged(self):
        """No title/phase_text supplied -> old callers keep the old behaviour exactly."""
        self.assertEqual(cd.status_glyph(PHASE_PLAN_SLUG, {}, set()), cd.UNTRACKED_GLYPH)

    def test_rendered_report_shows_the_glyph_for_reverse_integer(self):
        self.assertIn(f"[Reverse Integer](https://leetcode.com/problems/reverse-integer) | "
                      f"math_sim | {cd.IN_PHASE_PLAN_GLYPH}", self.report)

    def test_phase_plan_problem_excluded_from_cross_tier_untracked_list(self):
        """The single-company fixture can never populate the cross-tier list
        (MIN_COMPANIES_CROSS_TIER=3), so this drives render_cross_tier() directly with
        hand-built multi-company Problems instead."""
        three_companies = frozenset({"Amazon", "Google", "Meta"})
        in_phase = cd.Problem(slug=PHASE_PLAN_SLUG, title="Reverse Integer", difficulty="MEDIUM",
                               link="https://leetcode.com/problems/reverse-integer",
                               topics=frozenset({"Math"}), frequency=50.0, companies=three_companies)
        control = cd.Problem(slug="control-problem", title="Totally Untracked Control Problem",
                              difficulty="MEDIUM", link="https://leetcode.com/problems/control",
                              topics=frozenset({"Array"}), frequency=40.0, companies=three_companies)
        report = cd.TierReport(tier="t", fetched=list(three_companies),
                                union=[in_phase, control], top=[in_phase, control], excluded=0)
        lines = "\n".join(cd.render_cross_tier([report], self.ctx, set()))
        self.assertNotIn("Reverse Integer", lines)
        self.assertIn("Totally Untracked Control Problem", lines)


class NewTagMappingTests(unittest.TestCase):
    """(j) Direct coverage for the graph-tag additions and moves — these tags don't all
    show up in the fixture, so they're checked against _family_for_topics() directly
    rather than via a rendered report."""

    def test_topological_sort_moved_to_graphs(self):
        """Was advanced_graphs; techniques.yml files the technique under graphs."""
        self.assertEqual(cd.TOPIC_TO_FAMILY["Topological Sort"], "graphs")
        self.assertEqual(cd._family_for_topics(frozenset({"Topological Sort"})), "graphs")

    def test_new_graph_tag_spellings_map_to_graphs(self):
        for tag in ("Graph Theory", "Union-Find", "Bipartite Graph", "Graph Coloring",
                    "Directed Acyclic Graph"):
            self.assertEqual(cd.TOPIC_TO_FAMILY[tag], "graphs", tag)

    def test_sweep_line_maps_to_intervals(self):
        self.assertEqual(cd.TOPIC_TO_FAMILY["Sweep Line"], "intervals")

    def test_named_algorithm_tags_map_to_advanced_graphs(self):
        self.assertEqual(cd.TOPIC_TO_FAMILY["Dijkstra's Algorithm"], "advanced_graphs")
        self.assertEqual(cd.TOPIC_TO_FAMILY["Kruskal's Algorithm"], "advanced_graphs")

    def test_en_dash_algorithm_tag_maps_to_expansion(self):
        """Exact en-dash spelling, copied from the source repo's own CSVs."""
        self.assertEqual(cd.TOPIC_TO_FAMILY["Knuth–Morris–Pratt Algorithm"], "expansion")

    def test_geometry_and_bitmask_moved_off_expansion(self):
        self.assertEqual(cd.TOPIC_TO_FAMILY["Geometry"], "math_sim")
        self.assertEqual(cd.TOPIC_TO_FAMILY["Bitmask"], "bit_manipulation")


class FamilyPriorityOrderTests(unittest.TestCase):
    """(h) `design` ranks first (it has a live family), and the new families are all present."""

    def test_design_ranks_first_now_that_it_has_a_family(self):
        self.assertEqual(cd.FAMILY_PRIORITY[0], "design")

    def test_new_families_all_present(self):
        for family in ("strings", "math_sim", "bit_manipulation"):
            self.assertIn(family, cd.FAMILY_PRIORITY)


class ExcludedTagsTests(unittest.TestCase):
    def test_excluded_tags_exact_set(self):
        self.assertEqual(cd.EXCLUDED_TAGS,
                          frozenset({"Database", "Shell", "Concurrency", "JavaScript", "Pandas"}))


if __name__ == "__main__":
    unittest.main()
