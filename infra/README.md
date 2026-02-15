# Donkey 인프라 구성

Donkey 서비스의 **인프라 구성 환경**을 설명하는 문서입니다.  
(Terraform 사용법이 아닌, 구성된 환경 자체에 대한 문서입니다.)

---

## 개요

| 항목 | 내용                                                         |
| ---- | ------------------------------------------------------------ |
| 리전 | ap-northeast-2 (서울)                                        |
| 목적 | Donkey API 서버 호스팅, 컨테이너 이미지 저장, 작업 로그 저장 |

**구성 요약:** EC2 한 대에 API 서버를 두고, 이미지는 ECR에서 관리하며, 작업 로그는 S3에 저장하는 구조입니다.

---

## 구성 환경 (아키텍처)

```
                    ┌─────────────────────────────────────────┐
                    │                  AWS                    │
                    │                                         │
  Internet          │   ┌─────────────┐    ┌───────────────┐  │
  ───────────────►  │   │ Elastic IP  │───►│ EC2 Instance  │  │
  :8000 (API)       │   └─────────────┘    │ (AL2 + Docker)│  │
                    │                      └───────┬───────┘  │
                    │                              │          │
                    │   ┌─────────────┐    ┌───────▼───────┐  │
                    │   │     ECR     │◄───│ IAM Role      │  │
                    │   │ (donkey)    │    │ (ECR, S3, SSM)│  │
                    │   └─────────────┘    └───────┬───────┘  │
                    │                              │          │
                    │   ┌─────────────┐            │          │
                    │   │ S3 (logs)   │◄───────────┘          │
                    │   │ 90일 보관   │                        │
                    │   └─────────────┘                        │
                    └─────────────────────────────────────────┘
```

---

## 구성 요소

### 연산·호스팅

| 구성 요소  | 식별자        | 설명                                                                  |
| ---------- | ------------- | --------------------------------------------------------------------- |
| EC2        | donkey-server | Amazon Linux 2, Docker/Docker Compose. 루트 디스크 30GB(gp3), 암호화. |
| Elastic IP | donkey-eip    | EC2에 고정 공인 IP 부여. API는 이 IP의 8000 포트로 제공.              |

### 컨테이너 이미지

| 구성 요소 | 식별자 | 설명                                                                         |
| --------- | ------ | ---------------------------------------------------------------------------- |
| ECR       | donkey | Donkey 컨테이너 이미지 저장소. push 시 이미지 스캔, 최근 10개 이미지만 유지. |

### 스토리지

| 구성 요소 | 식별자               | 설명                                                                            |
| --------- | -------------------- | ------------------------------------------------------------------------------- |
| S3        | donkey-logs-{계정ID} | 작업 로그 저장. 서버 측 암호화(AES256). 30일 후 STANDARD_IA 전환, 90일 후 삭제. |

### 보안·접근

| 구성 요소      | 식별자          | 설명                                                                    |
| -------------- | --------------- | ----------------------------------------------------------------------- |
| Security Group | donkey-sg       | 인바운드: TCP 8000(API). 아웃바운드: 전체 허용.                         |
| IAM Role       | donkey-ec2-role | EC2가 ECR 이미지 풀, S3 로그 읽기/쓰기, SSM(Session Manager) 사용 가능. |
| Key Pair       | donkey-key      | EC2 SSH용(선택). 프라이빗 키는 로컬 ~/.ssh/donkey.pem.                  |

---

## 환경 태그

주요 리소스에는 `Project = donkey`, `Environment = dev` 태그가 부여되어 있습니다.

---

## 기존 EC2 인스턴스에 DNS 연결하기

Terraform이 **새 인스턴스** 대신 **원래 쓰던 인스턴스**를 관리하도록 바꾸는 방법입니다.

### 1. 원래 인스턴스 ID 확인

- AWS 콘솔 EC2 목록에서 원래 쓰던 인스턴스의 **인스턴스 ID** (예: `i-0abc123...`) 확인
- 또는 SSM/SSH로 접속 중인 인스턴스 ID 확인

### 2. 원래 인스턴스에 붙어 있는 EIP Allocation ID 확인

```bash
# 원래 인스턴스 ID를 넣어서 해당 인스턴스에 붙은 EIP 조회
aws ec2 describe-addresses --filters "Name=instance-id,Values=i-원래인스턴스ID" \
  --profile donkey --region ap-northeast-2 \
  --query 'Addresses[0].AllocationId' --output text
```

나온 값이 `eipalloc-xxxx` 형태의 **Allocation ID**입니다.

### 3. Terraform state에서 새 인스턴스·새 EIP 제거

`infra` 디렉터리에서:

```bash
terraform state rm aws_instance.main aws_eip.main
```

(이제 Terraform은 “새 인스턴스/새 EIP”를 관리 대상에서 뺍니다. AWS에 있는 해당 리소스는 그대로 두고, 나중에 수동 종료/해제합니다.)

### 4. 원래 인스턴스·원래 EIP import

```bash
# 아래 OLD_INSTANCE_ID, OLD_EIP_ALLOC_ID 를 1·2에서 확인한 값으로 바꿈
terraform import aws_instance.main i-OLD_INSTANCE_ID
terraform import aws_eip.main eipalloc-OLD_EIP_ALLOC_ID
```

### 5. 적용

```bash
terraform apply
```

Route 53 A 레코드가 **원래 EIP**를 가리키도록 맞춰집니다.

### 6. 새로 만들어진 인스턴스·EIP 정리 (선택)

- AWS 콘솔에서 **Terraform이 만든 새 EC2** 인스턴스 종료
- 그 인스턴스에 붙었던 **Elastic IP** 해제(Release)

이렇게 하면 donkey.ai.kr 은 **원래 쓰던 인스턴스**의 8000 포트로 연결됩니다.
