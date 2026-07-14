# HARPO paper — independent preprint

IEEE-conference-style preprint (Zenodo DOI; arXiv cs.AR if endorsed). Converted
2026-07-02 from the abandoned FPT'26 Track-A 2-page submission: the former appendices
are now the body sections, the paper is de-anonymized (author: Phuc (Patrick) Duc
Nguyen, Independent Researcher, ORCID 0009-0000-6536-214X), and a Related Work
section with verified citations was added.

## Files
- `paper.tex` — preamble, author block, abstract, Introduction, Related Work, the
  `\input` block (body sections), Conclusion, bibliography.
- `appendix/A-architecture.tex` — §: The HARPO Agent (architecture + loops + budget
  + score + invariant).
- `appendix/C-scoring.tex` — §: Scoring overhaul + recipe-vs-LLM deep analysis (the
  central contribution).
- `appendix/B-results.tex` — §: Full measured results incl. token consumption per phase.
- `appendix/E-coverage.tex` — §: Task-type coverage and limitations + future work.
- `appendix/D-reproducibility.tex` — §: Environment, commands, install caveat.

(Files keep their historical `appendix/` names; they are body sections now, input in
the order A, C, B, E, D.)

## How to build — locally, via Docker (no host LaTeX install)
Atlas has no native `pdflatex`; the paper compiles with the `texlive/texlive:latest`
Docker image (~4 GB, pulled 2026-07-02 — same pattern as FocusRoast's `swift:latest`):

```bash
cd paper   # from the repo root
docker run --rm -v "$PWD":/work -w /work texlive/texlive:latest \
  latexmk -pdf -interaction=nonstopmode -halt-on-error paper.tex
```

Output: `paper.pdf` (gitignored, regenerable). Verified 2026-07-02: 8 pages, all
`\ref`/`\cite` resolve, every page visually inspected, no overfull boxes above ~4 pt.
Overleaf (free; bundles `IEEEtran`) remains a fallback if you want to edit in a GUI.

## ⚠️ Verify before submitting
- ~~Repo URL in `paper.tex`~~ — done 2026-07-02: the `\thanks` footnote links
  `https://github.com/phucducnguyen/harpo`, and the reproducibility claims use the
  strong post-release wording. If the repo ever moves, update both.
- **Numbers:** every quantitative value is copied from `docs/ablations/canonical/TABLE.md`
  (the single source of truth). If results change, regenerate that table and re-sync — do
  not hand-edit numbers in the `.tex`.
- **Citations:** all bibliography entries were verified against the arXiv API
  (titles + full author lists) on 2026-07-02. If you add one, verify it the same way —
  never cite from memory.
- **Compile check:** rebuild with the command above and skim every table and
  cross-reference in the PDF before uploading anywhere.
