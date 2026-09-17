# Minimal makefile for Sphinx documentation
# `make html` to build, `make clean` to wipe _build, `make serve` to live-reload.

SPHINXOPTS    ?= -W --keep-going
SPHINXBUILD   ?= sphinx-build
SOURCEDIR     = .
BUILDDIR      = _build

.PHONY: help clean html serve

help:
	@$(SPHINXBUILD) -M help "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS)

clean:
	rm -rf "$(BUILDDIR)"

html:
	$(SPHINXBUILD) -M html "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS)
	@echo
	@echo "Build finished. Open $(BUILDDIR)/html/index.html in a browser."

serve:
	$(SPHINXBUILD) -M html "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS)
	@echo
	@echo "Open http://localhost:8000 with:"
	@echo "  python -m http.server -d $(BUILDDIR)/html"

# Catch-all target: route other targets to Sphinx
%: Makefile
	$(SPHINXBUILD) -M $@ "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS)
