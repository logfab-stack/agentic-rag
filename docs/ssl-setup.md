# SSL/TLS Setup Guide

This guide explains how to configure HTTPS for the Agentic RAG System in production deployments.

> **Feature #326**: HTTPS and security headers

## Overview

The application supports multiple SSL/TLS deployment options:

1. **Self-signed certificates** (development/testing)
2. **Manual certificates** (Let's Encrypt, commercial CAs)
3. **Automatic certificates** via Traefik (recommended for production)

## Security Headers

When SSL is enabled, the following security headers are automatically added:

| Header | Purpose | Default Value |
|--------|---------|---------------|
| `Strict-Transport-Security` | Forces HTTPS connections | `max-age=31536000; includeSubDomains` |
| `X-Frame-Options` | Prevents clickjacking | `SAMEORIGIN` |
| `X-Content-Type-Options` | Prevents MIME sniffing | `nosniff` |
| `X-XSS-Protection` | XSS filter (legacy) | `1; mode=block` |
| `Referrer-Policy` | Controls referrer info | `strict-origin-when-cross-origin` |
| `Permissions-Policy` | Restricts browser features | Disables sensors, camera, etc. |
| `Content-Security-Policy` | Controls resource loading | Self + API endpoints |

## Option 1: Self-Signed Certificates (Development)

Generate self-signed certificates for local testing:

```bash
# Create certs directory
mkdir -p certs

# Generate self-signed certificate (valid for 365 days)
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout certs/privkey.pem \
  -out certs/fullchain.pem \
  -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"

# Set permissions
chmod 600 certs/privkey.pem
chmod 644 certs/fullchain.pem
```

Then start with SSL:

```bash
docker compose -f docker-compose.prod.yml -f docker-compose.ssl.yml up -d
```

> **Note**: Browsers will show a security warning for self-signed certificates. This is expected for development.

## Option 2: Manual Certificates (Let's Encrypt)

### Prerequisites

- A domain name pointing to your server
- Port 80 and 443 accessible from the internet
- Certbot installed

### Get Certificates

```bash
# Install certbot (Ubuntu/Debian)
sudo apt-get update
sudo apt-get install certbot

# Get certificate (standalone mode - stop existing web server first)
sudo certbot certonly --standalone -d yourdomain.com -d www.yourdomain.com

# Certificates are saved to:
# - /etc/letsencrypt/live/yourdomain.com/fullchain.pem
# - /etc/letsencrypt/live/yourdomain.com/privkey.pem
```

### Configure Environment

Create or update your `.env` file:

```env
# Domain configuration
DOMAIN=yourdomain.com
CORS_ORIGINS=https://yourdomain.com,https://www.yourdomain.com

# SSL paths
SSL_CERT_PATH=/etc/letsencrypt/live/yourdomain.com/fullchain.pem
SSL_KEY_PATH=/etc/letsencrypt/live/yourdomain.com/privkey.pem

# Enable SSL
SSL_ENABLED=true
FORCE_HTTPS=true
```

### Start with SSL

```bash
docker compose -f docker-compose.prod.yml -f docker-compose.ssl.yml up -d
```

### Auto-Renewal

Set up a cron job to renew certificates:

```bash
# Edit crontab
sudo crontab -e

# Add renewal job (runs daily at 2:30 AM)
30 2 * * * certbot renew --quiet --deploy-hook "docker restart agentic-rag-frontend"
```

## Option 3: Automatic Certificates with Traefik (Recommended)

Traefik automatically obtains and renews Let's Encrypt certificates.

### Prerequisites

- Domain name pointing to your server
- Ports 80 and 443 accessible from the internet

### Configure Environment

```env
# Domain and email for Let's Encrypt
DOMAIN=yourdomain.com
ACME_EMAIL=your-email@example.com

# CORS origins
CORS_ORIGINS=https://yourdomain.com

# Enable SSL in backend
SSL_ENABLED=true
FORCE_HTTPS=true
```

### Start with Traefik

```bash
# Create the network first (if not exists)
docker network create agentic-rag-network

# Start all services with Traefik
docker compose -f docker-compose.prod.yml -f docker-compose.ssl.yml \
  --profile traefik up -d
```

### Verify

```bash
# Check Traefik logs for certificate issuance
docker logs agentic-rag-traefik

# Access Traefik dashboard (if enabled)
https://traefik.yourdomain.com
```

## Configuration Reference

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SSL_ENABLED` | Enable SSL mode in backend | `false` |
| `FORCE_HTTPS` | Redirect HTTP to HTTPS | `false` |
| `SSL_CERT_PATH` | Path to certificate file | `./certs/fullchain.pem` |
| `SSL_KEY_PATH` | Path to private key file | `./certs/privkey.pem` |
| `DOMAIN` | Domain for Traefik routing | `localhost` |
| `ACME_EMAIL` | Email for Let's Encrypt | `admin@example.com` |
| `FRONTEND_HTTPS_PORT` | HTTPS port mapping | `443` |

### Security Headers Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `SECURITY_HEADERS_ENABLED` | Enable security headers | `true` |
| `HSTS_MAX_AGE` | HSTS duration (seconds) | `31536000` (1 year) |
| `HSTS_INCLUDE_SUBDOMAINS` | Include subdomains in HSTS | `true` |
| `HSTS_PRELOAD` | Enable HSTS preload | `false` |
| `X_FRAME_OPTIONS` | Frame embedding policy | `SAMEORIGIN` |
| `CSP_DIRECTIVES` | Content Security Policy | (see default) |
| `PERMISSIONS_POLICY` | Browser feature policy | (see default) |

## Testing SSL Configuration

### Check Certificate

```bash
# View certificate details
openssl s_client -connect yourdomain.com:443 -servername yourdomain.com </dev/null 2>/dev/null | openssl x509 -noout -text

# Check expiration
openssl s_client -connect yourdomain.com:443 -servername yourdomain.com </dev/null 2>/dev/null | openssl x509 -noout -dates
```

### Verify Security Headers

```bash
# Check response headers
curl -I https://yourdomain.com

# Expected headers:
# Strict-Transport-Security: max-age=31536000; includeSubDomains
# X-Frame-Options: SAMEORIGIN
# X-Content-Type-Options: nosniff
# Content-Security-Policy: default-src 'self'; ...
```

### Online Tools

- **SSL Labs**: https://www.ssllabs.com/ssltest/
- **Security Headers**: https://securityheaders.com/
- **Mozilla Observatory**: https://observatory.mozilla.org/

## Troubleshooting

### Certificate Not Found

```
nginx: [emerg] cannot load certificate "/etc/nginx/ssl/fullchain.pem"
```

**Solution**: Ensure certificates are mounted correctly in docker-compose.ssl.yml

### Mixed Content Warnings

Browser blocks HTTP resources on HTTPS page.

**Solution**:
1. Ensure `FORCE_HTTPS=true` is set
2. Update `CSP_DIRECTIVES` to include `upgrade-insecure-requests`

### CORS Errors

API requests blocked due to CORS.

**Solution**: Update `CORS_ORIGINS` to include your HTTPS domain:
```env
CORS_ORIGINS=https://yourdomain.com
```

### Certificate Renewal Failed (Traefik)

Check Traefik logs:
```bash
docker logs agentic-rag-traefik
```

Common issues:
- Port 80 blocked (Let's Encrypt needs HTTP challenge)
- DNS not pointing to server
- Rate limited (use staging server for testing)

## Security Best Practices

1. **Always use HTTPS in production** - Never transmit sensitive data over HTTP
2. **Enable HSTS** - Prevents downgrade attacks
3. **Keep certificates updated** - Set up auto-renewal
4. **Use strong ciphers** - The nginx configs use Mozilla's recommended cipher suite
5. **Monitor certificate expiration** - Set up alerts before expiry
6. **Review CSP regularly** - Update as your application's needs change
7. **Test with security scanners** - Use SSL Labs, Security Headers, etc.

## Nginx Configuration Files

- `frontend/nginx.conf` - HTTP configuration with security headers
- `frontend/nginx-ssl.conf` - Full HTTPS configuration with TLS settings

When using Traefik, the standard `nginx.conf` is used since Traefik handles SSL termination.
