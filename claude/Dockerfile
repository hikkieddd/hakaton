FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONIOENCODING=utf-8
ENV BK_DATA_DIR=/srv/data

WORKDIR /srv

COPY app/requirements.txt /srv/app/requirements.txt
RUN pip install --no-cache-dir -r /srv/app/requirements.txt

COPY app /srv/app
COPY data /srv/data

EXPOSE 8765

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8765} --app-dir /srv/app/backend"]
