# Troubleshooting scenarios

**Student:** Vivek Singh Solanki | **Roll number:** 24bcs10338

Four manifests in this directory are **intentionally broken**. Each one
reproduces a failure that is common in real clusters, in the `taskboard`
namespace, without touching the working `taskboard-lite` Deployment (the
scenario objects have their own names and labels and use `emptyDir` instead
of the PVC).

Prerequisites: the namespace, ConfigMap and Secret from `kubernetes/` exist
and the image is loaded into minikube.

```bash
kubectl apply -f kubernetes/namespace.yaml -f kubernetes/configmap.yaml -f kubernetes/secret.yaml
minikube image load taskboard-lite:local
```

General diagnostic loop used for every scenario:

```bash
kubectl -n taskboard get pods -o wide                 # STATUS / READY column
kubectl -n taskboard describe pod <pod>               # Events at the bottom
kubectl -n taskboard logs <pod> --previous            # when the container did start
kubectl -n taskboard get endpoints <service>          # does the Service see any pod?
kubectl -n taskboard get events --sort-by=.lastTimestamp | tail -20
```

The "Observed output" blocks are left empty on purpose; they are filled with
the real `kubectl` output and a screenshot when the scenarios are executed.

---

## 01 - Wrong image tag (`01-broken-image.yaml`)

**Bug.** `image: taskboard-lite:v9.9.9` - that tag was never built.

**Expected symptom.** The pod cycles through `ErrImagePull` and
`ImagePullBackOff`; `READY 0/1`. `describe pod` shows
`Failed to pull image "taskboard-lite:v9.9.9"` and
`Back-off pulling image`.

```bash
kubectl apply -f troubleshooting/01-broken-image.yaml
kubectl -n taskboard get pods -l app.kubernetes.io/instance=scenario-01 -w
kubectl -n taskboard describe pod -l app.kubernetes.io/instance=scenario-01 | tail -15
```

**Fix.** Point the Deployment at an image that exists in the cluster.

```bash
kubectl -n taskboard set image deployment/taskboard-broken-image taskboard-lite=taskboard-lite:local
kubectl -n taskboard rollout status deployment/taskboard-broken-image
```

(Or edit the manifest, change the tag to `local`, and `kubectl apply` again.)

**Observed output.**

```text
(paste the kubectl output here after running the scenario)
```

---

## 02 - Service selector mismatch (`02-broken-service.yaml`)

**Bug.** Pods are labelled `app.kubernetes.io/instance: scenario-02`; the
Service selects `scenario-2`.

**Expected symptom.** The pod is `Running 1/1`, but
`kubectl get endpoints taskboard-broken-selector` shows `<none>`.
`kubectl port-forward svc/taskboard-broken-selector` fails because no pod
matches, and `curl` from another pod gets `connection refused`.

```bash
kubectl apply -f troubleshooting/02-broken-service.yaml
kubectl -n taskboard get pods -l app.kubernetes.io/instance=scenario-02
kubectl -n taskboard get endpoints taskboard-broken-selector
kubectl -n taskboard get svc taskboard-broken-selector -o jsonpath='{.spec.selector}'; echo
kubectl -n taskboard get pods -l app.kubernetes.io/instance=scenario-02 --show-labels
```

**Fix.** Make the selector match the pod labels.

```bash
kubectl -n taskboard patch svc taskboard-broken-selector \
  -p '{"spec":{"selector":{"app.kubernetes.io/name":"taskboard-lite-broken","app.kubernetes.io/instance":"scenario-02"}}}'
kubectl -n taskboard get endpoints taskboard-broken-selector        # now lists the pod IP
kubectl -n taskboard port-forward svc/taskboard-broken-selector 8082:80 &
curl -s localhost:8082/health
```

**Observed output.**

```text
(paste the kubectl output here after running the scenario)
```

---

## 03 - Missing Secret key (`03-broken-secret-ref.yaml`)

**Bug.** `secretKeyRef.key: DB_PASS`; the Secret only contains `DB_PASSWORD`.

**Expected symptom.** `STATUS CreateContainerConfigError`, `READY 0/1`, no
restarts. `describe pod` ends with
`Error: couldn't find key DB_PASS in Secret taskboard/taskboard-secret`.
The image was pulled fine; the kubelet refuses to start the container
because it cannot build its environment.

```bash
kubectl apply -f troubleshooting/03-broken-secret-ref.yaml
kubectl -n taskboard get pods -l app.kubernetes.io/instance=scenario-03
kubectl -n taskboard describe pod -l app.kubernetes.io/instance=scenario-03 | grep -A3 "Error"
kubectl -n taskboard get secret taskboard-secret -o jsonpath='{.data}' | tr ',' '\n'    # which keys exist
```

**Fix.** Reference the key that exists.

```bash
kubectl -n taskboard patch deployment taskboard-broken-secret --type json \
  -p '[{"op":"replace","path":"/spec/template/spec/containers/0/env/0/valueFrom/secretKeyRef/key","value":"DB_PASSWORD"}]'
kubectl -n taskboard rollout status deployment/taskboard-broken-secret
```

**Observed output.**

```text
(paste the kubectl output here after running the scenario)
```

---

## 04 - Readiness probe on the wrong path (`04-broken-probe.yaml`)

**Bug.** `readinessProbe.httpGet.path: /readyz`; the app serves `/ready`.

**Expected symptom.** The pod is `Running` but stays `READY 0/1` forever
(liveness on `/health` passes, so it is not restarted). `describe pod`
repeats `Readiness probe failed: HTTP probe failed with statuscode: 404`.
The Service has no ready endpoints and the ingress host
`broken-probe.taskboard.local` answers **503 Service Temporarily Unavailable**.
With `kubectl port-forward` straight to the pod the app answers normally,
which proves the app is fine and only the probe is wrong.

```bash
kubectl apply -f troubleshooting/04-broken-probe.yaml
kubectl -n taskboard get pods -l app.kubernetes.io/instance=scenario-04
kubectl -n taskboard describe pod -l app.kubernetes.io/instance=scenario-04 | grep -i readiness
kubectl -n taskboard get endpoints taskboard-broken-probe
curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: broken-probe.taskboard.local' "http://$(minikube ip)/"   # 503
```

**Fix.** Probe the real endpoint.

```bash
kubectl -n taskboard patch deployment taskboard-broken-probe --type json \
  -p '[{"op":"replace","path":"/spec/template/spec/containers/0/readinessProbe/httpGet/path","value":"/ready"}]'
kubectl -n taskboard rollout status deployment/taskboard-broken-probe
curl -s -H 'Host: broken-probe.taskboard.local' "http://$(minikube ip)/health"                               # {"status":"ok"}
```

**Observed output.**

```text
(paste the kubectl output here after running the scenario)
```

---

## Clean up

```bash
kubectl delete -f troubleshooting/ --ignore-not-found
```

## Summary table

| # | Symptom in `kubectl get pods` | Where to look | Root cause | Fix |
|---|---|---|---|---|
| 01 | `ImagePullBackOff` | `describe pod` -> Events | image tag does not exist | correct tag / load image |
| 02 | pod fine, Service unreachable | `get endpoints` is `<none>` | selector and pod labels differ | align selector |
| 03 | `CreateContainerConfigError` | `describe pod` -> Error line | Secret key name wrong | correct `secretKeyRef.key` |
| 04 | `Running` but `0/1`, ingress 503 | `describe pod` -> readiness 404 | probe path wrong | correct probe path |
