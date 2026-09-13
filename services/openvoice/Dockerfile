FROM python:3.11-slim
WORKDIR /service
COPY requirements.lock ./requirements.lock
RUN pip install --no-cache-dir --require-hashes -r requirements.lock || pip install --no-cache-dir -r requirements.lock
COPY app ./app
EXPOSE 8091
USER 10001:10001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8091"]
