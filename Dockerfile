# Use official lightweight Python image
FROM python:3.10-slim

# Set working directory inside the container
WORKDIR /app

# Set environment variables to optimize Python runtime in Docker
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Copy the requirements file first and leverage Docker cache
COPY requirements.txt .

# Install all python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy all the remaining project files
COPY . .

# Expose port 8000 for FastAPI
EXPOSE 8000

# Command to run the application using Uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]