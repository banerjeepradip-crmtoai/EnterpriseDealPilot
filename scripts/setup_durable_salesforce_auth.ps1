# One-time setup: stores durable Salesforce username/password/security-token
# credentials in Google Secret Manager so dealpilot-live can authenticate on
# every request instead of relying on a session token that expires.
#
# Why this fixes the "have to remember to refresh" problem for good: see
# mcp-services/salesforce/client.py's LiveSalesforceClient — when
# SALESFORCE_SESSION_ID is unset, it falls into the username/password path,
# which calls simple_salesforce's Salesforce(username=..., password=...,
# security_token=...) fresh on every LiveSalesforceClient() construction
# (and get_client() constructs a fresh one on every request — see
# get_client() in that same file). That's a brand-new login every time,
# so there's no token to expire and nothing to refresh, ever.
#
# Run this ONCE, interactively, on your own machine. Values are read with
# masked input and go straight to Secret Manager — they are never printed,
# logged, or committed anywhere, and Claude never sees them.
#
# Requires: `gcloud` already authenticated with access to the
# enterprisedealpilot project.

$ErrorActionPreference = "Stop"
$gcloud = "C:\gcloud-sdk\bin\gcloud.cmd"
$scratchDir = [System.IO.Path]::GetTempPath()

function Set-SecretFromSecureString {
    param([string]$SecretName, [System.Security.SecureString]$Value)

    $plain = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($Value)
    )
    $file = Join-Path $scratchDir "$SecretName.secret"
    try {
        Set-Content -Path $file -Value $plain -NoNewline

        # Native commands write "not found" to stderr, which PowerShell
        # promotes into a terminating error under $ErrorActionPreference =
        # "Stop" even with 2>$null — so this check needs its own relaxed
        # scope rather than relying on the script-wide setting.
        $previousPref = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        & $gcloud secrets describe $SecretName --project enterprisedealpilot *> $null
        $exists = ($LASTEXITCODE -eq 0)
        $ErrorActionPreference = $previousPref

        if ($exists) {
            & $gcloud secrets versions add $SecretName --project enterprisedealpilot --data-file="$file" | Out-Null
        } else {
            & $gcloud secrets create $SecretName --project enterprisedealpilot --replication-policy=automatic --data-file="$file" | Out-Null
        }
        Write-Host "Stored $SecretName in Secret Manager."
    } finally {
        Remove-Item $file -Force -ErrorAction SilentlyContinue
        $plain = $null
    }
}

Write-Host "Enter your Salesforce login for the enterprisedealpilot org."
Write-Host "Nothing you type here is shown to Claude or saved to disk beyond this run."
Write-Host ""

$username = Read-Host "Salesforce username (e.g. you@enterprisedealpilot.com)"
$password = Read-Host "Salesforce password" -AsSecureString
$securityToken = Read-Host "Salesforce security token" -AsSecureString
$domain = Read-Host "Domain: 'login' for production/dev-ed org, 'test' for a sandbox [login]"
if ([string]::IsNullOrWhiteSpace($domain)) { $domain = "login" }

$usernameSecure = ConvertTo-SecureString $username -AsPlainText -Force

Set-SecretFromSecureString -SecretName "salesforce-username" -Value $usernameSecure
Set-SecretFromSecureString -SecretName "salesforce-password" -Value $password
Set-SecretFromSecureString -SecretName "salesforce-security-token" -Value $securityToken

# domain isn't a secret, but keeping it alongside the others as one keeps
# the Cloud Run --set-secrets wiring uniform.
$domainSecure = ConvertTo-SecureString $domain -AsPlainText -Force
Set-SecretFromSecureString -SecretName "salesforce-domain" -Value $domainSecure

Write-Host ""
Write-Host "Done. Credentials are in Secret Manager. Tell Claude you're ready"
Write-Host "and it will grant dealpilot-live access to these secrets and"
Write-Host "redeploy it onto durable auth."
