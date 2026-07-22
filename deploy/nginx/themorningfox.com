server {
    listen 8080;
    server_name themorningfox.com www.themorningfox.com;
    root /home/elucia/dev/jina-clone/web;
    index index.html;
    access_log /var/log/morningfox/access.log;
    autoindex off;

    include snippets/security-headers.conf;
    include snippets/deny-dotfiles.conf;
    include snippets/error-pages.conf;

    location = /ai  { return 302 https://feed.themorningfox.com/ai-digest/latest.html; }
    location = /ai/ { return 302 https://feed.themorningfox.com/ai-digest/latest.html; }
    location = /stats { return 301 https://$host/stats/; }
    location / { try_files $uri $uri/ =404; }
    location /editions/ { alias /home/elucia/dev/jina-clone/briefings/; }
}

server {
    listen 443 ssl;
    server_name themorningfox.com www.themorningfox.com;
    root /home/elucia/dev/jina-clone/web;
    index index.html;
    access_log /var/log/morningfox/access.log;
    autoindex off;

    include snippets/security-headers.conf;
    include snippets/deny-dotfiles.conf;
    include snippets/error-pages.conf;

    location = /ai  { return 302 https://feed.themorningfox.com/ai-digest/latest.html; }
    location = /ai/ { return 302 https://feed.themorningfox.com/ai-digest/latest.html; }
    location / { try_files $uri $uri/ =404; }
    location /editions/ { alias /home/elucia/dev/jina-clone/briefings/; }

    # Visitor stats dashboard (GoAccess) — password-protected, HTTPS only.
    location = /stats { return 301 /stats/; }
    location /stats/ {
        alias /var/www/morningfox-stats/;
        access_log off;
        index index.html;
        auth_basic "Morning Fox Stats";
        auth_basic_user_file /etc/nginx/.htpasswd-stats;
    }

    ssl_certificate /etc/letsencrypt/live/themorningfox.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/themorningfox.com/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;
}
