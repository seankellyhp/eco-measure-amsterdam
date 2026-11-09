# Measuring the energy and emissions of Python programs

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/seankellyhp/eco-measure-amsterdam/blob/main/getting-started.ipynb)

Workshop materials: a tutorial on measuring the energy use and carbon
emissions of Python programs with [CodeCarbon](https://codecarbon.io) and
[EcoLogits](https://ecologits.ai). It is the Python counterpart of the
[TidyCarbon](https://github.com/seankellyhp/Tidycarbon) tutorial for R.

The tutorial shows how to

1. measure the energy and emissions of an existing Python script,
2. measure each step of a pipeline separately,
3. benchmark the energy cost of sentiment analysis with two dictionary
   packages,
4. estimate the energy cost of sentiment analysis with a hosted language
   model.

## Option A: Google Colab (nothing to install)

Click **Open in Colab** above, sign in with a Google account, and run the
cells from top to bottom. The first cell installs the missing packages and
downloads the data, which takes about a minute.

## Option B: your own machine

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then:

```bash
git clone https://github.com/seankellyhp/eco-measure-amsterdam
cd eco-measure-amsterdam
uv sync
uv run jupyter lab getting-started.ipynb
```

`uv sync` installs Python and every package, at the versions in
[uv.lock](uv.lock). The data are in [data/](data/). NLTK downloads its
tokenizer models and lexicon into the virtual environment on the first run.

## The language model section

The last section sends a request to a language model through
[OpenRouter](https://openrouter.ai), which needs an API key and costs money.
The rest of the tutorial runs without one. On Colab, add the key as a secret
named `OPENROUTER_API_KEY` (key icon in the left sidebar). Locally, put it in a
`.env` file:

```
OPENROUTER_API_KEY=sk-or-...
```

## Files

| File | |
|---|---|
| [getting-started.ipynb](getting-started.ipynb) | The tutorial as a notebook, for Colab or Jupyter. |
| [getting-started.html](getting-started.html) | The tutorial rendered with all outputs, to read along. |
| [getting-started.qmd](getting-started.qmd) | The Quarto source of the tutorial. |
| [data/](data/) | Jane Austen's six novels and the Bing sentiment lexicon, exported from the R packages janeaustenr and tidytext by [data/make_data.R](data/make_data.R). |

The notebook is generated from the Quarto source. After editing
`getting-started.qmd`, rebuild it with `python make_colab.py` (needs pandoc,
which comes with Quarto), and render the HTML with
`uv run quarto render getting-started.qmd`.
