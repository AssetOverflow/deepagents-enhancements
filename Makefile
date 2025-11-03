PYTHON_FILES=.
MYPY_CACHE=.mypy_cache

.PHONY: lint lint_diff lint_package lint_tests lint_mcp format format_diff test test_mcp

lint format: PYTHON_FILES=.
lint_diff format_diff: PYTHON_FILES=$(shell git diff --relative=src/deepagents --name-only --diff-filter=d master | grep -E '\.(py|ipynb)$$')
lint_package: PYTHON_FILES=src/deepagents
lint_tests: PYTHON_FILES=tests
lint_mcp: PYTHON_FILES=src/deepagents/integrations/mcp tests/mcp

lint lint_diff lint_package lint_tests lint_mcp:
	[ "$(PYTHON_FILES)" = "" ] || uv run --all-groups ruff check $(PYTHON_FILES)
	[ "$(PYTHON_FILES)" = "" ] || uv run --all-groups ruff format $(PYTHON_FILES) --diff
	[ "$(PYTHON_FILES)" = "" ] || mkdir -p $(MYPY_CACHE) && uv run --all-groups mypy $(PYTHON_FILES) --cache-dir $(MYPY_CACHE)

format format_diff:
	[ "$(PYTHON_FILES)" = "" ] || uv run --all-groups ruff format $(PYTHON_FILES)
	[ "$(PYTHON_FILES)" = "" ] || uv run --all-groups ruff check --fix $(PYTHON_FILES)

# Test targets --------------------------------------------------------------

test:
	uv run --all-groups pytest

# Run only the deterministic MCP unit tests (skips optional live smoke checks)
test_mcp:
	uv run --all-groups pytest tests/mcp
