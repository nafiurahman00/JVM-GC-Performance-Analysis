# Makefile for LaTeX project

# Project name (without extension)
PROJECT = main

# Compiler options
LATEXMK = latexmk
LATEXMK_FLAGS = -pdf -interaction=nonstopmode

all: $(PROJECT).pdf

$(PROJECT).pdf: $(PROJECT).tex
	$(LATEXMK) $(LATEXMK_FLAGS) $(PROJECT).tex

clean:
	$(LATEXMK) -c
	rm -f *.bbl *.run.xml *.synctex.gz

distclean: clean
	$(LATEXMK) -C

.PHONY: all clean distclean $(PROJECT).pdf
