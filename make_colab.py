"""Convert getting-started.qmd into getting-started.ipynb, for Google Colab or local Jupyter.

Needs pandoc (Quarto ships one). Usage: python make_colab.py
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

PANDOC = shutil.which("pandoc") or "/home/wald3n/.local/share/r-pandoc/3.10/pandoc-3.10/bin/pandoc"
REPO = "seankellyhp/eco-measure-amsterdam"
RAW = f"https://raw.githubusercontent.com/{REPO}/main"
COLAB = f"https://colab.research.google.com/github/{REPO}/blob/main/getting-started.ipynb"

root = Path(__file__).parent
src = (root / "getting-started.qmd").read_text()

# --- YAML header -> title cell -------------------------------------------
yaml, body = re.match(r"^---\n(.*?)\n---\n(.*)$", src, re.S).groups()
title = re.search(r'^title: "(.*)"', yaml, re.M).group(1)
subtitle = re.search(r'^subtitle: "(.*)"', yaml, re.M).group(1)

# --- setup cell (replaces the hidden include:false cell) -------------------
setup = f'''```{{python}}
# Setup. On Colab: install the packages Colab does not have, and download the data.
# Locally (uv sync), everything is already installed and in the repository.
import os
import sys
import urllib.request
import warnings
from pathlib import Path

if "google.colab" in sys.modules:
    %pip install -q -U codecarbon "ecologits[openai]" polars plotnine

for file in ["data/austen_books.csv", "data/bing.csv"]:
    if not Path(file).exists():
        Path(file).parent.mkdir(exist_ok=True)
        urllib.request.urlretrieve(f"{RAW}/{{file}}", file)

# Quieten CodeCarbon before the first tracker is created.
os.environ["CODECARBON_LOG_LEVEL"] = "error"
warnings.filterwarnings("ignore")

import plotnine
import polars as pl

plotnine.options.figure_size = (7, 3.5)
plotnine.options.dpi = 110
pl.Config.set_tbl_hide_dataframe_shape(True)
```'''
body = re.sub(r"```\{python\}\n#\| include: false\n.*?```", lambda m: setup, body, count=1, flags=re.S)

# --- installation section -> Colab instructions ----------------------------
install_old = re.search(r"# Requirements and Installation\n.*?(?=\nThe data are in)", body, re.S).group(0)
install_new = """# Requirements and Installation

There are two ways to run this notebook. Either way, run the setup cell at
the top first, then the cells in order, from top to bottom.

- **Google Colab.** Open the notebook with the *Open in Colab* button above.
  The setup cell installs CodeCarbon, EcoLogits, polars and plotnine
  (scikit-learn, SciPy, NLTK and pyarrow are already on Colab), and downloads
  the data.
- **Your own machine.** Clone the
  [repository](https://github.com/seankellyhp/eco-measure-amsterdam). It has
  the data and a [uv](https://docs.astral.sh/uv/) environment with every
  package:

  ```bash
  git clone https://github.com/seankellyhp/eco-measure-amsterdam
  cd eco-measure-amsterdam
  uv sync
  uv run jupyter lab --config jupyter_server_config.py
  ```

polars holds the data and the measurements, and plotnine draws them.
scikit-learn [@pedregosa:2011:sklearn] fits the topic model, and NLTK
[@bird:2009:nltk] provides the stop words, the sentence tokenizer and the
second sentiment dictionary. openai and pydantic send the requests to the language model.

On Colab, CodeCarbon measures a shared virtual machine in a Google
data center. It usually cannot read the CPU's energy counters there, so it
estimates the energy from the CPU model instead.
"""
body = body.replace(install_old, install_new)
body = body.replace("The data are in the `data` folder next to this tutorial:",
                    "The data are in the `data` folder (on Colab, the setup cell downloads them):")

body = body.replace("Here they go into the project's virtual environment, one of\nthe folders NLTK searches:", "Here they go into one of the folders NLTK searches:")

# --- figure from GitHub ----------------------------------------------------
body = body.replace("(figures/electricity-map.png)", f"({RAW}/figures/electricity-map.png)")

# --- inline Quarto expression ----------------------------------------------
body = body.replace('Labeling all `{python} f"{pride.height:,}"` sentences', "Labeling all the sentences")

# --- the Hello_World example runs fine; drop eval:false and labels --------
body = re.sub(r"^#\| (eval: false|label: .*)\n", "", body, flags=re.M)

# --- API key from Colab secrets instead of .env -----------------------------
body = re.sub(
    r"It needs an API\nkey\. Put the key in a `\.env` file.*?```\nOPENROUTER_API_KEY=sk-or-\.\.\.\n```",
    """It needs an API
key. Never paste the key into a cell.

- **Colab:** click the key icon in the left sidebar (*Secrets*), add a secret
  named `OPENROUTER_API_KEY` with your key as its value, and allow this
  notebook to access it.
- **Your own machine:** put the key in a `.env` file in the repository folder,
  with no spaces around the `=`. The file is in `.gitignore`, so it stays out
  of version control:

  ```
  OPENROUTER_API_KEY=sk-or-...
  ```""",
    body, flags=re.S,
)
body = body.replace(
    "The code below is not run when the tutorial is rendered, because it needs an\nAPI key and every request costs money.",
    "The code below needs an API key, and every request costs money.",
)
# The key comes from Colab's secrets on Colab, and from .env elsewhere.
body = body.replace("from dotenv import load_dotenv\n", "")
body = body.replace("load_dotenv()\n", """if "google.colab" in sys.modules:
    from google.colab import userdata

    os.environ["OPENROUTER_API_KEY"] = userdata.get("OPENROUTER_API_KEY")
else:
    from dotenv import load_dotenv

    load_dotenv()
""")

# --- Colab badge under the title -----------------------------------------
header = f"""# {title}

**{subtitle}**

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)]({COLAB})
"""

# --- resolve citations with pandoc ------------------------------------------
md = subprocess.run(
    [PANDOC, "-f", "markdown", "-t", "gfm-raw_html", "--wrap=preserve", "--citeproc",
     "--bibliography", str(root / "references.bib"), "--csl", str(root / "apa.csl")],
    input=(header + body).replace("```{python}", "```python"), capture_output=True, text=True, check=True,
).stdout

# --- split into cells --------------------------------------------------------
cells = []


def add(kind, text):
    text = text.strip("\n")
    if not text.strip():
        return
    lines = text.split("\n")
    source = [line + "\n" for line in lines[:-1]] + [lines[-1]]
    cell = {"cell_type": kind, "metadata": {}, "source": source}
    if kind == "code":
        cell.update(execution_count=None, outputs=[])
    cells.append(cell)


pos = 0
for m in re.finditer(r"^``` (?:python|\{python\})\n(.*?)^```\n", md, re.M | re.S):
    add("markdown", md[pos:m.start()])
    add("code", m.group(1))
    pos = m.end()
add("markdown", md[pos:])

nb = {
    "cells": cells,
    "metadata": {
        "colab": {"provenance": []},
        "kernelspec": {"display_name": "Python 3", "name": "python3"},
        "language_info": {"name": "python"},
    },
    "nbformat": 4,
    "nbformat_minor": 0,
}
out = root / "getting-started.ipynb"
out.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n")
print(f"wrote {out}: {sum(c['cell_type'] == 'code' for c in cells)} code, "
      f"{sum(c['cell_type'] == 'markdown' for c in cells)} markdown cells")
