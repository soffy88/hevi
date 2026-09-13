FROM python:3.11-slim
WORKDIR /service
COPY requirements.lock ./requirements.lock
RUN pip install --no-cache-dir --require-hashes -r requirements.lock || pip install --no-cache-dir -r requirements.lock
COPY app ./app
COPY model_bootstrap.py ./model_bootstrap.py
RUN mkdir -p /models/openvoice && chown -R 10001:10001 /models
VOLUME ["/models/openvoice"]
ENV OPENVOICE_MODEL_DIR=/models/openvoice
EXPOSE 8091
USER 10001:10001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8091"]
