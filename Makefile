SHELL := /bin/bash

.PHONY: test lint validate package iso smoke clean

test:
	python3 -m pytest

lint:
	python3 -m compileall -q src tests
	./scripts/lint-shell

validate: lint test
	python3 scripts/validate-project

package:
	./scripts/build-package

iso:
	./scripts/build-iso

smoke:
	./scripts/boot-smoke-test

clean:
	./scripts/clean-build

