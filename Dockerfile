FROM python:3.11-slim
LABEL maintainer="AI Trading Office"
ENV PYTHONUNBUFFERED=1 OFFICE_HOST=0.0.0.0 OFFICE_PORT=8080 TZ=Asia/Ho_Chi_Minh
WORKDIR /app
COPY server.py /app/server.py
COPY static /app/static
COPY skills /app/skills
RUN mkdir -p /app/data
EXPOSE 8080
HEALTHCHECK --interval=60s --timeout=5s CMD python3 -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/api/health',timeout=4)" || exit 1
CMD ["python3", "server.py"]
