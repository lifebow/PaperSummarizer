.PHONY: verify pre-push install-hooks

verify:
	./scripts/harness.sh

pre-push:
	./scripts/harness.sh --pre-push

install-hooks:
	./scripts/install-hooks.sh
