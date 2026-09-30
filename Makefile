PY_FILES = __init__.py fbx.py mixamo_blender_importer.py

# Folder name inside the zip = the add-on's module name in Blender (Install from Disk keeps it).
PACKAGE = JA-Mixamo-Importer
ZIP = Blender-JA-Mixamo-Importer.zip

DOC = ja_mixamo_importer_doc

ZIP_CONTENTS = $(PY_FILES) README.md

PEP8_FILES = $(PY_FILES) tests/*.py tests/tools/*.py

.PHONY: all format pep8 clean

all: build/$(ZIP) build/$(DOC).pdf

format:
	autopep8 --in-place $(PEP8_FILES)

pep8:
	pycodestyle --config=.pep8 $(PEP8_FILES)

build/$(ZIP): $(ZIP_CONTENTS)
	rm -rf build/$(PACKAGE) $@
	mkdir -p build/$(PACKAGE)
	cp $(ZIP_CONTENTS) build/$(PACKAGE)
	(cd build; zip -r $(ZIP) $(PACKAGE))

build/$(DOC).pdf: $(DOC).tex
	mkdir -p build
	pdflatex --output-directory=build $(DOC).tex
	pdflatex --output-directory=build $(DOC).tex  # second pass for the table of contents

clean:
	rm -rf build
