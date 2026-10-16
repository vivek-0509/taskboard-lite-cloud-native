# GitOps for TaskBoard Lite

**Student:** Vivek Singh Solanki | **Roll number:** 24bcs10338

**Git is the source of truth.** Nobody runs `kubectl apply` against the
cluster by hand; a controller (Argo CD) watches the repository and makes the
cluster match what is committed. Every change to the running system is a
commit with an author, a review and a diff, and rolling back is `git revert`.

## Files

| File | Purpose |
|---|---|
| `argocd-application.yaml` | the Argo CD `Application`: which repo, branch and path to watch, which cluster/namespace to sync to, and the sync policy |
| `manifests/kustomization.yaml` | what Argo CD renders: a self-contained copy of the Kubernetes manifests (namespace, configmap, secret, pvc, deployment, service, hpa; the Ingress is cluster-specific and left out) |

The Kubernetes objects themselves are not duplicated here. `kubernetes/` stays
the single definition; the kustomization only references it and swaps the
image name/tag.

## Workflow

```
developer ----PR----> main ----CI (test, scans, build, push ghcr)----> image :<sha>
                        |
                        | (1) PR bumps gitops/manifests/kustomization.yaml newTag -> <sha>
                        v
                  Argo CD polls main (every 3 min) or receives a webhook
                        |
                        | (2) kustomize build gitops/manifests  ->  desired state
                        | (3) diff against the live cluster
                        v
                  sync: kubectl apply the diff, prune removed objects, self-heal drift
```

1. **Code change** - a pull request touches `application/`. The pipeline runs
   tests and the security gate, builds the image and pushes
   `ghcr.io/vivek-0509/taskboard-lite:<git sha>` (and `:latest`).
2. **Config change** - a second, tiny pull request edits one line:
   `newTag: <git sha>` in `manifests/kustomization.yaml`. The reviewer sees
   exactly which image goes live. Merging it is the deployment.
3. **Reconciliation** - Argo CD notices the new commit on `main`, renders the
   kustomization and compares it with the cluster. Only the Deployment's image
   differs, so it patches that; Kubernetes performs the rollout
   (`Recreate`, because of the RWO volume). The Application shows
   `Synced` / `Healthy` once the pods pass their readiness probes.
4. **Drift** - if someone runs `kubectl scale deployment taskboard-lite --replicas=1`
   or deletes the ConfigMap, `selfHeal: true` puts it back within seconds and
   `prune: true` removes anything that is not in git.
5. **Rollback** - `git revert` the tag bump (or any other commit); Argo CD
   syncs the previous state. No cluster access is needed.

### How image tag updates happen

- Manual (this project): edit `newTag` in `manifests/kustomization.yaml` via a
  pull request. The sha tag is printed in the `push-image` job summary.
- Automated (next step): the pipeline's last job commits the tag bump itself
  (`kustomize edit set image taskboard-lite=ghcr.io/...:<sha>` and `git push`),
  or Argo CD Image Updater watches GHCR and writes the tag back to git.
  Either way the cluster still only follows git.

Why not `latest`? With `imagePullPolicy: IfNotPresent` a node that already
has `latest` will never pull the new build, and even with `Always` nobody can
tell from git which version is running. A sha tag is reproducible and
reviewable; `latest` is only the default so the first sync works before any
tag was pinned.

## Running it on minikube

```bash
# 1. install Argo CD
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
kubectl -n argocd rollout status deployment/argocd-server

# 2. (optional) extra kustomize build flags for the repo server
kubectl -n argocd patch cm argocd-cm --type merge \
  -p '{"data":{"kustomize.buildOptions":"--load-restrictor LoadRestrictionsNone"}}'
kubectl -n argocd rollout restart deployment/argocd-repo-server

# 3. register the application
kubectl apply -f gitops/argocd-application.yaml

# 4. watch it sync
kubectl -n argocd get application taskboard-lite -w
kubectl -n taskboard get all

# UI: https://localhost:8080 (user admin)
kubectl -n argocd port-forward svc/argocd-server 8080:443
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d; echo
```

Prerequisites on the cluster side:

- The GHCR package must be public, or the `taskboard` namespace needs an
  `imagePullSecret` (`kubectl create secret docker-registry ghcr ...`) referenced
  by the Deployment.
- `metrics-server` for the HPA (`minikube addons enable metrics-server`);
  without it the HPA shows `<unknown>` but still keeps `minReplicas`.

Render locally without a cluster:

```bash
kubectl kustomize gitops/manifests   # or: kustomize build gitops/manifests
```

## Secrets in GitOps

`kubernetes/secret.yaml` holds a demo value only. In a real GitOps setup the
Secret is either committed encrypted (Sealed Secrets, SOPS + age) so that only
the cluster can decrypt it, or replaced by an `ExternalSecret` that pulls the
value from a vault at sync time. The pipeline's gitleaks stage allowlists the
one demo string precisely so that anything else looking like a credential is
still caught.
