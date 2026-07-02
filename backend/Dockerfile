FROM python:3.12-slim

WORKDIR /project

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend as a package so relative imports resolve
COPY . ./backend

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
