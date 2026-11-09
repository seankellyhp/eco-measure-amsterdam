# Measuring the energy and emissions of Python programs

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/seankellyhp/eco-measure-amsterdam/blob/main/notebooks/getting-started.ipynb)

Workshop materials: a tutorial on measuring the energy use and carbon
emissions of Python programs with [CodeCarbon](https://codecarbon.io) and
[EcoLogits](https://ecologits.ai). It is the Python counterpart of the
[TidyCarbon](https://github.com/seankellyhp/Tidycarbon) tutorial for R.

The tutorial is split into three notebooks. Each runs on its own, but they
are meant to be read in this order:

| Notebook | | |
|---|---|---|
| [getting-started.ipynb](notebooks/getting-started.ipynb) | Measure the energy and emissions of an existing Python script, and of each step of a pipeline (an LDA topic model). | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/seankellyhp/eco-measure-amsterdam/blob/main/notebooks/getting-started.ipynb) |
| [sentiment_tracking.ipynb](notebooks/sentiment_tracking.ipynb) | Measure dictionary and transformer (DistilBERT) sentiment analysis, and benchmark the Bing dictionary in polars, NLTK's VADER and transformers against each other. | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/seankellyhp/eco-measure-amsterdam/blob/main/notebooks/sentiment_tracking.ipynb) |
| [llm_tracking.ipynb](notebooks/llm_tracking.ipynb) | Estimate the energy and emissions of sentiment analysis with a hosted language model, with EcoLogits. | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/seankellyhp/eco-measure-amsterdam/blob/main/notebooks/llm_tracking.ipynb) |

## Option A: Google Colab (nothing to install)

Click **Open in Colab** next to a notebook, sign in with a Google account,
and run the cells from top to bottom. The first cell installs the missing
packages and downloads the data, which takes about a minute.

## Option B: your own machine

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then:

```bash
git clone https://github.com/seankellyhp/eco-measure-amsterdam
cd eco-measure-amsterdam
uv sync
uv run jupyter lab notebooks/getting-started.ipynb
```

`uv sync` installs Python and every package, at the versions in
[uv.lock](uv.lock). The last command opens Getting Started in your browser; if
no browser opens, copy the `http://localhost:8888/...` link that Jupyter prints in
the terminal. The other two notebooks are next to it in the `notebooks` folder, in
the file browser on the left. Leave the terminal open while you work;
Ctrl+C stops Jupyter. The data are in [data/](data/). NLTK downloads its
tokenizer models and lexicon into the virtual environment on the first run,
and transformers downloads its sentiment model (about 270 MB) into the
Hugging Face cache. The sentiment model runs on an NVIDIA GPU if there is
one (on Linux and Windows, PyTorch's CUDA libraries are a download of several
GB), and on the CPU otherwise.

## The language model section

The last cell of `llm_tracking` sends a request to a language model through
[OpenRouter](https://openrouter.ai), which needs an API key and costs money.
Everything else runs without one. On Colab, add the key as a secret
named `OPENROUTER_API_KEY` (key icon in the left sidebar). Locally, put it in a
`.env` file:

```
OPENROUTER_API_KEY=sk-or-...
```

## Files

| File | |
|---|---|
| [notebooks/](notebooks/) | The three notebooks. |
| [data/](data/) | Jane Austen's six novels and the Bing sentiment lexicon, exported from the R packages janeaustenr and tidytext by [data/make_data.R](data/make_data.R). |
| [figures/](figures/) | Images used in the notebooks. |
