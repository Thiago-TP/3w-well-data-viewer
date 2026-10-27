# Presentation at the 5th 3W Workshop

This folder holds the files that build the PDF used to present this GUI at the 5th 3W Workshop.
The slides are a beamer deck whose look is the official PowerPoint template of the workshop,
`5th_ws3w.pptx`, reproduced by a beamer theme of its own.

| File                           | What it is                                                                                                            |
| ------------------------------ | --------------------------------------------------------------------------------------------------------------------- |
| `presentation.tex`             | the deck: fourteen frames for the fifteen minutes, the screenshots taken from [`docs/assets/`](../assets)            |
| `beamerthemews3w.sty`          | the theme after the template: its colors and font, the logos, the content, title and closing layouts                  |
| `latexmkrc`                    | what `latexmk` reads: LuaLaTeX, the auxiliary files in `build/` (gitignored), the PDF in this folder                  |
| `assets/`                      | the template's own media, extracted from the pptx: the gold network of the background, the Petrobras and 3W logos     |

## Building

If you have a LaTeX distribution installed (as well as the necessary packages),
you can build the presentation by `cd`'ing into this folder and running

```bash
latexmk          # presentation.pdf, by LuaLaTeX; the auxiliary files go to build/
latexmk -pdf     # the same by pdfLaTeX
latexmk -C       # remove everything built
```

in the terminal/shell. Alternatively, you can use a LaTeX IDE of your choice (Overleaf, TeXStudio, etc.).

- The template is set in **Trebuchet MS**. Under LuaLaTeX (or XeLaTeX) the theme uses it whenever
  the system has it, as Windows and macOS do, and falls back to Fira Sans, which TeX Live ships,
  otherwise; under pdfLaTeX it uses Fira Sans. The first LuaLaTeX run may spend a minute building
  the font database.
- Two passes are needed, the logos and titles being placed with TikZ's `remember picture`;
  `latexmk` runs both.
- Beyond beamer and TikZ the deck needs `fontspec` (or `FiraSans` under pdfLaTeX), `booktabs`,
  `array` and `qrcode`, all in TeX Live and on Overleaf.
- The title frame reads the title, subtitle, author, institute and date set in the preamble;
  `\wsclosingframe[contact lines]{message}` draws the closing frame. Content frames are ordinary
  beamer frames.

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
