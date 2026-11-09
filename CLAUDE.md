# Notebooks

- The Quarto files (`notebooks/*.qmd`) are the source. Make every edit there, never in the `.ipynb` files.
- The `.ipynb` files are build output. After editing a `.qmd`, rebuild them from the sources:
  `uv run --group docs quarto render` (or `uv run --group docs quarto render notebooks/<name>.qmd` for one notebook).
- Rendering does not run the code (`execute: enabled: false` in `_quarto.yml`), so the rebuilt notebooks have no cell outputs. This is intended: participants run them.
