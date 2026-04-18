FROM python:3.12-slim

WORKDIR /app

# Install deps
COPY web/requirements.txt ./web_requirements.txt
RUN pip install --no-cache-dir -r web_requirements.txt

# Copy application code
COPY wechat_automation/ ./wechat_automation/
COPY config/ ./config/
COPY web/ ./web/

ENV PORT=8080
EXPOSE 8080

CMD ["uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8080"]
