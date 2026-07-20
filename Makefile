IMAGE ?= ipecho
TAG ?= dev
NS ?= devops-lab
GF_ADMIN_PASS ?= admin

.PHONY: install test lint run docker-build helm-lint deploy smoke \
        k3s-deploy geoip-secret geoip-local grafana-secret grafana-config grafana-deploy clean

install:
	pip install -r app/requirements.txt -r app/requirements-dev.txt

test:
	cd app && pytest -q

lint:
	ruff check app

run:
	cd app && uvicorn main:app --host 0.0.0.0 --port 8080 --reload

docker-build:
	docker build -t $(IMAGE):$(TAG) .

helm-lint:
	helm lint charts/ipecho

deploy:
	helm upgrade --install ipecho charts/ipecho -n staging --create-namespace \
		--set image.tag=$(TAG) --wait --timeout 300s

smoke:
	kubectl -n staging port-forward svc/ipecho 8080:80 & sleep 4; \
	curl -f localhost:8080/health && curl -f localhost:8080/ready

k3s-deploy: geoip-secret
	helm upgrade --install ipecho charts/ipecho -n $(NS) \
		-f deploy/values-k3s.yaml --set image.tag=$(TAG) --wait --timeout 300s

geoip-secret:
	kubectl apply -f deploy/namespace.yaml
	kubectl -n $(NS) create secret generic ipecho-geoip \
		--from-literal=license=$(MAXMIND_LICENSE_KEY) \
		--dry-run=client -o yaml | kubectl apply -f -

geoip-local:
	mkdir -p app/data
	curl -sSL "https://download.maxmind.com/app/geoip_download?edition_id=GeoLite2-City&license_key=$(MAXMIND_LICENSE_KEY)&suffix=tar.gz" \
		| tar -xz -C /tmp
	cp /tmp/GeoLite2-City_*/GeoLite2-City.mmdb app/data/GeoLite2-City.mmdb
	@echo "Listo. Corré:  GEOIP_DB=$(PWD)/app/data/GeoLite2-City.mmdb make run"

grafana-secret:
	kubectl -n $(NS) create secret generic ipecho-grafana-admin \
		--from-literal=user=admin --from-literal=password=$(GF_ADMIN_PASS) \
		--dry-run=client -o yaml | kubectl apply -f -

grafana-config:
	kubectl -n $(NS) create configmap ipecho-grafana-datasources \
		--from-file=grafana/datasources --dry-run=client -o yaml | kubectl apply -f -
	kubectl -n $(NS) create configmap ipecho-grafana-dashprovider \
		--from-file=grafana/dashboards-provider --dry-run=client -o yaml | kubectl apply -f -
	kubectl -n $(NS) create configmap ipecho-grafana-dashboards \
		--from-file=grafana/dashboards --dry-run=client -o yaml | kubectl apply -f -

grafana-deploy: grafana-secret grafana-config
	kubectl apply -f deploy/grafana.yaml
	kubectl -n $(NS) rollout restart deploy/ipecho-grafana

clean:
	rm -f image.tar sbom.cyclonedx.json
	rm -rf .venv
