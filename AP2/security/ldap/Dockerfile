FROM python:3.12-slim
RUN pip install --no-cache-dir ldap3==2.9.1
COPY seed.py /seed.py
CMD ["python", "/seed.py"]
