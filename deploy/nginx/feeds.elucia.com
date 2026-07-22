server {
    listen 8080;
    server_name feeds.elucia.com;
    root /home/elucia/dev/jina-clone/feeds;
    autoindex off;

    include snippets/security-headers.conf;
    include snippets/deny-dotfiles.conf;
    include snippets/error-pages.conf;

    location = /ai-digest/ { return 302 /ai-digest/latest.html; }
    location / { try_files $uri $uri/ =404; }
}

server {
    listen 443 ssl;
    server_name feeds.elucia.com;
    root /home/elucia/dev/jina-clone/feeds;
    autoindex off;

    include snippets/security-headers.conf;
    include snippets/deny-dotfiles.conf;
    include snippets/error-pages.conf;

    location = /ai-digest/ { return 302 /ai-digest/latest.html; }
    location / { try_files $uri $uri/ =404; }

    ssl_certificate /etc/letsencrypt/live/feeds.elucia.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/feeds.elucia.com/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;
}
