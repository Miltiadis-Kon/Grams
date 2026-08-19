# Tailscale Setup Guide — Grams Local Stack

This guide explains how to expose your locally-hosted Grams app over Tailscale
so you can access it from any of your devices (phone, laptop, etc.) anywhere.

## Prerequisites

- Docker Desktop installed and running
- Tailscale account ([tailscale.com](https://tailscale.com/)) — free for personal use

---

## 1. Install Tailscale on Windows

Download and install from: https://tailscale.com/download/windows

After installation, sign in through the system tray icon or run:

```powershell
tailscale up
```

This registers your machine on your tailnet.

---

## 2. Start the App Stack

```powershell
# From the project root:
docker compose --env-file .env.local up -d
```

Verify it is running:

```powershell
docker compose ps
# Both grams_postgres and grams_app should show "running"
```

Test locally first:

```powershell
curl http://localhost:5000/api/recipes
```

---

## 3. Find Your Tailscale IP

```powershell
tailscale ip -4
# Example output: 100.x.y.z
```

Or open the Tailscale tray icon → click your machine name.

---

## 4. Access From Any Device

On any device logged into the same Tailscale account:

```
http://100.x.y.z:5000
```

Replace `100.x.y.z` with your machine's Tailscale IP.

> **Tip**: Set a stable Tailscale hostname in the admin console at
> https://login.tailscale.com/admin/machines so you can use
> `http://your-machine-name:5000` instead of the IP.

---

## 5. (Optional) Tailscale MagicDNS

Enable MagicDNS in the Tailscale admin panel so you can use:

```
http://your-machine-name.tail12345.ts.net:5000
```

---

## 6. (Optional) Tailscale Funnel — Public HTTPS Access

If you want a public HTTPS URL (accessible without Tailscale on the client):

```powershell
tailscale funnel 5000
```

This gives you a URL like `https://your-machine-name.tail12345.ts.net`
that anyone can access — no VPN needed.

> **Note**: Funnel requires Tailscale account verification. Run
> `tailscale funnel status` to check.

---

## 7. Auto-Start on Boot (Recommended)

### Docker Compose auto-start:

Docker Desktop on Windows can be configured to start automatically.
The `restart: unless-stopped` policy in `docker-compose.yml` means containers
restart after Docker starts.

### Tailscale auto-start:

Tailscale installs as a Windows service and starts automatically at boot.

---

## Quick Reference

| Action | Command |
|--------|---------|
| Start stack | `docker compose --env-file .env.local up -d` |
| Stop stack | `docker compose down` |
| View logs | `docker compose logs -f app` |
| Get Tailscale IP | `tailscale ip -4` |
| Enable funnel | `tailscale funnel 5000` |
| Check Tailscale status | `tailscale status` |
| Connect to PG directly | `psql -h localhost -U grams -d grams` |
