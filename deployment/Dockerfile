# Autor: oswaldo.diaz@inegi.org.mx
# Usar la imagen base oficial de Python 3.11 en su versión ligera slim
FROM python:3.11-slim
# Establecer el directorio de trabajo dentro del contenedor en /app
WORKDIR /app
# Copiar todos los archivos del directorio local actual al directorio /app del contenedor
COPY . /app
# Ejecutar la actualización de pip e instalar dependencias básicas sin guardar caché
RUN pip install --no-cache-dir --upgrade pip
# Definir el comando predeterminado (será sobrescrito por cada servicio en docker-compose)
CMD ["python", "agent_asset_discovery.py"]