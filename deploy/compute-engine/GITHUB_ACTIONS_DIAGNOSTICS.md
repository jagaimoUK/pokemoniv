# Compute Engine: GitHub Actions read-only diagnostics

## Status and scope

**Proposal only. No VM, GCP IAM, running container, database or feature flag has been changed by this PR.**

The existing Google Cloud Compute Engine VM is `pokemoniv-web` in `asia-northeast1-a`. The workflow can run exactly one of `health`, `storage`, or `missing` through IAP and a fixed root-owned VM-side diagnostic helper. The workflow **cannot** accept arbitrary commands, perform deployment, edit files or change databases. It accepts either a manual Run workflow action or one of three exact owner-authored PR #118 comments: `/gce health`, `/gce storage`, `/gce missing`.

GitHub's `main` branch is protected. Review this PR and merge before activation. Manual dispatch requires `github.actor == 'jagaimoUK'`. The comment trigger is limited to PR #118, exact command bodies, and immutable comment author ID `121705998`. Both require `github.ref == 'refs/heads/main'`. It uses a dedicated WIF service account with no JSON keys and pinned actions. Authentication to Google Cloud **and** VM-side sudoers are separate one-time setups.

**Connector limitation and fallback:** ChatGPT's installed GitHub connector has no workflow-dispatch action, but can add a PR comment. GitHub may trigger the workflow from a ChatGPT-posted exact PR #118 comment if the comment is attributed to the approved user account; this has not yet been validated. Otherwise invoke **Run workflow** manually. The PR-comment body is never executed as shell code; only the fixed allowlisted command is executed. Never broaden the author, issue number, or command filters without security review.

## Security gates before any changes to Google Cloud

1. Check existing **effective OS Login** settings in project and VM metadata. **Do not automatically enable OS Login.** Enabling it can disable access using existing SSH metadata keys and change the currently working browser SSH login.
2. Confirm Google Cloud Console access and a recovery route. Verify the VM snapshot and preserve its existing SSH.
3. Confirm IAP TCP forwarding can reach TCP/22 on this VM. Do not expose application port 8787 or broaden public SSH firewall access.
4. Check which service account is attached to the VM, so `roles/iam.serviceAccountUser`, if required, can be limited to **that one attached account**.

## Google Cloud: one-time WIF (Google Cloud owner)

Use the Cloud Console equivalent or the commands below **after reviewing the target project**. These commands do **not** enable OS Login, grant VM SSH roles, or touch a running VM. They require IAM administration permissions.

```sh
PROJECT_ID='YOUR_GCP_PROJECT_ID'
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
POOL_ID='pokemoniv-github'
PROVIDER_ID='pokemoniv-main-diagnostics'
SA="pokemoniv-gce-diagnostics@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud iam service-accounts create pokemoniv-gce-diagnostics --project="$PROJECT_ID" --display-name='PokemonIV GCE read-only diagnostics'
gcloud iam workload-identity-pools create "$POOL_ID" --project="$PROJECT_ID" --location=global --display-name='PokemonIV GitHub Actions'

gcloud iam workload-identity-pools providers create-oidc "$PROVIDER_ID" \
  --project="$PROJECT_ID" --location=global --workload-identity-pool="$POOL_ID" \
  --issuer-uri='https://token.actions.githubusercontent.com/' \
  --attribute-mapping='google.subject=assertion.sub,attribute.repository_id=assertion.repository_id' \
  --attribute-condition="assertion.repository_id=='1415557002' && assertion.repository_owner_id=='121705998' && assertion.ref=='refs/heads/main' && assertion.workflow_ref=='jagaimoUK/pokemoniv/.github/workflows/gce-readonly-diagnostics.yml@refs/heads/main' && (assertion.event_name=='workflow_dispatch' || assertion.event_name=='issue_comment')"

gcloud iam service-accounts add-iam-policy-binding "$SA" \
  --project="$PROJECT_ID" --role='roles/iam.workloadIdentityUser' \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/attribute.repository_id/1415557002"
```

**Additional scoped IAM roles only after OS Login safety review:** grant `roles/compute.osLogin` and `roles/iap.tunnelResourceAccessor` **on VM `pokemoniv-web` only** (restrict IAP to TCP/22). `gcloud compute ssh` may also require project-level `compute.projects.get` and instance metadata reads: preferably a custom read-only role, or `roles/compute.viewer` if its wider visibility is acceptable. If this VM has an attached service account, Google documents an additional `roles/iam.serviceAccountUser` grant **on that account only**. Do not use `roles/compute.osAdminLogin`, `roles/compute.instanceAdmin.v1`, Owner or Editor.

Set GitHub repository **Settings → Secrets and variables → Actions → Variables** (not Secrets):

| Variable | Value |
|---|---|
| `GCE_PROJECT_ID` | Your Google Cloud project ID |
| `GCE_WIF_PROVIDER` | `projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/pokemoniv-github/providers/pokemoniv-main-diagnostics` |
| `GCE_DIAG_SERVICE_ACCOUNT` | `pokemoniv-gce-diagnostics@PROJECT_ID.iam.gserviceaccount.com` |

Do not upload a private SSH key, JSON service-account key, root API key, or raw VM logs.

## VM bootstrap: separately approved one-time step

The workflow invokes `sudo -n /usr/local/sbin/pokemoniv-readonly-diagnostics {health|storage|missing}`. The helper does not yet exist on the VM. **Do not run the workflow until it is installed.**

After this PR is merged, inspect the pinned merged commit and install `deploy/compute-engine/gce_readonly_diagnostics.py` from that exact commit to `/usr/local/sbin/pokemoniv-readonly-diagnostics` with root ownership and mode 0755. Avoid using a floating GitHub URL. Establish the exact **Google OS Login POSIX username** for the new service-account identity. Then create a root-owned `/etc/sudoers.d/pokemoniv-gce-diagnostics` (0440), with only:

```text
OSLOGIN_USERNAME ALL=(root) NOPASSWD: /usr/local/sbin/pokemoniv-readonly-diagnostics health, /usr/local/sbin/pokemoniv-readonly-diagnostics storage, /usr/local/sbin/pokemoniv-readonly-diagnostics missing
```

No wildcards, unrestricted sudo, or Docker group membership. Verify with `visudo -cf /etc/sudoers.d/pokemoniv-gce-diagnostics` **before** closing the currently working SSH session. Do not make this change if OS Login safety or exact username remains uncertain.

## Validation and rollback

After setup: add the exact comment `/gce health` to PR #118 using ChatGPT GitHub integration, **or** GitHub → Actions → **GCE read-only diagnostics** → **Run workflow** → `health`. Confirm that a new Actions run actually started; do not assume a PR comment triggers a run until observed. Confirm HTTP 200, healthy container and approved image. Run `storage` to inspect mount paths, free space and database existence; `missing` checks the internal game-data catalog and feature switches without reading user records.

**Warning:** The GitHub repository is public. Actions logs must contain **no user IVs, credentials, database contents, arbitrary runtime logs or raw HTTP responses**. The helper intentionally emits limited metadata only.

On any access failure, stop and investigate instead of broadening IAM or disabling security protections. To disable, remove or disable the workflow and revoke the dedicated WIF/IAP/OS Login bindings. This workflow contains no production mutation and requires no data restore.

Official references:
- https://github.com/google-github-actions/auth
- https://docs.cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines
- https://docs.cloud.google.com/compute/docs/oslogin/set-up-oslogin
- https://docs.cloud.google.com/iap/docs/using-tcp-forwarding
