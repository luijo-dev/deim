.PHONY: setup dev run test check deploy service-url

PROJECT_ID ?= $(shell gcloud config get-value project)
REGION     ?= us-central1
SERVICE    ?= deim
IMAGE_URI  ?= gcr.io/$(PROJECT_ID)/$(SERVICE)

setup:
	uv sync

dev:
	uv run streamlit run main.py --server.headless true

run:
	uv run streamlit run main.py --server.headless true

test:
	uv run pytest -q

check:
	uv run ruff check .

deploy:
	gcloud builds submit --config=cloudbuild.yaml --substitutions=_IMAGE_URI=$(IMAGE_URI)
	gcloud run deploy $(SERVICE) \
		--image $(IMAGE_URI) \
		--region $(REGION) \
		--platform managed \
		--port 8080 \
		--no-allow-unauthenticated

service-url:
	gcloud run services describe $(SERVICE) --region $(REGION) --format 'value(status.url)'
