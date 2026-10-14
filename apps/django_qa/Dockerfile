FROM public.ecr.aws/docker/library/python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv/qa
COPY apps/django_qa/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY apps/django_qa/ .
RUN python manage.py check
EXPOSE 8001
CMD ["sh", "-ec", "python manage.py migrate --noinput && exec gunicorn bidcheck_django_qa.wsgi:application --bind 0.0.0.0:8001 --workers 1 --threads 2 --timeout 80 --access-logfile -"]
