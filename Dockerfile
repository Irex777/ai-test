FROM nginx:alpine
COPY index.html /usr/share/nginx/html/index.html
COPY kanban/ /usr/share/nginx/html/kanban/
COPY dashboard/ /usr/share/nginx/html/dashboard/
COPY chess/ /usr/share/nginx/html/chess/
COPY markdown/ /usr/share/nginx/html/markdown/
EXPOSE 80
