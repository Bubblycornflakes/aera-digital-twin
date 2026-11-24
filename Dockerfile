# AERA and AeroBench demo. Build: docker build -t aera .   Run: docker run -p 8061:8061 aera
FROM node:22-slim AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY aera ./aera
COPY examples ./examples
COPY scripts ./scripts
COPY results/runs ./results/runs
COPY --from=web /app/frontend/dist ./frontend/dist
# The IWA BSM1 archive is downloaded from the official release and checksum-verified, not bundled.
RUN python scripts/fetch_bsm1.py
EXPOSE 8061
CMD ["python", "-m", "uvicorn", "aera.api:app", "--host", "0.0.0.0", "--port", "8061"]
