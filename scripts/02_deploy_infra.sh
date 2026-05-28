#!/usr/bin/env bash
# 02_deploy_infra.sh — 서버 인프라 배포
# Redis + central-hub + RBAC + ConfigMap
set -euo pipefail
source "$(dirname "$0")/common.sh"

section "인프라 배포 (Redis + central-hub)"

# ── ConfigMap 먼저 적용 ──────────────────────────────────────────
section "ConfigMap 적용"
kubectl apply -f deploy/base/configmaps/fleet-config.yaml
ok "fleet-config ConfigMap 적용"

# ── RBAC ────────────────────────────────────────────────────────
section "RBAC 적용"
kubectl apply -f apps/central-hub/manifests/rbac.yaml
ok "RBAC 적용"

# ── Redis ────────────────────────────────────────────────────────
section "Redis 배포"

# Redis 중복 방지:
# 기존 central-redis-deployment가 있으면 이를 canonical Redis로 사용하고,
# 새 redis-deployment는 만들지 않거나 삭제한다.
if kubectl get deployment -n "$NAMESPACE" central-redis-deployment &>/dev/null; then
  info "기존 central-redis-deployment 사용"
  kubectl delete deployment -n "$NAMESPACE" redis-deployment --ignore-not-found
  REDIS_DEPLOY="central-redis-deployment"
else
  kubectl apply -f apps/central-hub/manifests/redis-deployment.yaml
  REDIS_DEPLOY="redis-deployment"
fi

info "Redis Pod 준비 대기 중..."
kubectl rollout status deployment/"$REDIS_DEPLOY" -n "$NAMESPACE" --timeout=60s
ok "Redis 준비 완료: $REDIS_DEPLOY"

# Redis NodePort 보장: robot/link_proxy가 외부 경로로 접근할 때 사용
cat <<'EOF' | kubectl apply -f -
apiVersion: v1
kind: Service
metadata:
  name: redis-nodeport
  namespace: centralized
spec:
  type: NodePort
  selector:
    app: redis
  ports:
    - name: redis
      port: 6379
      targetPort: 6379
      nodePort: 30379
EOF
ok "redis-nodeport 적용"

# Redis 연결 확인
REDIS_POD=$(kubectl get pod -n "$NAMESPACE" -l app=redis \
  -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
if [[ -n "$REDIS_POD" ]]; then
  kubectl exec -n "$NAMESPACE" "$REDIS_POD" -- redis-cli ping | grep -q PONG \
    && ok "Redis PING 응답" \
    || warn "Redis PING 실패"
fi

# ── central-hub ─────────────────────────────────────────────────
section "central-hub 배포"
kubectl apply -f apps/central-hub/manifests/central-hub.yaml
info "central-hub Pod 준비 대기 중..."
kubectl rollout status deployment/central-hub -n "$NAMESPACE" --timeout=90s
ok "central-hub 준비 완료"

section "배포 결과"
kubectl get pods -n "$NAMESPACE" -o wide
kubectl get svc  -n "$NAMESPACE"

ok "완료 — 다음 단계: bash scripts/03_deploy_edge.sh"
