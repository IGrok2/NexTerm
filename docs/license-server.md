# License Server Setup

NexTerm Enterprise activation expects static JSON files at:

```text
http://193.23.221.4/licenses/<ACTIVATION_CODE>.json
```

Generate 16 activation files:

```powershell
python tools\generate_licenses.py
```

Copy the generated folder to the server:

```powershell
scp -r server\licenses root@193.23.221.4:/var/www/html/
```

Example Nginx config:

```nginx
server {
    listen 80;
    server_name 193.23.221.4;
    root /var/www/html;

    location /licenses/ {
        add_header Access-Control-Allow-Origin *;
        try_files $uri =404;
    }
}
```

Reload:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

Fallback behavior:

- if the server is online, NexTerm validates the signature and expiry;
- if the server is offline, NexTerm uses the cached license for 14 days;
- if there is no valid cache, NexTerm falls back to Standard.

Security note:

This is a practical desktop licensing layer. Because Python desktop binaries can
be reverse engineered, do not treat the client as a perfect trust boundary. Keep
billing, customer records and license generation on the server side.
