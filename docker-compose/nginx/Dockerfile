# Базовый образ с официальным nginx
FROM nginx:stable-alpine

# Копируем конфиг и сертификаты (если вы хотите собрать их в образ)
# Если используете volume‑монтирование, эти строки можно закомментировать.
COPY nginx.conf /etc/nginx/nginx.conf
COPY cert/ /etc/nginx/cert/