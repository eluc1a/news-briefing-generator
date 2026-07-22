server {
    listen 8080;
    server_name feed.themorningfox.com;
    root /home/elucia/dev/jina-clone/feeds;
    access_log /var/log/morningfox/access.log;
    autoindex off;

    include snippets/security-headers.conf;
    include snippets/deny-dotfiles.conf;
    include snippets/error-pages.conf;

    location = / { return 302 /ai-digest/latest.html; }
    location = /ai-digest/ { return 302 /ai-digest/latest.html; }
    location = /ai-digest/latest.html {
        add_header Cache-Control "no-store" always;
        include snippets/security-headers.conf;
        try_files $uri =404;
    }
    location / { try_files $uri $uri/ =404; }
}

server {
    listen 443 ssl;
    server_name feed.themorningfox.com;
    root /home/elucia/dev/jina-clone/feeds;
    access_log /var/log/morningfox/access.log;
    autoindex off;

    include snippets/security-headers.conf;
    include snippets/deny-dotfiles.conf;
    include snippets/error-pages.conf;

    location = / { return 302 /ai-digest/latest.html; }
    location = /ai-digest/ { return 302 /ai-digest/latest.html; }
    location = /ai-digest/latest.html {
        add_header Cache-Control "no-store" always;
        include snippets/security-headers.conf;
        try_files $uri =404;
    }
    location / { try_files $uri $uri/ =404; }

    ssl_certificate /etc/letsencrypt/live/feed.themorningfox.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/feed.themorningfox.com/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;
}
