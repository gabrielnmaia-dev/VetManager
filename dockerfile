FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /VetManager

COPY requirementes.txt .

RUN pip install --upgrade pip && \
    pip install -r requirementes.txt

COPY . .

EXPOSE 8000

