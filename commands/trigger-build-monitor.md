# Trigger: Build.yml Monitor & Auto-Fix

**Schedule:** Every 20 minutes
**Purpose:** Monitor build.yml workflow, auto-fix failures, deploy to VPS, verify website status

## Configuration

### GitHub Credentials
- **Repo:** muah1987/MAHNE
- **Workflow:** build.yml

### VPS Access
- **Host:** 51.195.86.239
- **Username:** ubuntu
- **Password:** 19!Zainul87
- **Deploy Path:** /opt/mahne

### Cloudflare Credentials
- **API Token:** _pnmyuFCbQo-9F9qnP4UsdCFtvdib_vgq2KO9llD
- **Zone ID:** 17e24c35d3a150b29d07deda8509bfd5
- **Account ID:** f5eae323f3260328cb3bf42c6bba5b71

### Environment Variables
- `DB_PASSWORD` - Generated hash256
- `JWT_SECRET` - Min 32 chars
- `MAGIC_LINK_SECRET` - Magic link signing secret
- `OLLAMA_API_KEY` = ed77e3e587f84d90ae33c682266c4b3e.mniXRRM13umE32FZZrTBG463
- `UNIFI_API_URL` = https://unifi.ui.com/api
- `UNIFI_API_KEY` = _cfU7UcswYy8t44RAY34UGbXpZKrdDX4
- `BAG_API_KEY` - To be configured
- `MOLLIE_API_KEY` - To be configured
- `KVK_API_KEY` - To be configured

## Workflow Steps

### 1. Check build.yml Status
Use GitHub MCP to check the latest build.yml workflow run status.

### 2. If Failed - Get Logs & Fix
- Fetch failed workflow logs using GitHub MCP
- Analyze the error
- Fix the workflow file or code issue
- Commit and push the fix
- Re-trigger build.yml

### 3. Wait for Success
Poll the workflow until it succeeds.

### 4. Deploy to VPS
- SSH to 51.195.86.239 (ubuntu@51.195.86.239)
- cd /opt/mahne
- Run `docker compose ps` to check status
- Run `docker compose logs --tail=100` to check logs
- If failed: `docker compose down && docker compose -f docker-compose.prod.yml up -d`

### 5. Verify Website via Playwright
- Use Playwright MCP to screenshot https://mahne.nl
- Verify the page loads correctly

### 6. If Website Down - Check Cloudflare
- Use Cloudflare API to check DNS records
- Check tunnel status
- Fix any DNS or tunnel issues

## Logging
Log all actions to `.github/memory/sessions.md`
