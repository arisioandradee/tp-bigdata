FROM python:3.11-slim-bookworm
RUN pip install --no-cache-dir "elasticsearch>=8.15,<9"
COPY setup.py /setup.py
CMD ["python", "/setup.py"]
