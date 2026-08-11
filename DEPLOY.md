# Deployment Guide: Frontend on Vercel + Backend on Your Machine

## Prerequisites (install on your 16GB personal machine)

1. **Docker Desktop**: https://www.docker.com/products/docker-desktop/
   ```
   winget install Docker.DockerDesktop
   ```
   Restart your machine after install. Open Docker Desktop and wait for it to start.

2. **ngrok**: https://ngrok.com (sign up for free account)
   ```
   winget install ngrok.ngrok
   ngrok config add-authtoken YOUR_AUTH_TOKEN
   ```

3. **Vercel CLI** (already installed on your dev machine):
   ```
   npm i -g vercel
   ```

---

## Step 1: Start the Backend (Docker Compose)

```bash
cd backend
docker compose up -d
```

This starts: Kafka, InfluxDB, API Gateway, ML Service, Correction Engine, TSDB Writer, C-MAPSS Adapter.

Verify: `curl http://localhost:8000/health` should return all components healthy.

---

## Step 2: Expose Backend via ngrok

```bash
ngrok http 8000
```

ngrok will show a public URL like: `https://abc123.ngrok-free.app`

Copy this URL — you'll need it for the frontend config.

---

## Step 3: Deploy Frontend to Vercel

```bash
cd frontend

# Set the backend URL as an environment variable
vercel env add NEXT_PUBLIC_API_URL     # paste: https://abc123.ngrok-free.app
vercel env add NEXT_PUBLIC_WS_URL      # paste: wss://abc123.ngrok-free.app/ws/telemetry

# Deploy
vercel --prod
```

Vercel gives you a URL like: `https://digital-twin-engine.vercel.app`

---

## Step 4: Access

- Frontend: `https://digital-twin-engine.vercel.app`
- Backend health: `https://abc123.ngrok-free.app/health`
- WebSocket: `wss://abc123.ngrok-free.app/ws/telemetry`

---

## Before Your Demo

1. Start Docker Desktop
2. Run `docker compose up -d` in the backend folder
3. Run `ngrok http 8000`
4. If the ngrok URL changed, update Vercel env vars and redeploy:
   ```
   vercel env rm NEXT_PUBLIC_API_URL
   vercel env add NEXT_PUBLIC_API_URL   # new ngrok URL
   vercel env rm NEXT_PUBLIC_WS_URL
   vercel env add NEXT_PUBLIC_WS_URL    # wss://new-url/ws/telemetry
   vercel --prod
   ```

## Tips

- ngrok free tier changes URLs each restart. For a stable URL, upgrade to ngrok's $8/month plan (static domain) or use Cloudflare Tunnel (free, stable subdomain).
- Keep Docker Desktop running during your demo.
- The full Docker Compose stack uses ~2-3GB RAM — well within your 16GB.
- Unlike local mode, the Docker stack runs indefinitely with no timeout.
