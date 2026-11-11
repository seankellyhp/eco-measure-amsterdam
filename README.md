# Measuring What We Compute: Towards (More) Efficient AI Use

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/seankellyhp/eco-measure-amsterdam/blob/main/notebooks/getting_started.ipynb)

Workshop materials: a tutorial on measuring the energy use and carbon
emissions of programs with [CodeCarbon](https://codecarbon.io) and
[EcoLogits](https://ecologits.ai) for social science researchers. 

Here are links for resources shared in the presentation. 

[CLEER Dashboard](https://cleerdash.sustainableaigroup.com/) Sustainability estimates for LLMs.  
[AI Energy Score](https://huggingface.co/spaces/AIEnergyScore/Leaderboard) Standardized energy estimates for specialized and general AI models, by task.   
[Electricity Maps](https://app.electricitymaps.com/map/fifteen_minutes?signal=carbon-intensity) Real-time electricity grids.  
[OpenRouter](https://openrouter.ai/) Per request access to a variety of LLMs with benchmarks.   
[Vast AI](https://vast.ai/) On-demand GPU infrastructure with data center locations.   
[Aleph Alpha Kolibri-1](https://huggingface.co/Aleph-Alpha/Kolibri-1) Detailed open LLM model card with energy and good documentation.   

The tutorial is split into three notebooks. Each runs on its own, but they
are meant to be read in this order:

| Notebook | | |
|---|---|---|
| [getting_started.ipynb](notebooks/getting_started.ipynb) | Measure the energy and emissions of an existing Python script, and of each step of a pipeline (an LDA topic model). | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/seankellyhp/eco-measure-amsterdam/blob/main/notebooks/getting_started.ipynb) |
| [sentiment_tracking.ipynb](notebooks/sentiment_tracking.ipynb) | Measure dictionary and transformer (DistilBERT) sentiment analysis, and benchmark the Bing dictionary in polars, NLTK's VADER and transformers against each other. | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/seankellyhp/eco-measure-amsterdam/blob/main/notebooks/sentiment_tracking.ipynb) |
| [llm_tracking.ipynb](notebooks/llm_tracking.ipynb) | Estimate the energy and emissions of sentiment analysis with a hosted language model, with EcoLogits. | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/seankellyhp/eco-measure-amsterdam/blob/main/notebooks/llm_tracking.ipynb) |

An R version of the tutorial is also available, using
[TidyCarbon](https://github.com/seankellyhp/Tidycarbon). It has aligned content, but in one jupyter notebook only:

| Notebook | | |
|---|---|---|
| [tidycarbon_tutorial.ipynb](notebooks/tidycarbon_R/tidycarbon_tutorial.ipynb) | Measure the energy and emissions of R programs with tidycarbon: tidytext dictionary sentiment, a tidytext vs. quanteda benchmark, and LLMs with ellmer. | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/seankellyhp/eco-measure-amsterdam/blob/main/notebooks/tidycarbon_R/tidycarbon_tutorial.ipynb) |

## Option A: Google Colab (nothing to install)

Click **Open in Colab** next to a notebook, sign in with a Google account,
and run the cells from top to bottom. The first cell installs the missing
packages and downloads the data, which takes about a minute.

## Option B: your own machine

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then:

```bash
git clone https://github.com/seankellyhp/eco-measure-amsterdam
cd eco-measure-amsterdam
uv sync --extra cpu
uv run jupyter lab notebooks/getting_started.ipynb
```

`uv sync --extra cpu` installs Python and every package, at the versions in
[uv.lock](uv.lock), with the CPU-only build of PyTorch, which the
transformer model in `sentiment_tracking` uses. It works on every machine,
and the download stays small. Don't leave out `--extra cpu`: a plain
`uv sync` removes PyTorch.

**NVIDIA GPU (Linux or Windows).** To run the model on an NVIDIA GPU, install
the CUDA build of PyTorch instead (about 3 GB more to download):

```bash
uv sync --extra cu132
```

It needs an NVIDIA driver for CUDA 13: run `nvidia-smi` and check that the
top right shows `CUDA Version: 13.0` or higher. If it shows a lower version,
update the driver, or use `--extra cpu`. GPUs older than the GTX 16 and
RTX 20 series are not supported by CUDA 13; use Colab with a GPU runtime
instead. If the GPU cannot be used, the notebook says
`The model runs on: cpu` and carries on, on the CPU. To switch back, run
`uv sync --extra cpu`.

**Mac.** Use `--extra cpu`. On an Apple Silicon Mac the model runs on the
Mac's GPU. PyTorch no longer supports Intel Macs; use Colab instead.

The last command opens Getting Started in your browser; if
no browser opens, copy the `http://localhost:8888/...` link that Jupyter prints in
the terminal. The other two notebooks are next to it in the `notebooks` folder, in
the file browser on the left. Leave the terminal open while you work;
Ctrl+C stops Jupyter. The data are in [data/](data/). NLTK downloads its
tokenizer models and lexicon into the virtual environment on the first run,
and transformers downloads its sentiment model (about 270 MB) into the
Hugging Face cache. The sentiment model runs on an NVIDIA GPU if you
installed the CUDA build, on the GPU of an Apple Silicon Mac, and on the CPU
otherwise.

## The language model section

The last cell of `llm_tracking` sends a request to a language model through
[OpenRouter](https://openrouter.ai), which needs an API key and costs money.
Everything else runs without one. On Colab, add the key as a secret
named `OPENROUTER_API_KEY` (key icon in the left sidebar). Locally, put it in a
`.env` file:

```
OPENROUTER_API_KEY=sk-or-...
```

## Optional: I have included an Easter Egg for those using a local coding agent. This is experimental but yours to try out. 

[carbon_skill/](carbon_skill/) is a program plus a skill for
[Claude Code](https://claude.com/claude-code) that applies the same tools to
an agent's own work: what the computer used while the agent worked (CodeCarbon),
how many tokens the session used, and an estimate of what generating them cost
in the provider's datacenter (EcoLogits). Tested on Linux; might work on Windows and Mac. 
Currently only supports Claude. Submissions welcome. 

```bash
uv tool install ./carbon_skill
carbon install-skill
carbon doctor
```

Or ask your agent to "install the carbon skill by following
carbon_skill/README.md". See [carbon_skill/README.md](carbon_skill/README.md).

## Files

| File | |
|---|---|
| [notebooks/](notebooks/) | The three Python notebooks (`.ipynb`, for Colab or Jupyter) and their Quarto sources (`.qmd`), and the R notebook in [notebooks/tidycarbon_R/](notebooks/tidycarbon_R/). |
| [data/](data/) | Jane Austen's six novels and the Bing sentiment lexicon, exported from the R packages janeaustenr and tidytext by [data/make_data.R](data/make_data.R). |
| [slides/](slides/) | Copy of the presentation. |
| [figures/](figures/) | Images used in the notebooks. |
| [carbon_skill/](carbon_skill/) | The optional `/carbon` program and skill for Claude Code. |

The notebooks are generated from the Quarto sources. After editing a `.qmd`
file, rebuild the notebooks with

```bash
uv run --group docs quarto render
```

The `docs` group installs Quarto, which participants do not need. The build
settings, including the bibliography, are in [_quarto.yml](_quarto.yml). The
notebooks are built without running the code, so they have no saved outputs.
