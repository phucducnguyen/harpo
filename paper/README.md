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
No native `pdflatex` is required; the paper compiles with the
`texlive/texlive:latest` Docker image (~4 GB, pulled 2026-07-02):

```bash
cd paper   # from the repo root
docker run --rm -v "$PWD":/work -w /work texlive/texlive:latest \
  latexmk -pdf -interaction=nonstopmode -halt-on-error paper.tex
```

Output: `paper.pdf` (gitignored, regenerable). Verified 2026-08-03 (v2 + claim
corrections + the pre-send audit round): 11 pages, all `\ref`/`\cite` resolve, zero
errors, zero undefined references, two overfull hboxes (5.9 pt and 4.1 pt).
⚠️ `paper.log` contains a non-UTF8 byte, so a plain `grep` over it returns **nothing**
and reads as "clean" — that produced one false all-clear on 2026-08-03. Check it with a
binary-safe reader (`open(...,'rb').decode('utf-8','replace')`), never bare `grep`.
Overleaf (free; bundles `IEEEtran`) remains a fallback if you want to edit in a GUI.

## ⚠️ Verify before submitting
- ~~Repo URL in `paper.tex`~~ — done 2026-07-02: the `\thanks` footnote links
  `https://github.com/phucducnguyen/harpo`, and the reproducibility claims use the
  strong post-release wording. If the repo ever moves, update both.
- **Numbers:** every quantitative value is copied from `docs/ablations/canonical/TABLE.md`
  (the single source of truth). If results change, regenerate that table and re-sync — do
  not hand-edit numbers in the `.tex`. ⚠️ Two documented exceptions, both flagged in the
  text: figures from the **pre-fix** record `docs/ablations/mac8_001_ollama.json`
  (Table I's raw-LLM row + the within-run rescoring), and `area_score` values, which are
  recomputed via `harpo/area.py` because the logs store raw counts, not the score.
  Any *new* exception must be flagged at point of use, or the "copied verbatim" claim in
  `C-scoring.tex` becomes false.
- **Citations:** all bibliography entries were verified against the arXiv API
  (titles + full author lists) on 2026-07-02. If you add one, verify it the same way —
  never cite from memory.
- **Compile check:** rebuild with the command above and skim every table and
  cross-reference in the PDF before uploading anywhere.
