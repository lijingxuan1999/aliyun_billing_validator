.PHONY: all build deploy

all: build deploy

build:
	mbt build

deploy:
	cf deploy mta_archives/billing-validator-mcp_1.0.0.mtar
