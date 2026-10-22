# Markdown Style Guide for Algorithm Cheatsheets

This document outlines the formatting standards used in algorithm cheatsheet files (e.g., `binary_search_patterns.md`). Follow this format when creating new markdown documentation.

---

## Overall Structure

```
# Main Title

## Quick Reference
[Table of patterns/variations]

---

## Detailed Sections
[Numbered sections with deep dives]

---

## Supporting Sections
[Key insights, pattern recognition, etc.]
```

---

## Section 1: Quick Reference Table

**Purpose**: Provide at-a-glance comparison of all patterns/variations

**Format**:
- Use a comparison table
- Include 3-5 key columns (Pattern, Property1, Property2, Use Case)
- Keep rows concise
- Use **bold** for pattern names

**Example**:
```markdown
| Pattern | Loop | Midpoint | Use Case |
|---------|------|----------|----------|
| **Exact Value** | `while l <= r` | `(l + r) // 2` | Find exact match |
| **Min Boundary** | `while l < r` | `(l + r) // 2` | Find first true |
| **Max Boundary** | `while l < r` | `(l + r + 1) // 2` | Find last true |
```

---

## Section 2: Detailed Pattern Sections

**Structure for each pattern**:

1. **Header**: `## N. Pattern Name (Optional Subtitle)`
2. **Use Case**: Clear 1-line description starting with "**Use Case**:"
3. **Component Table**: Shows key implementation details
4. **Code Block**: Working example code
5. **Reference Link**: Link to relevant problem/resource

**Component Table Format**:
```markdown
| Component | Value |
|-----------|-------|
| **Loop** | `while l < r` |
| **Midpoint** | `mid = (l + r) // 2` (left-biased) |
| **Return** | `l` at loop exit |
```

**Code Block Format**:
- Use Python code blocks
- Include comments explaining logic
- Show realistic update conditions
- Keep to 8-15 lines

```markdown
**Update Rules**:
\`\`\`python
if condition:
    l = mid  # Explanation of movement
else:
    r = mid - 1  # Explanation of movement
\`\`\`
```

**Reference Format**:
```markdown
**Example**: [LeetCode XXX - Problem Name](https://leetcode.com/problems/problem-slug/)
```

---

## Section 3: Supporting Content

### 3A. Explanation Sections

When explaining abstract concepts (e.g., `is_valid(mid)`):

1. **Start with definition**: What is it? (use bold)
2. **Explain why it matters**: 1-2 sentences
3. **Show real examples**: 2-3 concrete cases with code
4. **Provide pattern recognition**: Table of "how to identify it"
5. **Link back to patterns**: Connect to earlier sections

**Subsection Pattern**:
```markdown
### What is it?

[Clear definition]

### Why it matters

[Importance explanation]

### Real Examples

#### Example 1: Problem Name (Pattern Type)
[Code block with comments]

#### Example 2: Problem Name (Pattern Type)
[Code block with comments]

### Pattern Recognition

[Table showing how to identify the concept]
```

### 3B. Key Insights Section

Include a final section highlighting:
- **Why design choices matter** (e.g., why bias matters)
- **Mental models** (summary tables)
- **Common pitfalls** (if applicable)
- **Comparison of approaches** (if applicable)

**Format**:
```markdown
## Key Insights

### Why Bias Matters

- **Left-biased**: [When to use, what it prevents]
- **Right-biased**: [When to use, what it prevents]

### Mental Model

[Summary table comparing all approaches]
```

---

## Formatting Standards

### Headers

- Use `#` for main title (1 header)
- Use `##` for major sections (Quick Reference, numbered patterns, Key Insights)
- Use `###` for subsections within patterns or detailed sections
- Use `####` for sub-subsections (e.g., within explanations)

### Emphasis

- **Bold**: Pattern names, component labels, problem goals
- `Code`: Function names, variable names, code constructs
- `Code blocks`: Multi-line code examples
- *Italics*: Rarely used; prefer bold for emphasis

### Links

- External links: `[Display Text](URL)`
- Internal sections: Avoid anchor links; use relative references

### Spacing

- Add `---` (horizontal rule) between major sections
- Add blank lines between:
  - Component tables and code blocks
  - Different pattern sections
  - Subsections within explanations
- Keep tables compact (no extra blank lines within tables)

### Tables

- Use 3-5 columns max (readability)
- Left-align most columns, center-align shorter content
- Use **bold** in headers for emphasis
- Use backticks for code/technical terms in table cells

### Code Blocks

- Language identifier: `python` (or appropriate language)
- Include comments explaining key lines
- Keep to 8-15 lines (break long examples into smaller blocks)
- Use realistic variable names from the problem domain

---

## Example Template

```markdown
# Algorithm/Concept Name

## Quick Reference

| Pattern/Type | Key Feature 1 | Key Feature 2 | Use Case |
|--------------|---------------|---------------|----------|
| **Pattern A** | Value A1 | Value A2 | Use case A |
| **Pattern B** | Value B1 | Value B2 | Use case B |

---

## 1. Pattern A Name

**Use Case**: [Clear description of when to use]

| Component | Value |
|-----------|-------|
| **Loop** | [Loop type] |
| **Key Formula** | [Formula] |
| **Return** | [What you return] |

**Implementation**:
\`\`\`python
[Code example]
\`\`\`

**Example**: [Link to problem]

---

## 2. Pattern B Name

[Repeat structure above]

---

## Understanding [Abstract Concept]

### What is it?

[Definition]

### Why it matters

[Explanation]

### Real Examples

#### Example 1: [Problem] ([Pattern Type])
\`\`\`python
[Code]
\`\`\`

#### Example 2: [Problem] ([Pattern Type])
\`\`\`python
[Code]
\`\`\`

### Pattern Recognition

| Context | How to Identify |
|---------|-----------------|
| Scenario 1 | [Identification rule] |
| Scenario 2 | [Identification rule] |

---

## Key Insights

### [Insight Topic]

[Explanation with visual or conceptual breakdown]

### Mental Model

[Summary table or visual]
```

---

## Checklist for New Files

- [ ] Main title captures topic clearly
- [ ] Quick Reference table provides at-a-glance comparison
- [ ] Each pattern has: Use Case → Component Table → Code → Link
- [ ] Code blocks are 8-15 lines with explanatory comments
- [ ] Component tables are consistent across patterns
- [ ] External links include full URLs
- [ ] Explanation sections include 2+ real examples
- [ ] Pattern Recognition table (if applicable) helps identify when to use
- [ ] Key Insights section ties everything together
- [ ] Horizontal rules separate major sections
- [ ] Spacing is consistent (blank lines between sections)
- [ ] No inline code for file paths or markdown syntax instructions (use code blocks)
- [ ] Table cells use backticks for technical terms
- [ ] Subsections are hierarchical and logically organized

---

## Tips for Maintainability

1. **Keep examples current**: Update LeetCode links if problems move
2. **Be consistent**: Use the same terminology across sections
3. **Prefer tables**: Tables are faster to scan than bullet lists
4. **Add context**: Include "why" not just "what"
5. **Group related info**: Use subsections to organize complex topics
6. **Test readability**: Check markdown rendering in VS Code preview
7. **Link appropriately**: Connect related patterns within the document

---

## Related Files

- `algorithm_cheatsheet/binary_search_patterns.md`: Example of this style guide in practice
- Repository: `cse-progress`
