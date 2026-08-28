# Refreshes the Salesforce session the dealpilot-live Cloud Run service
# runs on and rolls a new revision so it picks it up.
#
# Why this exists: the live-mode backend on Cloud Run authenticates with
# SALESFORCE_SESSION_ID/SALESFORCE_INSTANCE_URL (see
# mcp-services/salesforce/client.py). That token has no self-heal there —
# self-heal shells out to the `sf` CLI, which only exists on a developer
# machine, not inside the container (see client.py's _refresh_session_via_cli
# docstring) — so once the org session expires (session timeout is 24h,
# see salesforce-metadata/README.md), the live demo backend just fails
# until someone mints a fresh token and redeploys. Run this any time
# before a demo recording session to be sure it's fresh.
#
# Requires: `sf` CLI already authenticated locally (sf org login web),
# `gcloud` already authenticated with access to the enterprisedealpilot
# project. Never prints the session token to the console.

$ErrorActionPreference = "Stop"
$gcloud = "C:\gcloud-sdk\bin\gcloud.cmd"
$scratchDir = [System.IO.Path]::GetTempPath()
$sessionFile = Join-Path $scratchDir "sf_session_id.secret"
$urlFile = Join-Path $scratchDir "sf_instance_url.secret"

Write-Host "Minting a fresh Salesforce session via sf CLI..."
$env:SF_TEMP_SHOW_SECRETS = "true"
$orgInfo = (sf org display --target-org enterprisedealpilot --json | ConvertFrom-Json).result
Remove-Item Env:\SF_TEMP_SHOW_SECRETS

Set-Content -Path $sessionFile -Value $orgInfo.accessToken -NoNewline
Set-Content -Path $urlFile -Value $orgInfo.instanceUrl -NoNewline

Write-Host "Pushing new Secret Manager versions..."
& $gcloud secrets versions add salesforce-session-id --project enterprisedealpilot --data-file="$sessionFile" | Out-Null
& $gcloud secrets versions add salesforce-instance-url --project enterprisedealpilot --data-file="$urlFile" | Out-Null

Remove-Item $sessionFile, $urlFile -Force

Write-Host "Rolling a new Cloud Run revision to pick up the refreshed secrets..."
& $gcloud run services update dealpilot-live `
  --region us-central1 `
  --project enterprisedealpilot `
  --update-secrets="SALESFORCE_SESSION_ID=salesforce-session-id:latest,SALESFORCE_INSTANCE_URL=salesforce-instance-url:latest" | Out-Null

Write-Host "Done. dealpilot-live is now running with a fresh Salesforce session."
