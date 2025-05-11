FROM ubuntu:22.04
RUN apt-get update && apt-get install -y python3 python3-pip curl
WORKDIR /app
COPY fast_server.py .
COPY requirements.txt .
COPY bin/ ./bin/
COPY models/ ./models/

RUN pip install -r requirements.txt

EXPOSE 8000
CMD ["python3", "fast_server.py", "--port", "8000","--model","phi3.5:3.8b-mini-instruct-q6_K"]
