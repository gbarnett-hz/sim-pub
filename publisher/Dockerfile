FROM python:3.12.5-alpine

WORKDIR /app
COPY publish.py requirements.txt ./
RUN pip install -r requirements.txt

ENTRYPOINT ["python", "publish.py"]
