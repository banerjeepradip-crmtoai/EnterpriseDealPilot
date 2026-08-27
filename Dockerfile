# Builds one image shared by every mcp-services/* deployment. Which
# service actually runs is selected at container start by MCP_SERVICE_DIR
# (set per Cloud Run service at deploy time — see infrastructure/README.md)
# rather than by baking six near-identical Dockerfiles. Full repo as
# build context on purpose: fixture-mode salesforce/documents read
# samples/ from outside their own service directory, and this avoids
# duplicating those fixtures into every service's own folder.
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "cd \"$MCP_SERVICE_DIR\" && python server.py"]
