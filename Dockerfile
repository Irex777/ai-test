FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html /usr/share/nginx/html/
COPY methodology.html /usr/share/nginx/html/
COPY kanban/ /usr/share/nginx/html/kanban/
COPY dashboard/ /usr/share/nginx/html/dashboard/
COPY chess/ /usr/share/nginx/html/chess/
COPY markdown/ /usr/share/nginx/html/markdown/
COPY calculator/ /usr/share/nginx/html/calculator/
COPY snake/ /usr/share/nginx/html/snake/
COPY pomodoro/ /usr/share/nginx/html/pomodoro/
COPY weather/ /usr/share/nginx/html/weather/
COPY password/ /usr/share/nginx/html/password/
COPY gta/ /usr/share/nginx/html/gta/
COPY webos/ /usr/share/nginx/html/webos/
