# Deployment Notes

## VPS Photo Upload Fix

**Issue**: Image uploads worked locally but not on VPS deployment.

**Root Cause**: The production Docker Compose configuration was missing a persistent volume for uploaded files. Files were being written to the container's temporary filesystem and lost when the container restarted.

**Solution**: Added `uploads_data` volume to persist uploads at `/app/runtime/uploads` in the backend container.

### Changes Made

**File**: `deploy/docker-compose.prod.yml`

1. Added volume mount to backend service:
   ```yaml
   volumes:
     - uploads_data:/app/runtime/uploads
   ```

2. Defined the persistent volume:
   ```yaml
   volumes:
     uploads_data:
   ```

### Deployment Instructions

After pulling this change on the VPS:

```bash
cd /opt/friend-hub/app
git pull origin main
docker compose --env-file .env -f deploy/docker-compose.prod.yml up -d --build
```

The new `uploads_data` volume will be created automatically. Existing uploads are not affected - the volume is additive.

### File Serving

- Files uploaded to `/api/v1/photos` are stored at `/app/runtime/uploads/photos` in the container
- This maps to the `uploads_data` Docker volume on the VPS host
- The Caddyfile correctly proxies `/uploads/*` requests to the backend
- The backend's StaticFiles mount at `/uploads/photos` serves these files

### Testing

After deployment:
1. Upload a photo from chat
2. Verify the image displays in the message
3. Restart the backend container: `docker compose -f deploy/docker-compose.prod.yml restart backend`
4. Verify the image still displays (confirming volume persistence)
