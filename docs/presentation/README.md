# Presentation at the 5th 3W Workshop

This folder holds the files that build the PDF used to present this GUI at the 5th 3W Workshop.
The slides are a beamer deck whose look is the official PowerPoint template of the workshop,
`template_5o_ws3w.pptx`, reproduced by a beamer theme of its own. The talk follows
[issue #24](https://github.com/Thiago-TP/3w-well-data-viewer/issues/24): one section per page of
the viewer, each the page's research question and what looking at 3W through it finds.

| File                           | What it is                                                                                                            |
| ------------------------------ | --------------------------------------------------------------------------------------------------------------------- |
| `presentation.tex`             | the deck: the title frame, one `\input` per section, the closing frame, then the appendix                             |
| `sections/`                    | one file per section: `timelines.tex`, `availability.tex`, `faults.tex`, `dispersions.tex`, `references.tex` (the paper and thesis the slides cite, set without a `.bib` file) and `appendix.tex` so far                      |
| `figures/`                     | what the sections draw, one folder per section: the charts (`.tikz`), the numbers they quote, the CSV tables behind the charts, crops of the viewer |
| `tables/`                      | the tables the sections set, one folder per section: the tabulars (`.tex`) and, where a table is long, the CSV it reads |
| `scripts/`                     | what writes the numbers, CSV tables and crops, one script per section, from the 3W dataset and the viewer's own code |
| `beamerthemews3w.sty`          | the theme after the template: its colors and font, the logos, the content, title and closing layouts                  |
| `latexmkrc`                    | what `latexmk` reads: LuaLaTeX, the auxiliary files in `build/` (gitignored), the PDF in this folder                  |
| `assets/`                      | the template's own media, extracted from the pptx: the gold network of the background, the Petrobras and 3W logos     |
| `presentation.pdf`             | the built deck, versioned so that it can be read without a LaTeX distribution                                         |

## Building

If you have a LaTeX distribution installed (as well as the necessary packages),
you can build the presentation by `cd`'ing into this folder and running

```bash
latexmk          # presentation.pdf, by LuaLaTeX; the auxiliary files go to build/
latexmk -pdf     # the same by pdfLaTeX
latexmk -C       # remove everything built
```

in the terminal/shell. Alternatively, you can use a LaTeX IDE of your choice (Overleaf, TeXStudio, etc.).

> [!WARNING]
> The deck is meant to be built by **LuaLaTeX**, which `latexmk` uses here because `latexmkrc` says
> so. A LaTeX IDE does not read `latexmkrc` and compiles with pdfLaTeX unless told otherwise: set
> its compiler to LuaLaTeX (on Overleaf, *Menu → Compiler*; in TeXstudio, *Options → Configure →
> Build → Default Compiler*). Under pdfLaTeX the deck still builds, but in Fira Sans instead of the
> template's Trebuchet MS, so lines break elsewhere and a frame that fits under LuaLaTeX may not.
> Even under LuaLaTeX, a system without Trebuchet MS (Linux, Overleaf) falls back to Fira Sans.
> The first LuaLaTeX run on a machine builds its font database, which can take a few minutes with
> no output; later runs take seconds.

- Two passes are needed, the logos and titles being placed with TikZ's `remember picture`;
  `latexmk` runs both.
- Beyond beamer and TikZ the deck needs `fontspec` (or `FiraSans` under pdfLaTeX), `pgfplots`,
  `pgfplotstable`, `booktabs`, `multirow` and `array`, all in TeX Live and on Overleaf.
- The title frame reads the title, subtitle, author, institute and date set in the preamble;
  `\wsclosingframe{message}{line}{line}` draws the closing frame. Content frames are ordinary
  beamer frames; a `\framesubtitle` takes the line under the title, where the sections put the
  page and its research question. The theme places everything from the page's anchors with
  TikZ's `positioning` library, and draws each logo with one command, so that a logo has one size
  (and the Petrobras logo one place) on every layout.
- The appendix follows the closing frame, after `\appendix`: frames the talk points to (a button
  jumps there) but has no time to show.

## Figures and numbers

Every figure a section quotes is a macro of `figures/<section>/numbers.tex`, every chart
(`figures/<section>/*.tikz`) reads a CSV table beside it, and the crops of the viewer are PNG
files there too; a long table (`tables/<section>/*.tex`) reads a CSV table beside it the same way.
None of the numbers, CSV tables or crops is written by hand: the script of the section writes
them, from the root of the repository:

```bash
uv run python docs/presentation/scripts/timelines.py                  # numbers, tables and crops
uv run python docs/presentation/scripts/timelines.py --no-shots       # numbers and tables only
uv run python docs/presentation/scripts/timelines.py --raw-dir PATH   # another copy of 3W
uv run python docs/presentation/scripts/availability.py               # the Availability section (no crops)
uv run python docs/presentation/scripts/faults.py                     # the Faults and Features section, likewise
uv run python docs/presentation/scripts/dispersions.py                # the Dispersions section, likewise
uv run python docs/presentation/scripts/appendix.py                   # the appendix, likewise
```

The scripts need what the viewer needs and nothing more: the project's environment (`uv sync`),
whose PySide6 and pyqtgraph render the crops offscreen (`scripts/offscreen.py`, shared by every
script), and a local copy of the 3W dataset (`../3W/dataset` from the root of the repository by
default). They read the catalogue the viewer caches, so the numbers take seconds once the viewer
has scanned the dataset; the crops read the few instances they show (the sixteen of the appendix
take about a minute and a half). Since `figures/` and `tables/` are versioned, the deck builds
without the dataset; the scripts are for when the dataset, or the viewer, changes.

| Script         | Writes                                                                                                               |
| -------------- | -------------------------------------------------------------------------------------------------------------------- |
| `timelines.py` | into `figures/timelines/`: `numbers.tex`; `overlaps.csv` (instances per well); `labels-pre-join.csv` and `labels-post-join.csv` (each folder's time by label, its files apart and joined); `gaps.csv` (what stays unlabeled once joined); `returns.csv` (every return to normal along a joined history); `well4_overlaps.png` and `well4_restrictions.png` (the Timelines page and an instance window on WELL-00004) |
| `availability.py` | into `figures/availability/`: `numbers.tex`; `coverage.csv` (every variable's samples live, frozen and missing, the readings among them that are implausible, out of order or against the state, the instances of each and the reading farthest outside the plausible range, which the chart draws and the appendix sets). No crops. It reads the profile pass from the viewer's cache, and stops if the pass has not been run: tick *Measured vs filled* on the Availability page once |
| `faults.py` | into `tables/faults/`: `signatures.csv` (per fault class, its instances and wells, and per signature variable the move the paper or thesis expects, how many instances make it of those that can show it, and how many lack the variable); `hydrate.csv` (the well state under each label of every real Hydrate in Production Line); into `figures/faults/`: `numbers.tex`; `scaling.png` (the Faults page on Scaling in PCK, one instance per well); `well19.png` and `well25.png` (the instance window of a hydrate of each well on P-TPT); `simulated.csv` and `simulated-bands.csv` (a simulated hydrate, which the viewer does not read, for `simulated.tikz` to draw in the instance window's style). It reads the signature variables of about 500 instances, about a minute |
| `dispersions.py` | into `tables/dispersions/`: `pairs.csv` (per fault class, its pair of sensors, the two live in the most samples of those every instance of the class records live, and their Pearson coefficient over its normal operation, transient and steady state, on every sample and on the measurements alone, with how many these are); into `tables/appendix/`: `wells.csv` (the same per well); into `figures/dispersions/`: `numbers.tex`; `wells.csv` and `pooled.csv` (every well's coefficient and the pooled one, on every sample and on the measurements alone, for `wells.tikz`). No crops: it reads every row of the pair of each class, rather than the page's subsample, in under a minute once the viewer has cached the dataset |
| `appendix.py`  | into `tables/appendix/`: `changes.csv` (every label change across an unlabeled stretch of a joined history, with the sensor shown); into `figures/appendix/`: `change-<n>.png` (each change in the instance window) |

## Instructions communicated via email (portuguese)
O uso do template anexo é incentivado, mas não é considerado obrigatório;
O compartilhamento voluntário dos badges anexos em suas redes sociais é incentivado. Isso ampliará a divulgação sobre o nosso workshop;
Exemplo aqui. Aliás, se você puder comentar e/ou compartilhar essa publicação será ótimo.
A imagem anexa é para uso facultativo como fundo de tela durante o workshop;
Teremos até 15 minutos para cada apresentação (inclusive a sua);
Interações (perguntas, observa e respostas) sobre todas as apresentações em cada manhã serão agrupadas em período dedicado no final de cada manhã;
A versão final da programação será posteriormente divulgada;
Solicitamos você nos enviar, como resposta a este e-mail, o material que você pretende apresentar;
Precisamos receber todos os materiais o quanto antes e até 08/11/26 (domingo);
Recomendamos conteúdo compatível com até 15 minutos de exposição;
É essencial que a relação entre o seu trabalho e o 3W seja ressaltada;
O material não pode conter conteúdo nem comercial nem sensível (restrito ou confidencial);
Eventuais ajustes poderão ser solicitados entre essa data e o dia anterior ao início do workshop.
Como o workshop será híbrido em relação a idioma, solicitamos que:
O material seja elaborado 100% em Inglês;
A exposição seja realizada em Português ou Inglês, conforme sua escolha pessoal;
Perguntas e comentários poderão ser feitos em Inglês e nesse caso respostas deverão ser feitas nos dois idiomas, possivelmente com suporte dos anfitriões.
