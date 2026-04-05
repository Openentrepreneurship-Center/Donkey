#!/usr/bin/env bash
# EC2에서 실행: ECR 이미지 pull 후 API 블루–그린, Caddy reload, worker 갱신.
# GitHub Actions가 base64 디코드 후 /tmp에 두고 bash로 실행한다.
set -euo pipefail

ECR_REGISTRY="${ECR_REGISTRY:?}"
IMG="${ECR_REGISTRY}/donkey:latest"

echo "Logging in to ECR and pulling ${IMG}..."
aws ecr get-login-password --region ap-northeast-2 | docker login --username AWS --password-stdin "${ECR_REGISTRY}"
docker pull "${IMG}"

docker network create donkey-net 2>/dev/null || true

if ! docker ps -a --format '{{.Names}}' | grep -qx donkey-redis; then
  docker run -d --name donkey-redis --restart unless-stopped --network donkey-net redis:7-alpine
elif ! docker ps --format '{{.Names}}' | grep -qx donkey-redis; then
  docker start donkey-redis
fi
docker network connect donkey-net donkey-redis 2>/dev/null || true

docker rm -f donkey-api-candidate 2>/dev/null || true

echo "Starting donkey-api-candidate..."
docker run -d --name donkey-api-candidate --restart unless-stopped --network donkey-net \
  --link donkey-redis:redis --env-file /home/ec2-user/.env "${IMG}"

echo "Waiting for /health on candidate..."
for i in $(seq 1 30); do
  # alpine + wget: 별도 curl 이미지 태그 이슈·prune 후 재pull 부담 감소
  if docker run --rm --network donkey-net alpine:3.19 \
    sh -c 'wget -q -O /dev/null -T 5 http://donkey-api-candidate:8000/health' >/dev/null 2>&1; then
    echo "Candidate health OK (attempt ${i})"
    break
  fi
  if [ "${i}" -eq 30 ]; then
    echo "Health check failed for donkey-api-candidate"
    docker logs donkey-api-candidate 2>&1 | tail -80 || true
    exit 1
  fi
  sleep 2
done

printf '%s\n' 'donkey.ai.kr {' '    reverse_proxy donkey-api-candidate:8000' '}' > /home/ec2-user/Caddyfile

if docker ps --format '{{.Names}}' | grep -qx caddy; then
  docker exec caddy caddy reload --config /etc/caddy/Caddyfile
  echo "Caddy reloaded → donkey-api-candidate"
else
  echo "Starting Caddy (first run)"
  docker rm -f caddy 2>/dev/null || true
  docker run -d --name caddy --restart unless-stopped --network donkey-net -p 80:80 -p 443:443 \
    -v /home/ec2-user/Caddyfile:/etc/caddy/Caddyfile -v caddy_data:/data caddy:alpine
fi

if docker ps -a --format '{{.Names}}' | grep -qx donkey-api; then
  echo "Stopping previous donkey-api..."
  docker stop donkey-api 2>/dev/null || true
  docker rm donkey-api 2>/dev/null || true
fi

echo "Promoting candidate → donkey-api and pointing Caddy at stable name..."
docker rename donkey-api-candidate donkey-api
printf '%s\n' 'donkey.ai.kr {' '    reverse_proxy donkey-api:8000' '}' > /home/ec2-user/Caddyfile
docker exec caddy caddy reload --config /etc/caddy/Caddyfile

echo "Restarting worker with new image..."
docker stop donkey-worker 2>/dev/null || true
docker rm donkey-worker 2>/dev/null || true
docker run -d --name donkey-worker --restart unless-stopped --network donkey-net \
  --link donkey-redis:redis --env-file /home/ec2-user/.env "${IMG}" \
  uv run arq app.arq_worker.WorkerSettings

docker image prune -af

if docker ps --format '{{.Names}}' | grep -qx donkey-api \
  && docker ps --format '{{.Names}}' | grep -qx donkey-worker \
  && docker ps --format '{{.Names}}' | grep -qx caddy; then
  echo "Deployment successful!"
else
  docker logs donkey-api 2>/dev/null | tail -50 || true
  docker logs donkey-worker 2>/dev/null | tail -50 || true
  docker logs caddy 2>/dev/null | tail -50 || true
  exit 1
fi
