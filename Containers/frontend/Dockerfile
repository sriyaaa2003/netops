FROM nginx:1.27-alpine

COPY templates/default.conf.template /etc/nginx/templates/default.conf.template
COPY index.html /usr/share/nginx/html/index.html

# Makes the entrypoint export NGINX_LOCAL_RESOLVERS from /etc/resolv.conf,
# used by the resolver directive in default.conf.template.
ENV NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
